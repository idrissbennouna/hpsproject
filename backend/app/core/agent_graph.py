import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("agent_graph")

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from typing_extensions import TypedDict
from pydantic import SecretStr

from app.services.log_parser import parse_trace_file
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


def _lookup_hsm_code_explanation(hsm_code: str, doc_session_id: Optional[str] = None) -> str:
    """Recherche la signification d'un code retour HSM dans le PDF de spec PUGD0537-004 via RAG."""
    if not hsm_code or hsm_code in ["00", "0000", "0"]:
        return "Exécution HSM normale."

    query = f"HsmResultCode {hsm_code} code HSM {hsm_code} erreur HSM"
    explanation = ""

    if doc_session_id:
        try:
            from app.rag.retriever import get_session_vectorstore
            session_db = get_session_vectorstore()
            session_docs = session_db.similarity_search(query, k=2, filter={"session_id": doc_session_id})
            if session_docs:
                explanation = session_docs[0].page_content.strip()
        except Exception:
            pass

    if not explanation:
        try:
            from app.rag.retriever import query_specs
            explanation = query_specs(query, k=1)
        except Exception:
            pass

    if explanation:
        cleaned = re.sub(r"\s+", " ", explanation)
        sentences = [s.strip() for s in cleaned.split(".") if len(s.strip()) > 10]
        if sentences:
            short_str = ". ".join(sentences[:2]) + "."
            if len(short_str) > 200:
                short_str = short_str[:197] + "..."
            return f"Code {hsm_code} : {short_str}"

    return f"Code {hsm_code} : Erreur retournée par le module HSM."


def _generate_pistes_diagnostiques(tx: dict, failed_funcs: list, alerts: list, last_hsm: Optional[dict], status: str) -> str:
    """Génère une courte synthèse diagnostique factuelle (2-3 phrases max) pour les transactions avec anomalie."""
    if not failed_funcs and not alerts and status == "approved":
        return "Transaction traitée avec succès sans anomalie."

    parts = []
    if failed_funcs:
        func_names = [f.get("function", str(f)) if isinstance(f, dict) else str(f) for f in failed_funcs]
        parts.append(f"Échec détecté sur la/les fonction(s) : {', '.join(func_names)}.")

    if last_hsm and last_hsm.get("code_resultat") not in ["00", "0000", "0", None]:
        cmd = last_hsm.get("commande", "HSM")
        code = last_hsm.get("code_resultat")
        parts.append(f"Erreur de traitement HSM sur la commande '{cmd}' (Code {code}).")

    if alerts:
        alert_str = "; ".join(alerts[:2])
        parts.append(f"Alertes : {alert_str}.")

    impact = "Déclin de la transaction" if status == "declined" else "Impact potentiel sur la validation de sécurité"
    parts.append(f"Impact : {impact}.")

    return " ".join(parts)


