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
# NB: ajuste le nombre de .parent si agent_graph.py n'est pas dans app/core/ ou app/services/
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# --- CONFIGURATION (avant : hardcodée, maintenant pilotable via .env) ---
_BACKEND_DIR = _ENV_PATH.parent
LOG_STORAGE_DIR = os.getenv("LOG_STORAGE_DIR", str(_BACKEND_DIR / "app" / "storage"))
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
MAX_SUSPICIOUS_TRANSACTIONS = int(os.getenv("MAX_SUSPICIOUS_TRANSACTIONS", "10"))
MAX_FALLBACK_TRANSACTIONS = int(os.getenv("MAX_FALLBACK_TRANSACTIONS", "5"))

# Avant : google_api_key=os.getenv("GOOGLE_API_KEY") uniquement -> si le .env
# ne contient que GEMINI_API_KEY, None écrase la détection automatique de la lib.
# Maintenant : on accepte les deux noms, avec une erreur explicite si aucun n'est trouvé
# (plutôt qu'un ValidationError pydantic opaque à l'import du module).
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
    """
    Étape 1 : utilise le parser local pour extraire les jalons et ne garde
    que les transactions suspectes (anomalies) pour éviter le gaspillage de tokens.
    """
    filename = state.get("file_name")
    if not filename:
        # Avant : fallback silencieux vers "BASE1_LCH_2.TRC019.TXT" (typo incluse).
        # Maintenant : on exige explicitement le nom du fichier, pas de valeur cachée.
        error_json = json.dumps({"error": "Aucun 'file_name' fourni dans l'état de l'agent."})
        return {"log_data_json": error_json, "current_agent": "ParserAgent"}

    log_file_path = _resolve_log_path(filename)
    if not log_file_path:
        error_json = json.dumps(
            {"error": f"Impossible de trouver le fichier '{filename}' dans '{LOG_STORAGE_DIR}'"}
        )
        return {"log_data_json": error_json, "current_agent": "ParserAgent"}

    all_parsed_transactions = parse_trace_file_for_story(log_file_path)

    # STRATÉGIE INGÉNIEUR : on ne garde que les transactions suspectes (avec alertes)
    suspicious_transactions = [tx for tx in all_parsed_transactions if tx.get("alerts_found")]

    if not suspicious_transactions:
        suspicious_transactions = all_parsed_transactions[:MAX_FALLBACK_TRANSACTIONS]
    else:
        suspicious_transactions = suspicious_transactions[:MAX_SUSPICIOUS_TRANSACTIONS]

    condensed_json = json.dumps(suspicious_transactions, indent=2, ensure_ascii=False)

    return {"log_data_json": condensed_json, "current_agent": "ParserAgent"}


# --- NOEUD 2 : RAG SPECIFICATION RETRIEVER (dynamique, plus de texte écrit à la main) ---
def rag_spec_retriever_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 2 : extrait les fonctions en échec détectées par le parser et va
    chercher leur VRAIE spécification dans la base vectorielle pgvector
    via query_specs(), ou fallback local si non disponible.
    """
    time.sleep(1)  # Temporisation de sécurité API

    try:
        log_data = json.loads(state.get("log_data_json", "[]"))
    except Exception:
        log_data = []

    monitored_functions = get_monitored_function_names()

    detected_errors = []
    if isinstance(log_data, list):
        for tx in log_data:
            if isinstance(tx, dict):
                for func in tx.get("failed_functions", []):
                    if func not in detected_errors:
                        detected_errors.append(func)

    if detected_errors:
        query_str = " ".join(detected_errors)
        rag_extracted_rules = query_specs(query_str, k=2)
        if not rag_extracted_rules.strip():
            rag_extracted_rules = get_spec_context_for_functions(detected_errors)
        if not rag_extracted_rules.strip():
            rag_extracted_rules = (
                f"ALERTE(S) DÉTECTÉE(S) sur la ou les fonction(s) suivante(s) : "
                f"{', '.join(detected_errors)}. Aucune spécification correspondante n'a été "
                "trouvée ni dans la base vectorielle pgvector ni dans le fallback Excel "
                "Spec_PowerCARD.xlsx — une vérification manuelle de ces fonctions est requise."
            )
    else:
        rag_extracted_rules = (
            "Aucune anomalie détectée sur les fonctions métier surveillées "
            f"({', '.join(monitored_functions)}). Aucune spécification à mobiliser."
        )

    return {"rag_context": rag_extracted_rules, "current_agent": "RagRetrieverAgent"}


# --- NOEUD 3 : COMPLIANCE AUDITOR ---
def compliance_auditor_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 3 : combine la LogStory filtrée et le contexte de spec pour générer
    le rapport d'audit final structuré.
    """
    auditor_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Audit et Conformité Monétique pour les testeurs d'HPS.\n"
            "Ton rôle est de générer un rapport d'analyse basé sur la liste des transactions et les "
            "spécifications techniques (RAG Context) fournies, EN SUIVANT STRICTEMENT LA DEMANDE DU TESTEUR "
            "ci-dessous (variable {user_prompt}) : n'inclus que ce qui est demandé, ni plus, ni moins.\n\n"
            "Tu disposes des éléments suivants, à utiliser SI ET SEULEMENT SI la demande du testeur le justifie :\n"
            "- La Story chronologique (les jalons) de chaque autorisation listée dans le JSON.\n"
            "- Les ALERTES rencontrées (statuts != OK ou NOK -1).\n"
            "- La justification de chaque alerte en faisant le lien avec le RAG Context fourni.\n"
            "- Des pistes de diagnostic (tables SQL ou configurations de routage à vérifier).\n\n"
            "Règles :\n"
            "- Si le testeur demande uniquement la story, ne restitue QUE la story, sans mentionner les alertes "
            "ni ajouter de justification ou de pistes de diagnostic, même si des alertes existent dans les données.\n"
            "- Si le testeur demande explicitement les alertes, la justification ou les pistes de diagnostic, "
            "inclus les sections correspondantes.\n"
            "- Si la demande est ambiguë ou générique (ex: \"analyse ce fichier\"), tu peux alors produire le "
            "rapport complet (story + alertes + justification + pistes) par défaut.\n"
            "- Ne réponds jamais avec plus de sections que ce que la demande justifie."
        )),
        ("user", (
            "Prompt de l'utilisateur : {user_prompt}\n\n"
            "Données des transactions (JSON filtré des anomalies) :\n{log_data_json}\n\n"
            "Spécifications Applicables (RAG Context) :\n{rag_context}"
        )),
    ])

    # Invocation du modèle avec mécanisme de retry automatique
    response = invoke_llm_with_retry(llm, auditor_prompt.format_messages(
        user_prompt=state.get("user_prompt"),
        log_data_json=state.get("log_data_json"),
        rag_context=state.get("rag_context"),
    ))

    # Tracking de tokens best-effort
    try:
        record_usage("ComplianceAuditor", extract_token_usage(response))
    except Exception as token_err:
        print(f"⚠️ Échec best-effort du tracking de tokens : {token_err}")

    # Normalisation sécurisée de response.content
    content = response.content
    if isinstance(content, list):
        print(f"⚠️ [WARNING] response.content is a list instead of string! Normalizing list: {content}")
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

    return {"final_response": normalized_response, "current_agent": "ComplianceAuditorAgent"}


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