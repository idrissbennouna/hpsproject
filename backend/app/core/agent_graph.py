import os
from pathlib import Path
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv() 

from typing import Annotated, Literal, TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import PGVector

# Imports de tes services de parsing
from app.services.log_parser import parse_trace_file_for_story

# 1. Définition de l'État Global du Graphe enrichi
class MultiAgentState(TypedDict):
    user_prompt: str           # Le prompt initial entré par l'utilisateur
    current_agent: str         # L'agent actif
    rag_context: str           # Données extraites de la documentation
    log_data_json: str         # Traces de logs parsées
    final_response: str        # La réponse générée à afficher sur l'interface
    requires_doc: bool         # Indicateur de routage conditionnel 🧠

# Initialisation du LLM Gemini
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

# =====================================================================
# 2. NODES (SOUS-AGENTS)
# =====================================================================

def log_agent_node(state: MultiAgentState):
    """
    Analyse le fichier de traces et lève un flag si une spécification complémentaire
    doit être recherchée par le DocAgent.
    """
    current_dir = Path(__file__).resolve().parent
    storage_dir = current_dir.parent / "storage"
    log_file_path = storage_dir / "BASE1_LCH_2.TRC019.TXT" 
    
    if not log_file_path.exists():
        error_msg = f"Erreur : Le fichier de traces est introuvable au chemin : {log_file_path}"
        return {"final_response": error_msg, "requires_doc": False}
    
    parsed_result = parse_trace_file_for_story(str(log_file_path))
    
    if isinstance(parsed_result.get('chronology'), str):
        lines = parsed_result['chronology'].split("\n")
        seen = set()
        clean_lines = []
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped not in seen:
                clean_lines.append(line)
                seen.add(line_stripped)
        chronology_clean = "\n".join(clean_lines)
    else:
        chronology_clean = str(parsed_result.get('chronology', ''))
        
    if "error" in parsed_result:
        return {"final_response": parsed_result["error"], "requires_doc": False}
    
    prompt = f"""
    Tu es un Agent expert en analyse de traces monétiques chez HPS.
    Génère un rapport technique clair contenant le déroulement chronologique (LogStory) et isole les fonctions en échec.
    Utilise uniquement des listes à puces.

    Données brutes :
    - Identifiants : {parsed_result['identifiers']}
    - Chronologie : {chronology_clean}
    - Anomalies : {parsed_result['alerts_found']}

    CONSIGNE : "{state['user_prompt']}"
    """
    
    response = llm.invoke(prompt)
    
    # Heuristique : Si une anomalie ou une fonction spécifique comme CardInSaf est levée,
    # on demande explicitement l'intervention du DocAgent pour le RAG PostgreSQL
    requires_doc = "échec" in response.content.lower() or "nok" in response.content.lower() or "alert" in response.content.lower()

    return {
        "log_data_json": chronology_clean,
        "final_response": response.content,
        "requires_doc": requires_doc
    }


