import json
import os
import time
from pathlib import Path
from typing import Dict, Any

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from typing_extensions import TypedDict
from pydantic import SecretStr

from app.services.log_parser import parse_trace_file_for_story
from app.services.spec_loader import get_monitored_function_names, get_spec_context_for_functions
from app.rag.retriever import query_specs
from app.services.llm_util import invoke_llm_with_retry
from app.services.token_tracker import extract_token_usage, record_usage

# Avant : load_dotenv() sans argument -> cherche le .env dans le cwd, ce qui
# casse si uvicorn n'est pas lancé exactement depuis la racine de backend/.
# Maintenant : chemin explicite, indépendant du dossier depuis lequel on lance la commande.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# --- CONFIGURATION (pilotable via .env) ---
_BACKEND_DIR = _ENV_PATH.parent
LOG_STORAGE_DIR = os.getenv("LOG_STORAGE_DIR", str(_BACKEND_DIR / "app" / "storage"))
raw_model = os.getenv("GEMINI_MODEL_NAME", "gemini-3.5-flash")
GEMINI_MODEL_NAME = raw_model.strip() if raw_model else "gemini-3.5-flash"
# Avant : le rapport ne montrait QUE les transactions "suspectes" (avec alerte),
# avec un fallback vers les N premières SEULEMENT si aucune alerte n'existait.
# Résultat : les transactions saines étaient silencieusement masquées du rapport.
# Maintenant : on transmet TOUJOURS toutes les transactions (non-heartbeat) au LLM,
# les suspectes étant simplement remontées en tête de liste pour être mises en avant.
# MAX_TOTAL_TRANSACTIONS reste un garde-fou anti-explosion de prompt sur un fichier
# avec des centaines de transactions, pas un filtre métier.
MAX_TOTAL_TRANSACTIONS = int(os.getenv("MAX_TOTAL_TRANSACTIONS", "20"))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

# Affichage des valeurs résolues au démarrage
_masked_key = GOOGLE_API_KEY[:6] + "..." if GOOGLE_API_KEY else "None"
print(f"[STARTUP agent_graph.py] GEMINI_MODEL_NAME={GEMINI_MODEL_NAME}, GOOGLE_API_KEY={_masked_key} loaded from {_ENV_PATH}")

if not GOOGLE_API_KEY:
    raise RuntimeError(
        f"Clé API Gemini introuvable. Vérifie que GOOGLE_API_KEY ou GEMINI_API_KEY "
        f"est bien défini dans '{_ENV_PATH}' (fichier trouvé : {_ENV_PATH.exists()})."
    )


# --- 1. DÉFINITION DE L'ÉTAT DU GRAPHE ---
class AgentState(TypedDict):
    user_prompt: str
    current_agent: str
    rag_context: str
    log_data_json: str
    final_response: str
    file_name: str
    doc_session_id: str  # Conservé de ta version


llm = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL_NAME,
    temperature=0,
    google_api_key=SecretStr(GOOGLE_API_KEY),
)