def format_condensed_transaction_for_compliance(
    tx: dict, doc_session_id: Optional[str] = None, hsm_cache: Optional[dict] = None
) -> dict:
    """
    Construit une extraction condensée par transaction pour ComplianceAuditor (sans chronologie brute ligne par ligne).
    Contient uniquement identifiants, alertes/fonctions en échec, pistes diagnostiques et dernier échange HSM.
    """
    idents = tx.get("identifiers", {})
    pan_raw = idents.get("pan")
    if pan_raw and len(pan_raw) >= 4:
        pan_masked = f"•••• •••• •••• {pan_raw[-4:]}"
    else:
        pan_masked = "Non fourni / Inconnu"

    val_rc = idents.get("response_code")
    status = "approved" if val_rc in ["00", "000"] else "declined"

    alerts = list(tx.get("alerts_found") or tx.get("alerts") or [])
    failed_funcs = list(tx.get("failed_functions") or [])
    succ_funcs_count = len(tx.get("successful_functions") or [])

    # Extraction du dernier échange HSM
    last_hsm = None
    hsm_calls = tx.get("hsm_calls") or []
    last_cmd = tx.get("last_hsm_cmd")
    last_res = tx.get("last_hsm_result")

    if not last_cmd or not last_res:
        for ev in reversed(tx.get("events", [])):
            if not last_cmd and ("TO HSM" in ev or "Commande transmise au HSM" in ev):
                m_cmd = re.search(r"(?:TO HSM|Commande transmise au HSM).*?(?:Data=\[?|Command=\[?|-->\s*)([A-Z0-9]{2,6})", ev)
                if m_cmd:
                    last_cmd = m_cmd.group(1)
            if not last_res and ("HsmResultCode" in ev or "Code Résultat HSM" in ev or "FROM HSM" in ev):
                m_res = re.search(r"(?:HsmResultCode|Code Résultat HSM).*?[:=]\s*\[?(\w+)", ev)
                if m_res:
                    last_res = m_res.group(1)
            if last_cmd and last_res:
                break

    if last_cmd or last_res or hsm_calls:
        res_code = last_res or "00"
        cmd_name = last_cmd or (hsm_calls[-1] if hsm_calls else "HSM_CMD")

        exp_pdf = "Exécution normale."
        if res_code and res_code not in ["00", "0000", "0"]:
            if hsm_cache is not None and res_code in hsm_cache:
                exp_pdf = hsm_cache[res_code]
            else:
                exp_pdf = _lookup_hsm_code_explanation(res_code, doc_session_id)
                if hsm_cache is not None:
                    hsm_cache[res_code] = exp_pdf

        last_hsm = {
            "commande": cmd_name,
            "code_resultat": res_code,
            "explication_pdf": exp_pdf
        }

    pistes_diag = _generate_pistes_diagnostiques(tx, failed_funcs, alerts, last_hsm, status)

    # Extraction du Processing Code (FLD 003 / ISO 8583 Processing Code)
    processing_code_raw = tx.get("all_fields", {}).get("003", {})
    processing_code = processing_code_raw.get("value") if isinstance(processing_code_raw, dict) else None

    # Non-conformités de champs : extraites depuis les alertes de format
    field_violations = []
    for a in alerts:
        if isinstance(a, dict) and "field_number" in a:
            field_violations.append(a)
        elif isinstance(a, str) and a.startswith("Field "):
            # Alertes texte brut issues de validate_transaction_fields via _add_event
            pass  # Les non-conformités structurées sont dans tx['alerts'] via validate_transaction_fields

    # Extraire les non-conformités structurées depuis les champs de la transaction
    from app.services.field_validator import validate_transaction_fields
    raw_violations = validate_transaction_fields(tx.get("all_fields", {}), session_id=doc_session_id)
    for v in raw_violations:
        if v not in field_violations:
            field_violations.append(v)

    return {
        "identifiers": {
            "transaction_id": idents.get("transaction_id") or f"TXN-{idents.get('stan', '1')}",
            "mti": tx.get("mti"),
            "mti_description": tx.get("mti_description"),
            "stan": idents.get("stan"),
            "pan_masked": pan_masked,
            "rrn": idents.get("rrn"),
            "response_code": val_rc,
            "approval_status": status,
            "processing_code": processing_code,
        },
        "alerts": alerts,
        "failed_functions": failed_funcs,
        "successful_functions_count": succ_funcs_count,
        "pistes_diagnostiques": pistes_diag,
        "dernier_hsm": last_hsm,
        "field_violations": field_violations,
    }


