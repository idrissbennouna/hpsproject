import json
import os
import re
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
try:
    from app.services.spec_loader import get_monitored_function_names, get_spec_context_for_functions
except Exception as _spec_loader_err:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "[agent_graph] Impossible d'importer spec_loader : %s. "
        "Les fonctions get_monitored_function_names et get_spec_context_for_functions "
        "seront des stubs no-op.",
        _spec_loader_err,
    )
    def get_monitored_function_names(*args, **kwargs): return []
    def get_spec_context_for_functions(*args, **kwargs): return ""
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


def _tx_match_key(tx: dict) -> str:
    """Clé de rapprochement RRN → STAN → transaction_id pour fusion parser/LLM."""
    if not isinstance(tx, dict):
        return ""
    for key in ("rrn", "stan", "transaction_id"):
        val = str(tx.get(key) or "").strip()
        if val:
            return f"{key}:{val}"
    return ""


_CHRONO_FAIL_FUNC_RE = re.compile(
    r"(?:"
    r"\b([A-Za-z][A-Za-z0-9_]{2,})\s*\(\s*\)|"
    r"(?:fonction|ex[ée]cution de|appel(?:\s+de)?)\s+([A-Za-z][A-Za-z0-9_]{2,})|"
    r"\b([A-Za-z][A-Za-z0-9_]{2,})\s*:\s*r[ée]sultat"
    r")",
    re.IGNORECASE,
)
_CHRONO_ERROR_RE = re.compile(
    r"\b(nok|échec|echec|error|failed|refuse)\b|-\s*[1-9]\d*|r[ée]sultat\s*-",
    re.IGNORECASE,
)


def _extract_failed_funcs_from_chronology(chronology) -> list:
    """Déduit les fonctions en échec depuis les étapes de chronologie LLM/parser."""
    if isinstance(chronology, str):
        steps = [s.strip(" -•\t") for s in chronology.splitlines() if s.strip()]
    elif isinstance(chronology, list):
        steps = [str(s).strip() for s in chronology if str(s).strip()]
    else:
        return []

    found = []
    seen = set()
    for step in steps:
        if not _CHRONO_ERROR_RE.search(step):
            continue
        m = _CHRONO_FAIL_FUNC_RE.search(step)
        if not m:
            continue
        name = next((g for g in m.groups() if g), None)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(name)
    return found


def _enrich_report_with_parser_data(report: dict, log_data_json: str) -> dict:
    """
    Réinjecte failed_functions (et champs utiles) depuis le parser dans le rapport LLM.

    Le schéma LLM omettait historiquement failed_functions : le frontend n'affichait
    alors jamais le bouton "?" (condition : failed_functions.length > 0).
    Cette fusion est déterministe et ne dépend pas du LLM.
    """
    if not isinstance(report, dict):
        return report

    try:
        parsed_txs = json.loads(log_data_json or "[]")
    except Exception:
        parsed_txs = []

    if not isinstance(parsed_txs, list):
        parsed_txs = []

    by_key = {}
    for ptx in parsed_txs:
        if not isinstance(ptx, dict):
            continue
        key = _tx_match_key(ptx)
        if key:
            by_key[key] = ptx

    report_txs = report.get("transactions")
    if not isinstance(report_txs, list):
        return report

    for idx, rtx in enumerate(report_txs):
        if not isinstance(rtx, dict):
            continue

        src = by_key.get(_tx_match_key(rtx))
        # Fallback positionnel si RRN/STAN absents côté LLM
        if src is None and idx < len(parsed_txs) and isinstance(parsed_txs[idx], dict):
            src = parsed_txs[idx]

        parser_failed = (src or {}).get("failed_functions") or []
        if not isinstance(parser_failed, list):
            parser_failed = []

        existing = rtx.get("failed_functions")
        if not isinstance(existing, list):
            existing = []

        chrono_failed = _extract_failed_funcs_from_chronology(rtx.get("chronology"))

        # Union ordonnée : parser → chronologie → LLM
        merged = []
        for fn in list(parser_failed) + list(chrono_failed) + list(existing):
            name = str(fn).strip() if fn is not None else ""
            if name and name not in merged:
                merged.append(name)
        rtx["failed_functions"] = merged

        if src and not rtx.get("processing_code") and src.get("processing_code"):
            rtx["processing_code"] = src.get("processing_code")

        # Synchroniser alerts ↔ failed_functions
        parser_alerts = (src or {}).get("alerts_found") or (src or {}).get("alerts") or []
        if not isinstance(parser_alerts, list):
            parser_alerts = []
        existing_alerts = rtx.get("alerts")
        if not isinstance(existing_alerts, list):
            existing_alerts = []

        synced_alerts = []
        for a in list(parser_alerts) + list(existing_alerts):
            text = str(a).strip() if a is not None else ""
            if text and text not in synced_alerts:
                synced_alerts.append(text)
        for fn in merged:
            if not any(fn.lower() in str(a).lower() for a in synced_alerts):
                synced_alerts.append(f"{fn}() a échoué.")
        rtx["alerts"] = synced_alerts

        if not (rtx.get("pistes_diagnostiques") or "").strip() and merged:
            rtx["pistes_diagnostiques"] = (
                f"Échec détecté sur : {', '.join(merged)}."
            )

    return report


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
        session_docs = session_db.similarity_search(search_q, k=8, filter={"session_id": doc_session_id})
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

