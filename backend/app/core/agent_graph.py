import os
from pathlib import Path
from dotenv import load_dotenv

# CRITIQUE : Charger les variables d'environnement AVANT d'initialiser le modèle
load_dotenv() 

from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI

# Imports de tes services de parsing
from app.services.log_parser import parse_trace_file_for_story

# 1. Définition de l'État Global du Graphe
class MultiAgentState(TypedDict):
    user_prompt: str           # Le prompt initial entré par l'utilisateur
    current_agent: str         # L'agent actif désigné par le superviseur
    rag_context: str           # Données extraites de la documentation (Excel/PDF)
    log_data_json: str         # Traces de logs parsées
    final_response: str        # La réponse générée à afficher sur l'interface

# Initialisation du LLM Gemini
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

# =====================================================================
# 2. STRUCTURE DU SUPERVISEUR (AIGUILLEUR)
# =====================================================================
class RouteResponse(BaseModel):
    next_action: Literal["DocAgent", "LogAgent", "FINISH"] = Field(
        description="Choisis l'agent approprié selon la demande ou FINISH si la réponse est prête."
    )
    justification: str = Field(description="Explication rapide du choix d'aiguillage.")

def supervisor_node(state: MultiAgentState):
    """Il analyse le besoin de l'utilisateur et choisit le sous-agent idéal."""
    # Si un agent a déjà fait le travail et a positionné la suite sur FINISH
    if state.get("current_agent") == "FINISH":
        return {"current_agent": "FINISH"}

    prompt = f"""
    Tu es le Superviseur Expert de la plateforme de Validation Monétique HPS.
    Ton rôle est d'analyser la demande de l'utilisateur et de passer le relais à l'agent spécialisé.

    Voici les agents disponibles :
    - 'DocAgent' : Utilisé si la question porte sur les documentations ou spécifications PowerCARD / Visa.
    - 'LogAgent' : En cas de demande d'analyse de traces, de génération de LogStory ou de vérification de fichier .TXT.
    - 'FINISH' : Si le travail est terminé et qu'une réponse finale claire est rédigée.

    Demande de l'utilisateur : {state['user_prompt']}
    """
    structured_llm = llm.with_structured_output(RouteResponse)
    decision = structured_llm.invoke(prompt)
    return {"current_agent": decision.next_action}

# =====================================================================
# 3. STRUCTURE DES SOUS-AGENTS
# =====================================================================
def doc_agent_node(state: MultiAgentState):
    """Agent temporaire spécialisé dans les spécifications et le RAG (bientôt PostgreSQL)."""
    prompt = f"Réponds à la demande de documentation : {state['user_prompt']}"
    response = llm.invoke(prompt)
    return {"final_response": response.content, "current_agent": "FINISH"}


def log_agent_node(state: MultiAgentState):
    """
    Nœud LangGraph chargé de traiter la demande sur les traces et les logs.
    """
    # Résolution dynamique et absolue du chemin d'accès au fichier de stockage
    current_dir = Path(__file__).resolve().parent
    storage_dir = current_dir.parent / "storage"
    log_file_path = storage_dir / "BASE1_LCH_2.TRC019.TXT" 
    
    # Sécurité : Vérification de l'existence du fichier sur la machine
    if not log_file_path.exists():
        error_msg = f"Erreur : Le fichier de traces est introuvable au chemin précis : {log_file_path}"
        return {"final_response": error_msg, "current_agent": "FINISH"}
    
    print(f"🔍 Fichier détecté avec succès ! Parsing en cours...")
    
    # Envoi du chemin absolu sous forme de chaîne de caractères au parseur
    parsed_result = parse_trace_file_for_story(str(log_file_path))
    
    if "error" in parsed_result:
        return {"final_response": parsed_result["error"], "current_agent": "FINISH"}
    
    # Construction du prompt métier enrichi
    prompt = f"""
    Tu es l'Agent d'Analyse des Logs de la plateforme ComplianceVerifier chez HPS.
    Ton rôle est de prendre les éléments extraits d'un fichier de traces monétiques et de rédiger une synthèse claire pour les équipes de test.

    Données techniques extraites :
    - Identifiants de transaction détectés : {parsed_result['identifiers']}
    - Chronologie des événements constatés : 
    {parsed_result['chronology']}
    - Anomalies / Échecs bloquants trouvés : {parsed_result['alerts_found']}

    Consignes de rédaction :
    1. Rédige une "LogStory" fluide en français qui explique le parcours de l'autorisation.
    2. S'il y a des alertes de non-conformité (ex: GetOriginalAuthData à -1, ou fonction != OK), mets-les en évidence en expliquant qu'elles provoquent une bascule vers 'AuthLocal'.
    3. Ajoute une section 'Pistes de diagnostic' : conseille au testeur d'aller inspecter les balises correspondantes (comme le tag P29 pour les défauts de sécurité ou DBConDoRefresh pour les soucis de session BD).

    Demande de l'utilisateur : {state['user_prompt']}
    """
    
    # Demande d'analyse à l'API Gemini
    response = llm.invoke(prompt)
    
    # Mise à jour de l'état
    return {
        "log_data_json": parsed_result['chronology'],
        "final_response": response.content,
        "current_agent": "FINISH"
    }

# =====================================================================
# 4. ROUTAGE ET CONFIGURATION DU GRAPHE
# =====================================================================
def router_edge(state: MultiAgentState):
    """Détermine dynamiquement vers quel nœud se diriger."""
    if state["current_agent"] == "DocAgent":
        return "DocAgent"
    elif state["current_agent"] == "LogAgent":
        return "LogAgent"
    else:
        return END

# Construction et assemblage du flux LangGraph
workflow = StateGraph(MultiAgentState)

workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("DocAgent", doc_agent_node)
workflow.add_node("LogAgent", log_agent_node)

workflow.add_edge(START, "Supervisor")

workflow.add_conditional_edges(
    "Supervisor",
    router_edge,
    {
        "DocAgent": "DocAgent",
        "LogAgent": "LogAgent",
        END: END
    }
)

workflow.add_edge("DocAgent", "Supervisor")
workflow.add_edge("LogAgent", "Supervisor")

# Compilation finale de l'application
compliance_agent_app = workflow.compile()

# =====================================================================
# 5. SCRIPT DE TEST LOCAL (DANS LE TERMINAL VS CODE)
# =====================================================================
if __name__ == "__main__":
    print("\n🚀 Lancement du test de l'Agent de Logs avec Gemini...\n")
    
    # Simulation d'un prompt utilisateur orienté Logs
    prompt_test = "Génère-moi la story complète de mon fichier de traces et vérifie s'il y a des alertes de non-conformité."
    
    # Déclenchement du graphe compilé
    result = compliance_agent_app.invoke({
        "user_prompt": prompt_test,
        "current_agent": "",
        "rag_context": "",
        "log_data_json": "",
        "final_response": ""
    })
    
    print("\n================== RAPPORT DE LOGSTORY GÉNÉRÉ ==================")
    print(result["final_response"])
    print("================================================================")