def _clean_and_parse_json(normalized_response: str, llm_instance=None) -> Dict[str, Any]:
    """Nettoie le texte de réponse du LLM et parse en JSON structuré, avec fallback et réparation si besoin."""
    cleaned_text = normalized_response.strip()
    if cleaned_text.startswith("```"):
        cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text, flags=re.IGNORECASE)
        cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
        cleaned_text = cleaned_text.strip()

    try:
        parsed_json = json.loads(cleaned_text)
        if isinstance(parsed_json, dict):
            return parsed_json
    except Exception as parse_err:
        logger.error(f"⚠️ [JSON_PARSE_ERROR] Failed to parse LLM response as JSON: {parse_err}")
        if llm_instance:
            try:
                logger.info("[JSON_REPAIR_ATTEMPT] Tentative de réparation du JSON invalide...")
                repair_prompt = ChatPromptTemplate.from_messages([
                    ("system", "Tu es un assistant expert en correction de formatage JSON. Ta tâche est de convertir le texte brut fourni en un OBJET JSON STRICTEMENT VALIDE. Ne renvoie rien d'autre que le JSON valide sans markdown, sans prose."),
                    ("user", "Corrige et formate le texte suivant en JSON valide :\n{invalid_text}")
                ])
                repair_resp = invoke_llm_with_retry(llm_instance, repair_prompt.format_messages(invalid_text=cleaned_text))
                repair_content = getattr(repair_resp, "content", str(repair_resp))
                repair_text = str(repair_content).strip()
                if repair_text.startswith("```"):
                    repair_text = re.sub(r"^```(?:json)?\s*", "", repair_text, flags=re.IGNORECASE)
                    repair_text = re.sub(r"\s*```$", "", repair_text).strip()
                repaired_json = json.loads(repair_text)
                if isinstance(repaired_json, dict):
                    logger.info("[JSON_REPAIR_SUCCESS] Le JSON a été réparé avec succès !")
                    return repaired_json
            except Exception as repair_err:
                logger.error(f"[JSON_REPAIR_FAILED] La tentative de réparation a échoué : {repair_err}")

    return {"raw_fallback": normalized_response}


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
    all_parsed_transactions = parse_trace_file(log_file_path, doc_session_id=doc_session_id, mode="full")

    # Filtrage explicite des heartbeats (0800/0810) : jamais des transactions métier
    filtered_transactions = [tx for tx in all_parsed_transactions if not tx.get("is_heartbeat")]

    # Réorganisation : suspectes en tête
    suspicious_transactions = [tx for tx in filtered_transactions if tx.get("alerts_found")]
    clean_transactions = [tx for tx in filtered_transactions if not tx.get("alerts_found")]
    ordered_transactions = suspicious_transactions + clean_transactions

    limit = max(MAX_TOTAL_TRANSACTIONS, 500) if MAX_TOTAL_TRANSACTIONS < 500 else MAX_TOTAL_TRANSACTIONS
    transactions_to_report = ordered_transactions[:limit]

    # Condensation des transactions (sans chronologie brute ligne par ligne)
    hsm_cache = {}
    condensed_transactions = [
        format_condensed_transaction_for_compliance(tx, doc_session_id=doc_session_id, hsm_cache=hsm_cache)
        for tx in transactions_to_report
    ]

    job_id = state.get("doc_session_id") or state.get("file_name")
    if job_id:
        from app.services.job_tracker import update_job
        update_job(job_id, stage="parsing_trace", detail=f"Parsing et condensation terminés ({len(condensed_transactions)} transactions)...", progress_pct=25)

    log_data_json = json.dumps(condensed_transactions, indent=2, ensure_ascii=False)

    return {"log_data_json": log_data_json, "current_agent": "ParserAgent"}


# --- NOEUD 2 : RAG SPECIFICATION RETRIEVER ---
def rag_spec_retriever_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 2 : si un document de spécification PDF a été joint pour cette analyse (doc_session_id),
    interroge la base vectorielle de session ("hps_session_files") pour extraire les règles applicables (k=8).
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
                    func_name = func.get("function", str(func)) if isinstance(func, dict) else str(func)
                    if func_name not in detected_errors:
                        detected_errors.append(func_name)

    query_str = " ".join(detected_errors) if detected_errors else state.get("user_prompt", "")
    search_q = query_str if query_str.strip() else "spécification"

    # Détection de code de commande ou de réponse (ex: EC, ED, CA...) via extract_code_tokens
    from app.rag.retriever import extract_code_tokens, query_command_code
    detected_cmd_codes = extract_code_tokens(search_q)

    session_spec_context = ""
    exact_docs = []
    
    if detected_cmd_codes:
        for cmd_code in detected_cmd_codes:
            exact_docs = query_command_code(cmd_code, session_id=doc_session_id, limit=8)
            if exact_docs:
                doc_snippets = []
                for d in exact_docs:
                    src = d.metadata.get("source", "Document de session")
                    pg = d.metadata.get("page")
                    pg_str = f" (Page {pg})" if pg else ""
                    doc_snippets.append(f"[{src}{pg_str}]\n{d.page_content.strip()}")
                session_spec_context = "\n\n".join(doc_snippets)
                break

    # Fallback vers similarity_search si pas de code détecté ou si la recherche exacte n'a pas retourné de résultat
    if not session_spec_context.strip():
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
        try:
            static_spec = query_specs(search_q, k=4)
            if static_spec.strip():
                rag_extracted_rules = f"=== SPÉCIFICATIONS TECHNIQUES POWERCARD (RÉFÉRENTIEL STATIQUE) ===\n{static_spec.strip()}"
            else:
                rag_extracted_rules = "Aucun extrait de spécification correspondant n'a été trouvé dans le document joint pour cette session."
        except Exception:
            rag_extracted_rules = "Aucun extrait de spécification correspondant n'a été trouvé dans le document joint pour cette session."

    return {"rag_context": rag_extracted_rules, "current_agent": "RagRetrieverAgent"}