def doc_agent_node(state: MultiAgentState):
    """
    Interroge pgvector pour les spécifications officielles.
    En cas d'erreur API ou d'échec d'embedding, bascule automatiquement 
    sur une recherche textuelle directe (Fallback) dans le fichier Excel local.
    """
    import openpyxl
    
    current_dir = Path(__file__).resolve().parent
    excel_path = current_dir.parent / "storage" / "Spec_PowerCARD.xlsx"
    
    CONNECTION_STRING = "postgresql+psycopg2://postgres:password@localhost:5432/hps_docs_db"
    COLLECTION_NAME = "hps_specifications"

    contexte_docs_extraits = ""
    sources_str = "Spec_PowerCARD.xlsx"
    success_rag = False

    # 1. Tentative initiale via pgvector RAG
    try:
        embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        vector_store = PGVector(
            connection_string=CONNECTION_STRING,
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME,
        )
        
        docs_trouves = vector_store.similarity_search(state.get("final_response", ""), k=1)
        if docs_trouves:
            contexte_docs_extraits = docs_trouves[0].page_content
            sources_str = docs_trouves[0].metadata.get("source", "Spec_PowerCARD.xlsx")
            success_rag = True
            
    except Exception as e:
        print(f"⚠️ Alerte API Vectorielle (Bascule sur le Fallback Excel Local) : {e}")

    # 2. Système de Secours : Recherche directe par mot-clé dans l'Excel
    if not success_rag and excel_path.exists():
        try:
            wb = openpyxl.load_workbook(excel_path, data_only=True)
            ws = wb["Lib"]
            rapport_precedent = state.get("final_response", "").lower()
            
            # Parcourir l'Excel pour chercher si le nom d'une fonction apparaît dans le rapport
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[0]:
                    continue
                func_name = str(row[0]).strip()
                
                # Si la fonction (ex: CardInSaf) est mentionnée dans le rapport d'échec
                if func_name.lower() in rapport_precedent:
                    description = str(row[3]).strip() if row[3] else "Aucune description"
                    exception = str(row[4]).strip() if row[4] else "Aucune condition"
                    source_val = str(row[1]).strip() if row[1] else "Spec_PowerCARD.xlsx"
                    
                    contexte_docs_extraits = f"Fonction {func_name} : {description}\nConditions & Exceptions : {exception}"
                    sources_str = source_val
                    break  # Correspondance trouvée, on s'arrête
                    
        except Exception as ex_excel:
            print(f"❌ Erreur lors de la lecture du fichier de secours Excel : {ex_excel}")

    # Si rien n'a été trouvé ni par RAG ni par l'Excel
    if not contexte_docs_extraits:
        contexte_docs_extraits = "Aucune spécification technique correspondante n'a pu être extraite."
        sources_str = "N/A"

    # 3. Génération du rapport enrichi par le LLM
    prompt_fusion = f"""
    Tu es l'Agent Documentaire chez HPS. Prends le rapport de logs et enrichis-le avec la spécification technique officielle extraite ci-dessous.
    
    Rapport de logs :
    {state['final_response']}

    Spécification officielle HPS :
    {contexte_docs_extraits}

    Formate le livrable final STRICTEMENT en Markdown (uniquement sous forme de puces claires et indentées). 
    Ajoute à la toute fin la mention de la source officielle exacte sous la forme : * **Source Officielle :** [{sources_str}]
    """
    
    response = llm.invoke(prompt_fusion)
    return {"final_response": response.content}
# =====================================================================
# 3. ROUTAGE CONDITIONNEL (CONDITIONAL ROUTING)
# =====================================================================

def router_node(state: MultiAgentState):
    """Aiguille le flux selon le besoin en documentation."""
    if state.get("requires_doc"):
        return "DocAgent"
    return END

# Configuration du graphe
workflow = StateGraph(MultiAgentState)

workflow.add_node("LogAgent", log_agent_node)
workflow.add_node("DocAgent", doc_agent_node)

workflow.set_entry_point("LogAgent")

# Ajout du routage conditionnel après le LogAgent
workflow.add_conditional_edges(
    "LogAgent",
    router_node,
    {
        "DocAgent": "DocAgent",
        END: END
    }
)

workflow.add_edge("DocAgent", END)
compliance_agent_app = workflow.compile()

# =====================================================================
# 4. TEST LOCAL
# =====================================================================
if __name__ == "__main__":
    print("\n🚀 Lancement du test avec Routage Conditionnel...\n")
    prompt_test = "Génère-moi la story complète de mon fichier de traces et vérifie s'il y a des alertes de non-conformité."
    
    result = compliance_agent_app.invoke({
        "user_prompt": prompt_test,
        "current_agent": "",
        "rag_context": "",
        "log_data_json": "",
        "final_response": "",
        "requires_doc": False
    })
    print(result["final_response"])