def _resolve_log_path(filename: str) -> str:
    """Cherche le fichier de trace dans le(s) dossier(s) de stockage configuré(s)."""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    candidates = [
        os.path.join(LOG_STORAGE_DIR, filename),
        os.path.join(project_root, LOG_STORAGE_DIR, filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# --- NOEUD 1 : PARSER & CHRONOLOGY AGENT ---
def parser_story_node(state: AgentState) -> Dict[str, Any]:
    filename = state.get("file_name")
    if not filename:
        error_json = json.dumps({"error": "Aucun 'file_name' fourni dans l'état de l'agent."})
        return {"log_data_json": error_json, "current_agent": "ParserAgent"}

    log_file_path = _resolve_log_path(filename)
    if not log_file_path:
        error_json = json.dumps(
            {"error": f"Impossible de trouver le fichier '{filename}' dans '{LOG_STORAGE_DIR}'"}
        )
        return {"log_data_json": error_json, "current_agent": "ParserAgent"}

    doc_session_id = state.get("doc_session_id")
    all_parsed_transactions = parse_trace_file_for_story(log_file_path, doc_session_id=doc_session_id)

    # Filtrage explicite des heartbeats (0800/0810) : jamais des transactions métier
    filtered_transactions = [tx for tx in all_parsed_transactions if not tx.get("is_heartbeat")]

    # Toutes les transactions sont transmises au rapport. Les suspectes (avec
    # alertes_found non vide) sont simplement remontées en tête de liste pour
    # que le LLM les mette en avant, sans que les transactions saines soient
    # masquées du rapport.
    suspicious_transactions = [tx for tx in filtered_transactions if tx.get("alerts_found")]
    clean_transactions = [tx for tx in filtered_transactions if not tx.get("alerts_found")]
    ordered_transactions = suspicious_transactions + clean_transactions

    transactions_to_report = ordered_transactions[:MAX_TOTAL_TRANSACTIONS]

    job_id = state.get("doc_session_id") or state.get("file_name")
    if job_id:
        from app.services.job_tracker import update_job
        update_job(job_id, stage="parsing_trace", detail="Analyse et parsing du fichier de traces...", progress_pct=10)

    log_data_json = json.dumps(transactions_to_report, indent=2, ensure_ascii=False)

    return {"log_data_json": log_data_json, "current_agent": "ParserAgent"}


# --- NOEUD 2 : RAG SPECIFICATION RETRIEVER ---
def rag_spec_retriever_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 2 : si un document de spécification PDF a été joint pour cette analyse (doc_session_id),
    interroge la base vectorielle de session ("hps_session_files") pour extraire les règles applicables.
    Si aucun document n'a été fourni, ne fait AUCUN appel RAG et renvoie un message explicite.
    """
    doc_session_id = state.get("doc_session_id")
    
    if not doc_session_id or not str(doc_session_id).strip():
        return {
            "rag_context": "Aucun document de spécification fourni pour cette analyse.",
            "current_agent": "RagRetrieverAgent"
        }

    try:
        log_data = json.loads(state.get("log_data_json", "[]"))
    except Exception:
        log_data = []

    detected_errors = []
    if isinstance(log_data, list):
        for tx in log_data:
            if isinstance(tx, dict):
                for func in tx.get("failed_functions", []):
                    if func not in detected_errors:
                        detected_errors.append(func)

    query_str = " ".join(detected_errors) if detected_errors else state.get("user_prompt", "")
    search_q = query_str if query_str.strip() else "spécification"

    session_spec_context = ""
    try:
        from app.rag.retriever import get_session_vectorstore
        session_db = get_session_vectorstore()
        session_docs = session_db.similarity_search(search_q, k=4, filter={"session_id": doc_session_id})
        if session_docs:
            doc_snippets = []
            for d in session_docs:
                src = d.metadata.get("source", "Document de session")
                pg = d.metadata.get("page")
                pg_str = f" (Page {pg})" if pg else ""
                doc_snippets.append(f"[{src}{pg_str}]\n{d.page_content.strip()}")
            session_spec_context = "\n\n".join(doc_snippets)
    except Exception as e:
        print(f"[RAG_SESSION_RETRIEVAL_ERR] Impossible d'interroger les documents de session '{doc_session_id}' : {e}")

    if session_spec_context.strip():
        rag_extracted_rules = (
            f"=== DOCUMENT DE SPÉCIFICATION FOURNI POUR CETTE ANALYSE ===\n{session_spec_context.strip()}"
        )
    else:
        rag_extracted_rules = (
            f"Aucun extrait de spécification correspondant n'a été trouvé dans le document joint pour cette session."
        )

    return {"rag_context": rag_extracted_rules, "current_agent": "RagRetrieverAgent"}


# --- NOEUD 3 : COMPLIANCE AUDITOR ---
def compliance_auditor_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 3 : combine la LogStory filtrée et le contexte de spec pour générer
    le rapport d'audit final sous forme d'un objet JSON structuré.
    """
    job_id = state.get("doc_session_id") or state.get("file_name")
    if job_id:
        from app.services.job_tracker import update_job
        update_job(job_id, stage="generating_report", detail="Génération du rapport d'audit par l'Agent Compliance (LLM)...", progress_pct=60)

    auditor_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Audit et Conformité Monétique pour les testeurs d'HPS.\n"
            "Ton rôle est de générer un rapport d'analyse sous forme d'un OBJET JSON STRUCTURÉ UNIQUEMENT "
            "(aucun texte de présentation, aucun bloc markdown prose en dehors du JSON) basé sur la liste des transactions "
            "et les spécifications techniques (RAG Context) fournies, EN SUIVANT STRICTEMENT LA DEMANDE DU TESTEUR "
            "ci-dessous (variable {user_prompt}).\n\n"
            "Format du JSON de réponse (respecte scrupuleusement la structure des clés et les types) :\n"
            "{{\n"
            '  "summary": {{\n'
            '    "total_transactions": <int>,\n'
            '    "suspicious_count": <int>,\n'
            '    "approved_count": <int>,\n'
            '    "declined_count": <int>\n'
            "  }},\n"
            '  "transactions": [\n'
            "    {{\n"
            '      "transaction_id": <string, ex: "TXN-1">,\n'
            '      "is_suspicious": <boolean>,\n'
            '      "pan_masked": <string, masquer tous sauf les 4 derniers chiffres ex: "•••• •••• •••• 1991">,\n'
            '      "stan": <string>,\n'
            '      "rrn": <string>,\n'
            '      "response_code": <string>,\n'
            '      "response_code_label": <string, ex: "Approuvée" ou "Déclinée">,\n'
            '      "approval_status": <"approved" | "declined">,\n'
            '      "alerts": [<string>, ...],\n'
            '      "chronology": [<string>, ...]\n'
            "    }}\n"
            "  ],\n"
            '  "field_analysis": [\n'
            "    {{\n"
            '      "field_number": <string, ex: "FLD 039">,\n'
            '      "field_name": <string, ex: "Response Code">,\n'
            '      "spec_description": <string>,\n'
            '      "spec_rules": [<string>, ...],\n'
            '      "observed_examples": [\n'
            "        {{\n"
            '          "transaction_ids": [<string>, ...],\n'
            '          "value": <string>,\n'
            '          "declared_length": <string>,\n'
            '          "note": <string>\n'
            "        }}\n"
            "      ],\n"
            '      "compliance_note": <string>\n'
            "    }}\n"
            "  ]\n"
            "}}\n\n"
            "Règles :\n"
            "- IMPORTANT : le JSON des transactions fourni contient TOUTES les transactions de la trace. Traite-les toutes.\n"
            "- Pour chaque transaction avec un champ `alerts_found` non vide, passe `is_suspicious` à true et renseigne les `alerts` avec de courts libellés d'alerte.\n"
            "- Si le testeur demande UNIQUEMENT la story (sans alertes ni justification), retourne le JSON avec `alerts` et `field_analysis` sous forme de listes vides `[]` et `suspicious_count` à 0.\n"
            "- Si la demande est d'analyser le fichier ou demande les alertes/justifications/pistes, remplis l'intégralité des sections `summary`, `transactions` et `field_analysis`.\n"
            "- Réponds STRICTEMENT et UNIQUEMENT avec l'objet JSON valide sans texte avant ou après."
        )),
        ("user", (
            "Prompt de l'utilisateur : {user_prompt}\n\n"
            "Données des transactions (JSON complet, TOUTES les transactions de la trace) :\n{log_data_json}\n\n"
            "Spécifications Applicables (RAG Context) :\n{rag_context}"
        )),
    ])

    response = invoke_llm_with_retry(llm, auditor_prompt.format_messages(
        user_prompt=state.get("user_prompt"),
        log_data_json=state.get("log_data_json"),
        rag_context=state.get("rag_context"),
    ))

    try:
        record_usage("ComplianceAuditor", extract_token_usage(response))
    except Exception as token_err:
        print(f"⚠️ Échec best-effort du tracking de tokens : {token_err}")

    content = response.content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", str(block)))
            elif hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        normalized_response = "\n".join(parts)
    elif content is None:
        normalized_response = ""
    else:
        normalized_response = str(content)

    # Nettoyage et parsing JSON côté serveur
    cleaned_text = normalized_response.strip()
    if cleaned_text.startswith("```"):
        cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text, flags=re.IGNORECASE)
        cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
        cleaned_text = cleaned_text.strip()

    try:
        parsed_json = json.loads(cleaned_text)
        if isinstance(parsed_json, dict) and ("summary" in parsed_json or "transactions" in parsed_json):
            final_data = parsed_json
        else:
            final_data = {"raw_fallback": normalized_response}
    except Exception as parse_err:
        print(f"⚠️ Failed to parse LLM response as JSON: {parse_err}")
        final_data = {"raw_fallback": normalized_response}

    return {"final_response": final_data, "current_agent": "ComplianceAuditorAgent"}


# 2. Construction et compilation du Workflow LangGraph
workflow = StateGraph(AgentState)

workflow.add_node("ParserStoryBuilder", parser_story_node)
workflow.add_node("RagRetriever", rag_spec_retriever_node)
workflow.add_node("ComplianceAuditor", compliance_auditor_node)

workflow.set_entry_point("ParserStoryBuilder")
workflow.add_edge("ParserStoryBuilder", "RagRetriever")
workflow.add_edge("RagRetriever", "ComplianceAuditor")
workflow.add_edge("ComplianceAuditor", END)

compliance_agent_app = workflow.compile()