# --- NOEUD 3 : COMPLIANCE AUDITOR (SINGLE LLM CALL ON CONDENSED DATA) ---
def compliance_auditor_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 3 : Traitement en UN SEUL APPEL LLM basé sur les transactions condensées.
    L'entrée condensée ne pèse plus que ~250 tokens/tx (vs 22,000 tokens/tx en mode full),
    permettant de traiter l'intégralité de la trace en un unique appel tout en restant
    très confortablement sous le plafond Gemini de 250 000 TPM.
    """
    job_id = state.get("doc_session_id") or state.get("file_name")
    if job_id:
        from app.services.job_tracker import update_job
        update_job(job_id, stage="generating_report", detail="Génération du rapport d'audit de conformité (LLM)...", progress_pct=60)

    user_prompt_str = str(state.get("user_prompt") or "")
    log_data_str = str(state.get("log_data_json") or "")
    rag_context_str = str(state.get("rag_context") or "")

    # CORRECTIF : toutes les accolades JSON littérales dans le template système DOIVENT être
    # doublées {{ }} pour ne pas être interprétées comme des variables LangChain.
    # Seules {user_prompt}, {log_data_json} et {rag_context} sont de vraies variables template.
    auditor_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Audit et Conformité Monétique pour les testeurs d'HPS.\n"
            "Ton rôle est de générer un rapport d'analyse sous forme d'un OBJET JSON STRUCTURÉ UNIQUEMENT "
            "(aucun texte de présentation, aucun bloc markdown prose en dehors du JSON) basé sur la liste des transactions "
            "et les spécifications techniques (RAG Context) fournies, EN SUIVANT STRICTEMENT LA DEMANDE DU TESTEUR "
            "ci-dessous (variable {{user_prompt}}).\n\n"
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
            '      "pan_masked": <string, masquer tous sauf les 4 derniers chiffres ex: "\u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022 1991">,\n'
            '      "stan": <string>,\n'
            '      "rrn": <string>,\n'
            '      "processing_code": <string ou null>,\n'
            '      "response_code": <string>,\n'
            '      "response_code_label": <string, ex: "Approuv\u00e9e" ou "D\u00e9clin\u00e9e">,\n'
            '      "approval_status": <"approved" | "declined">,\n'
            '      "alerts": [<string>, ...],\n'
            '      "failed_functions": [<string>, ...],\n'
            '      "pistes_diagnostiques": <string>,\n'
            '      "chronology": [<string>]\n'
            "    }}\n"
            "  ],\n"
            '  "field_analysis": [\n'
            "    {{\n"
            '      "field_number": <string, ex: "FLD 002">,\n'
            '      "field_name": <string, ex: "PAN">,\n'
            '      "expected_type": <string, ex: "N (num\u00e9rique, max 19)">,\n'
            '      "source": <string, ex: "Spec_PowerCARD.xlsx" ou "Document de session">,\n'
            '      "observed_value": <string, valeur r\u00e9ellement observ\u00e9e dans la trace>,\n'
            '      "non_conformity_type": <string, nature pr\u00e9cise de la non-conformit\u00e9, ex: "attendu num\u00e9rique, contient des lettres/symboles">\n'
            "    }}\n"
            "  ],\n"
            '  "no_field_violations": <boolean, true si field_analysis est vide>\n'
            "}}\n\n"
            "R\u00e8gles strictes :\n"
            "- Analyse TOUTES les transactions fournies dans les donn\u00e9es condens\u00e9es.\n"
            "- Pour chaque transaction avec des alertes ou un \u00e9chec, passe `is_suspicious` \u00e0 true et renseigne les `alerts`.\n"
            "- Copie dans `failed_functions` la liste exacte des fonctions pr\u00e9sentes dans le champ `failed_functions` des donn\u00e9es condens\u00e9es. Si aucune, laisser [].\n"
            "- Copie dans `processing_code` la valeur du champ `processing_code` des identifiers des donn\u00e9es condens\u00e9es. Si absent, mettre null.\n"
            "- Copie dans `pistes_diagnostiques` le champ `pistes_diagnostiques` des donn\u00e9es condens\u00e9es tel quel. Si transaction OK, laisser vide.\n"
            "- La chronologie liste UNIQUEMENT les actions et \u00e9v\u00e9nements r\u00e9els de traitement. "
            "Elle NE DOIT PAS inclure d'\u00e9tape de synth\u00e8se finale des alertes.\n"
            "- Chaque \u00e9l\u00e9ment de chronologie NE DOIT JAMAIS commencer par un num\u00e9ro (\"1.\", \"2.\", etc.).\n"
            "- SECTION field_analysis : NE lister QUE les champs o\u00f9 une NON-CONFORMIT\u00c9 R\u00c9ELLE a \u00e9t\u00e9 d\u00e9tect\u00e9e "
            "(pr\u00e9sente dans le champ `field_violations` des donn\u00e9es condens\u00e9es). "
            "NE PAS g\u00e9n\u00e9rer de description g\u00e9n\u00e9rique ou p\u00e9dagogique pour les champs conformes. "
            "Copier directement les champs `field_number`, `field_name`, `expected_type_label` (comme `expected_type`), "
            "`source_file` (comme `source`), `observed_value`, `non_conformity_type` depuis `field_violations`. "
            "Si `field_violations` est vide ou absent, mettre `field_analysis: []` et `no_field_violations: true`.\n"
            "- R\u00e9ponds STRICTEMENT et UNIQUEMENT avec l'objet JSON valide."
        )),
        ("user", (
            "Prompt de l'utilisateur : {user_prompt}\n\n"
            "Donn\u00e9es Condens\u00e9es des Transactions (JSON) :\n{log_data_json}\n\n"
            "Sp\u00e9cifications Applicables (RAG Context) :\n{rag_context}"
        )),
    ])

    from app.rag.retriever import estimate_tokens
    tok_user = estimate_tokens(user_prompt_str)
    tok_log = estimate_tokens(log_data_str)
    tok_rag = estimate_tokens(rag_context_str)
    tok_total = tok_user + tok_log + tok_rag

    print(
        f"=== [PROMPT TOKEN DIAGNOSTICS] (ComplianceAuditor - Single Call) ===\n"
        f"   ↳ Question/Prompt Utilisateur : ~{tok_user:,} tokens\n"
        f"   ↳ Données de Trace (JSON Condensé) : ~{tok_log:,} tokens\n"
        f"   ↳ Contexte RAG (Spécification): ~{tok_rag:,} tokens\n"
        f"   ↳ TOTAL ESTIMÉ PROMPT        : ~{tok_total:,} tokens (Plafond Gemini Free Tier : 250 000 TPM)\n"
        f"=========================================================================="
    )

    response = invoke_llm_with_retry(llm, auditor_prompt.format_messages(
        user_prompt=user_prompt_str,
        log_data_json=log_data_str,
        rag_context=rag_context_str,
    ))

    try:
        record_usage("ComplianceAuditor", extract_token_usage(response))
    except Exception:
        pass

    content = response.content
    if isinstance(content, list):
        parts = [b.get("text", str(b)) if isinstance(b, dict) else str(b) for b in content]
        norm_resp = "\n".join(parts)
    elif content is None:
        norm_resp = ""
    else:
        norm_resp = str(content)

    final_data = _clean_and_parse_json(norm_resp, llm_instance=llm)

    if job_id:
        from app.services.job_tracker import update_job
        update_job(
            job_id,
            stage="done",
            detail="Rapport d'audit de conformité généré avec succès.",
            progress_pct=100,
            result=final_data
        )

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