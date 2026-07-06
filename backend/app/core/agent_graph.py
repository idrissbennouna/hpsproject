import json
import os
import time
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

# Importation de ton parser local optimisé
from app.services.log_parser import parse_trace_file_for_story

load_dotenv()

# 1. Définition de l'état du graphe (State)
class AgentState(dict):
    user_prompt: str
    current_agent: str
    rag_context: str
    log_data_json: str
    final_response: str
    file_name: str

# Configuration du modèle LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# --- NOEUD 1 : PARSER & CHRONOLOGY AGENT (OPTIMISÉ ANTI-TOKEN OVERFLOW) ---
def parser_story_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 1 : Utilise le parser Python local pour extraire efficacement 
    les jalons de transactions sans surcharger l'API Gemini.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    filename = state.get("file_name") or "BASE1_LCH_2.TRC019.TXT"
    log_file_path = os.path.join(base_dir, "app", "storage", filename)
    
    # Si le chemin relatif diffère selon l'environnement de lancement
    if not os.path.exists(log_file_path):
        log_file_path = os.path.join("app", "storage", filename)

    if not os.path.exists(log_file_path):
        error_json = json.dumps({"error": f"Impossible de trouver le fichier '{filename}'"})
        return {"log_data_json": error_json, "current_agent": "ParserAgent"}

    # --- LE SECRET EST ICI : ON PARSE EN LOCAL ---
    # On récupère la liste des transactions pré-filtrées (identifiants, chronologie, alertes locales)
    parsed_transactions = parse_trace_file_for_story(log_file_path)

    # Pour ta démonstration, afin de respecter les limites strictes du Free Tier tout en montrant 
    # la pertinence sur l'ensemble du fichier, on convertit les structures condensées en JSON.
    # On peut limiter à un échantillon représentatif de transactions (ex: les 15 premières) si l'API sature encore,
    # ou passer le dictionnaire global condensé qui est 100 fois plus léger que le fichier brut de 31k lignes.
    condensed_json = json.dumps(parsed_transactions[:15], indent=2, ensure_ascii=False)
    
    return {
        "log_data_json": condensed_json,
        "current_agent": "ParserAgent"
    }

# --- NOEUD 2 : RAG SPECIFICATION RETRIEVER ---
def rag_spec_retriever_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 2 : Analyse la LogStory JSON générée et simule/interroge la base 
    vectorielle pour récupérer les règles des spécifications applicables.
    """
    # Temporisation optionnelle pour éviter de spammer l'API entre deux nœuds si nécessaire
    time.sleep(1)
    
    rag_extracted_rules = (
        "Spécification Technique HPS - Module libsaf (saf_manage.pc) :\n"
        "- La fonction CardInSaf() interroge le package PL/SQL PCRD_SAF_MANAGE.CARD_IN_SAF.\n"
        "- Elle valide si une carte possède des transactions Store-and-Forward éligibles stockées dans la table p7_store_and_forward.\n"
        "- Code retour NOK (-1) : Indique soit qu'aucune donnée correspondante n'a été trouvée pour ce numéro de carte (NO_DATA_FOUND), "
        "soit une anomalie de routage On-Us où la transaction existe mais l'origine n'est pas qualifiée (Local, National ou Foreign)."
    )
    
    return {
        "rag_context": rag_extracted_rules,
        "current_agent": "RagRetrieverAgent"
    }

# --- NOEUD 3 : COMPLIANCE AUDITOR ---
def compliance_auditor_node(state: AgentState) -> Dict[str, Any]:
    """
    Étape 3 : Combine les résumés de transactions extraits et le contexte RAG 
    pour dresser le bilan d'audit final demandé par le testeur HPS.
    """
    auditor_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Audit et Conformité Monétique pour les testeurs d'HPS.\n"
            "Ton rôle est de générer un rapport d'analyse final extrêmement rigoureux basé sur la liste des transactions "
            "et les spécifications techniques (RAG Context) fournies.\n\n"
            "Tu dois impérativement formater ta réponse pour le testeur :\n"
            "1. Restituer proprement la Story chronologique (les jalons) de chaque autorisation listée dans le JSON.\n"
            "2. Mettre en évidence les ALERTES (comme les statuts != OK ou NOK -1) rencontrées.\n"
            "3. JUSTIFIER chaque alerte détectée en faisant le lien avec le RAG Context (ex: expliquer ce que signifie le code -1 de CardInSaf).\n"
            "4. Proposer des pistes de diagnostic claires (tables SQL à vérifier, problèmes de routage)."
        )),
        ("user", (
            "Prompt de l'utilisateur : {user_prompt}\n\n"
            "Données des transactions (JSON condensé) :\n{log_data_json}\n\n"
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

# 2. Construction et compilation du Workflow LangGraph
workflow = StateGraph(AgentState)

# Ajout des nœuds à l'architecture
workflow.add_node("ParserStoryBuilder", parser_story_node)
workflow.add_node("RagRetriever", rag_spec_retriever_node)
workflow.add_node("ComplianceAuditor", compliance_auditor_node)

# Définition de la séquence linéaire d'exécution
workflow.set_entry_point("ParserStoryBuilder")
workflow.add_edge("ParserStoryBuilder", "RagRetriever")
workflow.add_edge("RagRetriever", "ComplianceAuditor")
workflow.add_edge("ComplianceAuditor", END)

# Compilation finale exposée pour main.py
compliance_agent_app = workflow.compile()