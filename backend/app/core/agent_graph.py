import json
import os
import time
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from typing_extensions import TypedDict  # Importation correcte pour LangGraph

# Importation de ton parser local optimisé et robuste
from app.services.log_parser import parse_trace_file_for_story

load_dotenv()

# --- 1. DÉFINITION DE L'ÉTAT DU GRAPHE (CORRIGÉ EN TYPEDDICT) ---
class AgentState(TypedDict):
    user_prompt: str
    current_agent: str
    rag_context: str
    log_data_json: str
    final_response: str
    file_name: str

# Configuration du modèle LLM Gemini
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# --- NOEUD 1 : PARSER & CHRONOLOGY AGENT (FILTRÉ & OPTIMISÉ) ---
def parser_story_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 1 : Utilise le parser local pour extraire les jalons et filtre
    les données pour ne garder que les anomalies (évite le gaspillage de tokens).
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    filename = state.get("file_name") or "BASE1_LCH_2.TRC019.TXT"
    log_file_path = os.path.join(base_dir, "app", "storage", filename)
    
    if not os.path.exists(log_file_path):
        log_file_path = os.path.join("app", "storage", filename)

    if not os.path.exists(log_file_path):
        error_json = json.dumps({"error": f"Impossible de trouver le fichier '{filename}'"})
        return {"log_data_json": error_json, "current_agent": "ParserAgent"}

    # Appel de ton parser Python local robuste (sans heartbeats)
    all_parsed_transactions = parse_trace_file_for_story(log_file_path)

    # STRATÉGIE INGENIEUR : On ne garde que les transactions suspectes (avec alertes)
    # pour éviter l'asphyxie des tokens de l'API
    suspicious_transactions = [
        tx for tx in all_parsed_transactions if tx.get("alerts_found")
    ]

    # Si aucune anomalie n'est détectée, on prend les 5 premières par défaut pour la forme
    if not suspicious_transactions:
        suspicious_transactions = all_parsed_transactions[:5]
    else:
        # On limite aux 10 premières anomalies pour sécuriser la démo
        suspicious_transactions = suspicious_transactions[:10]

    condensed_json = json.dumps(suspicious_transactions, indent=2, ensure_ascii=False)
    
    return {
        "log_data_json": condensed_json,
        "current_agent": "ParserAgent"
    }

# --- NOEUD 2 : RAG SPECIFICATION RETRIEVER (DYNAMIQUE) ---
def rag_spec_retriever_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 2 : Extrait dynamiquement les erreurs détectées par le parser 
    pour préparer la future connexion avec la base pgvector (YZ).
    """
    time.sleep(1) # Temporisation de sécurité API
    
    try:
        log_data = json.loads(state.get("log_data_json", "[]"))
    except Exception:
        log_data = []

    # Extraction automatique des mots-clés d'erreurs présents dans la LogStory
    detected_errors = []
    for tx in log_data:
        for alert in tx.get("alerts_found", []):
            # On cherche des noms de fonctions monétiques clés comme CardInSaf ou GetOriginalAuthData
            for func in ["CardInSaf", "GetOriginalAuthData", "CheckReqTlvFields", "FrdCheckControl", "CheckLimits"]:
                if func in alert and func not in detected_errors:
                    detected_errors.append(func)

    # --- ZONE DE JONCTION AVEC LE RAG DE YZ ---
    # TODO: Remplacer ce bloc de simulation par la vraie requête vectorielle de YZ :
    # context = db_vectorielle.similarity_search(query=" ".join(detected_errors), k=2)
    
    if "CardInSaf" in detected_errors or not detected_errors:
        # Simulation d'un retour propre en attendant la liaison pgvector complète
        rag_extracted_rules = (
            "Spécification Technique HPS - Module libsaf (saf_manage.pc) :\n"
            "- La fonction CardInSaf() appelle le package PL/SQL PCRD_SAF_MANAGE.CARD_IN_SAF.\n"
            "- Elle valide si une carte possède des transactions Store-and-Forward éligibles.\n"
            "- Code retour NOK (-1) : Indique soit qu'aucune donnée correspondante n'a été trouvée (NO_DATA_FOUND), "
            "soit une anomalie de routage On-Us où l'origine n'est pas qualifiée."
        )
    else:
        rag_extracted_rules = f"Recherche de spécifications requise pour les modules : {', '.join(detected_errors)}"

    return {
        "rag_context": rag_extracted_rules,
        "current_agent": "RagRetrieverAgent"
    }

# --- NOEUD 3 : COMPLIANCE AUDITOR ---
def compliance_auditor_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 3 : Combine la LogStory filtrée et le contexte extrait du RAG 
    pour générer le rapport d'audit final structuré.
    """
    auditor_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Audit et Conformité Monétique pour les testeurs d'HPS.\n"
            "Ton rôle est de générer un rapport d'analyse final extrêmement rigoureux basé sur la liste des transactions "
            "et les spécifications techniques (RAG Context) fournies.\n\n"
            "Tu dois impérativement formater ta réponse de manière claire pour le testeur HPS :\n"
            "1. Restituer proprement la Story chronologique (les jalons) de chaque autorisation listée dans le JSON.\n"
            "2. Mettre en évidence les ALERTES (comme les statuts != OK ou NOK -1) rencontrées.\n"
            "3. JUSTIFIER chaque alerte détectée en faisant le lien direct avec le RAG Context fourni.\n"
            "4. Proposer des pistes de diagnostic claires (tables SQL ou configurations de routage à vérifier)."
        )),
        ("user", (
            "Prompt de l'utilisateur : {user_prompt}\n\n"
            "Données des transactions (JSON filtré des anomalies) :\n{log_data_json}\n\n"
            "Spécifications Applicables (RAG Context) :\n{rag_context}"
        ))
    ])
    
    response = llm.invoke(auditor_prompt.format_messages(
        user_prompt=state.get("user_prompt"),
        log_data_json=state.get("log_data_json"),
        rag_context=state.get("rag_context")
    ))
    
    return {
        "final_response": response.content,
        "current_agent": "ComplianceAuditorAgent"
    }

# 2. Construction et compilation du Workflow LangGraph (Structure Linéaire Propre)
workflow = StateGraph(AgentState)

# Ajout des nœuds à l'architecture
workflow.add_node("ParserStoryBuilder", parser_story_node)
workflow.add_node("RagRetriever", rag_spec_retriever_node)
workflow.add_node("ComplianceAuditor", compliance_auditor_node)

# Définition de la séquence d'exécution
workflow.set_entry_point("ParserStoryBuilder")
workflow.add_edge("ParserStoryBuilder", "RagRetriever")
workflow.add_edge("RagRetriever", "ComplianceAuditor")
workflow.add_edge("ComplianceAuditor", END)

# Compilation finale exposée pour main.py
compliance_agent_app = workflow.compile()