def compliance_auditor_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 3 : combine la LogStory filtrée et le contexte de spec pour générer
    le rapport d'audit final sous forme d'un objet JSON structuré.
    """
    auditor_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Audit et Conformité Monétique pour les testeurs d'HPS.\n"
            "Ton rôle est de générer un rapport d'analyse sous forme d'un OBJET JSON STRUCTURÉ UNIQUEMENT "
            "(aucun texte de présentation, aucun bloc markdown prose en dehors du JSON) basé sur la liste des transactions "
            "et les spécifications techniques (RAG Context) fournies, EN SUIVANT STRICTEMENT LA DEMANDE DU TESTEUR "
            "ci-dessous (variable {user_prompt}).\n\n"
            "ADAPTATION AU FORMAT DE TRACE (NEUTRALITÉ VENDOR) :\n"
            "- Les transactions peuvent provenir de formats variés : PowerCARD / ISO 8583 (identifiants de champs préfixés 'FLD'), "
            "Mastercard (préfixe 'DE'), POS/EMV (tags TLV hexadécimaux), ou tout autre format propriétaire.\n"
            "- Tu ne dois JAMAIS supposer une nomenclature fixe. Identifie le format à partir des données fournies "
            "dans `all_fields` (chaque entrée contient : numéro, valeur, name, description).\n"
            "- Dans toutes tes analyses, utilise le terme neutre 'identifiant de champ réseau' plutôt que 'FLD' ou 'DE'. "
            "Pour les valeurs concrètes dans le JSON de sortie (field_number, response_code, processing_code, rrn), "
            "reproduis EXACTEMENT la notation que tu observes dans les données : "
            "si all_fields contient '039' avec name='Response Code', utilise la notation présente "
            "(ex: 'FLD 039', 'DE039', 'Field 39', ou simplement '039') — ne réécris pas.\n"
            "- Si une transaction est marquée `parsing_mode='ai_assisted'` ou `llm_fallback=true`, "
            "c'est qu'elle a été extraite par IA depuis un format non standard. "
            "Mentionne-le explicitement dans `pistes_diagnostiques` : "
            "\"Analyse réalisée en mode d'interprétation assistée par IA — format de trace non standard détecté.\"\n\n"
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
            '      "stan": <string — numéro de trace système (STAN, trace number, ou équivalent)>,\n'
            '      "rrn": <string — identifiant de référence réseau (RRN, retrieval ref, ou équivalent selon le format)>,\n'
            '      "processing_code": <string — code de traitement (identifiant de champ réseau 3 ou DE003 ou équivalent selon le format)>,\n'
            '      "response_code": <string — code réponse (identifiant de champ réseau 39 ou DE039 ou équivalent selon le format)>,\n'
            '      "response_code_label": <string, ex: "Approuvée" ou "Déclinée">,\n'
            '      "approval_status": <"approved" | "declined">,\n'
            '      "alerts": [<string>, ...],\n'
            '      "failed_functions": [<string, noms EXACTS des fonctions en échec issus de failed_functions dans les données parser>, ...],\n'
            '      "pistes_diagnostiques": <string — courte piste si des fonctions ont échoué, ou si mode IA assistée détecté, sinon "">,\n'
            '      "chronology": [<string>, ...]\n'
            "    }},\n"
            "  ],\n"
            '  "field_analysis": [\n'
            "    {{\n"
            '      "field_number": <string — notation EXACTE observée dans la trace (ex: "FLD 039", "DE039", "039", "9F26", etc.)>,\n'
            '      "field_name": <string — nom sémantique du champ tel que fourni dans all_fields[].name ou le référentiel ISO>,\n'
            '      "expected_type": <string, ex: "2 AN" ou "12 N">,\n'
            '      "source": <string — "Standard ISO 8583", "Référentiel Mastercard", fichier PDF uploadé, "Type inféré par IA", etc.>,\n'
            '      "observed_value": <string, ex: "(vide)" ou "00">,\n'
            '      "non_conformity_type": <string>,\n'
            '      "compliance_note": <string — note explicative sur la non-conformité>\n'
            "    }}\n"
            "  ]\n"
            "}}\n\n"
            "Règles :\n"
            "- IMPORTANT : le JSON des transactions fourni contient TOUTES les transactions de la trace. Traite-les toutes.\n"
            "- Pour chaque transaction avec un champ `alerts_found` non vide, passe `is_suspicious` à true et renseigne `alerts` "
            "avec de courts libellés d'alerte.\n"
            "- OBLIGATOIRE : copie telle quelle la liste `failed_functions` de chaque transaction parser vers le champ "
            "`failed_functions` du rapport (noms exacts). Si la liste parser est vide, mets `[]`. "
            "Ne renomme et n'omets aucune fonction.\n"
            "- OBLIGATOIRE : le tableau `alerts` doit contenir AU MOINS une alerte pour CHAQUE entrée de `failed_functions`. "
            "Ne fusionne pas plusieurs fonctions en une seule alerte.\n"
            "- Dans `chronology`, si tu mentionnes un résultat -1/NOK pour une fonction, cette fonction DOIT aussi figurer "
            "dans `failed_functions` et `alerts`.\n"
            "- Remplis `field_analysis` STRICTEMENT à partir des informations présentes dans `format_alerts`. "
            "Pour field_number, reproduis la notation exacte telle qu'elle apparaît dans la trace (FLD, DE, Field, tag TLV, etc.). "
            "Si source_file indique 'Type inféré par IA', répercute cette information dans le champ `source`.\n"
            "- Si le testeur demande UNIQUEMENT la story, retourne `alerts` et `field_analysis` sous forme de listes vides `[]` "
            "et `suspicious_count` à 0.\n"
            "- Si la demande est d'analyser le fichier ou les alertes/justifications/pistes, remplis l'intégralité des sections.\n"
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
            final_data = _enrich_report_with_parser_data(
                parsed_json, state.get("log_data_json", "[]")
            )
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