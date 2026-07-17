# backend/app/core/validation_agent_graph.py
import os
from pathlib import Path
from typing import Dict, Any
from typing_extensions import TypedDict
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.rag.retriever import query_specs
from app.services.session_storage import get_session_files
from app.services.llm_util import invoke_llm_with_retry
from app.services.token_tracker import extract_token_usage, record_usage


# Résolution et chargement du fichier .env
from pydantic import SecretStr

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

# Affichage des valeurs résolues au démarrage
_masked_key = GOOGLE_API_KEY[:6] + "..." if GOOGLE_API_KEY else "None"
print(f"[STARTUP validation_agent_graph.py] GEMINI_MODEL_NAME={GEMINI_MODEL_NAME}, GOOGLE_API_KEY={_masked_key} loaded from {_ENV_PATH}")

if not GOOGLE_API_KEY:
    raise RuntimeError(
        f"Clé API Gemini introuvable. Vérifie le fichier '{_ENV_PATH}'."
    )

# 1. Définition de l'état
class ValidationState(TypedDict):
    user_question: str
    chat_history: list[dict]  # [{"role": "user"|"assistant", "content": str}]
    rag_context: str
    final_response: str
    session_id: str
    sources: list[dict]

# Initialisation du LLM Gemini
llm = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL_NAME,
    temperature=0.2, # Légère créativité autorisée pour la conversation, mais cadrée par le système
    google_api_key=SecretStr(GOOGLE_API_KEY),
)

# Nœud 1 : Retriever
def retriever_node(state: ValidationState) -> Dict[str, Any]:
    """
    Interroge le RAG partagé avec la question de l'utilisateur pour extraire
    les extraits de spécifications pertinents, et y accole les documents de session éphémères.
    """
    question = state.get("user_question", "")
    session_id = state.get("session_id", "")
    
    sources = []
    
    # 1. Requête du RAG persistant classique (k=2 pour économiser les tokens)
    official_specs = query_specs(question, k=2)
    
    context_blocks = []
    if official_specs.strip():
        context_blocks.append(f"=== SPÉCIFICATIONS OFFICIELLES (RAG) ===\n{official_specs}")
        # Une seule entrée sources de type "spec" quand le RAG persistant est non vide
        sources.append({"type": "spec", "label": "Spec PowerCARD"})
    else:
        context_blocks.append("=== SPÉCIFICATIONS OFFICIELLES (RAG) ===\nAucune spécification officielle correspondante trouvée.")

    # 2. Contexte éphémère de la session s'il y en a un
    if session_id:
        session_files = get_session_files(session_id)
        if session_files:
            file_blocks = []
            for file_info in session_files:
                filename = file_info["name"]
                content = file_info["content"]
                stats = file_info.get("stats", {})
                
                # Injection explicite des métadonnées calculées
                truncation_note = (
                    " (le texte ci-dessous est tronqué pour limiter la consommation de "
                    "tokens, mais ces statistiques portent sur le fichier ORIGINAL complet)"
                    if stats.get("truncated_for_llm") else ""
                )
                meta_header = (
                    f"[Métadonnées calculées automatiquement — "
                    f"valeurs exactes, ne pas recompter{truncation_note}] "
                    f"Lignes : {stats.get('line_count', '?')} | "
                    f"Lignes non vides : {stats.get('non_empty_line_count', '?')} | "
                    f"Caractères : {stats.get('char_count', '?')}"
                )
                
                file_blocks.append(
                    f"--- Fichier uploadé : {filename} ---\n"
                    f"{meta_header}\n"
                    f"{content}"
                )
                # Une entrée sources de type "session_file" par fichier de session
                sources.append({"type": "session_file", "label": filename})
                
            context_blocks.append(f"=== DOCUMENTS ÉPHÉMÈRES (SESSION DE TEST) ===\n" + "\n\n".join(file_blocks))

    rag_context = "\n\n".join(context_blocks)
    return {"rag_context": rag_context, "sources": sources}

# Nœud 2 : Answerer
def answerer_node(state: ValidationState) -> Dict[str, Any]:
    """
    Génère la réponse de l'expert en se basant sur le contexte RAG et l'historique de discussion.
    """
    question = state.get("user_question", "")
    rag_context = state.get("rag_context", "")
    chat_history_raw = state.get("chat_history", [])

    # Limiter l'historique de discussion aux 6 derniers messages (3 tours de discussion)
    chat_history_raw = chat_history_raw[-6:]

    # Conversion de l'historique brut en messages LangChain
    formatted_messages = []
    for msg in chat_history_raw:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            formatted_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            formatted_messages.append(AIMessage(content=content))

    # Définition du prompt système strict
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Spécifications PowerCARD pour les testeurs HPS.\n"
            "Ton but est d'aider les testeurs à valider le comportement de la plateforme en répondant à leurs questions.\n\n"
            "Règles strictes :\n"
            "1. Réponds STRICTEMENT à partir du contexte RAG (RAG Context) fourni ci-dessous. N'invente pas d'informations.\n"
            "2. Si l'information demandée n'est pas présente dans le RAG Context, dis explicitement que tu ne trouves pas l'information dans les spécifications actuelles au lieu d'extrapoler ou de mentir.\n"
            "3. Prends en compte l'historique de la conversation pour comprendre le contexte des questions de suivi.\n"
            "4. Formate tes réponses dans un Markdown clair, soigné, structuré et professionnel (tableaux, listes à puces si approprié).\n"
            "5. Réponds en français.\n"
            "6. Si une métadonnée est fournie avec une mention du type '[Métadonnées calculées automatiquement...]', tu DOIS utiliser cette valeur telle quelle. Ne recalcule/ne recompte jamais toi-même à partir du texte brut : tu n'es pas fiable pour compter du texte (lignes, caractères, etc.). Cite uniquement et mot pour mot la valeur donnée dans ces métadonnées.\n\n"
            "RAG Context :\n"
            "{rag_context}"
        )),
        # Insertion de l'historique de chat
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{user_question}")
    ])

    # Invocation du modèle avec mécanisme de retry automatique
    chain = prompt_template | llm
    response = invoke_llm_with_retry(chain, {
        "rag_context": rag_context,
        "chat_history": formatted_messages,
        "user_question": question
    })

    # Tracking de tokens best-effort
    try:
        record_usage("ValidationAgent", extract_token_usage(response))
    except Exception as token_err:
        print(f"⚠️ Échec best-effort du tracking de tokens : {token_err}")

    # Normalisation sécurisée de response.content
    content = response.content
    if isinstance(content, list):
        print(f"⚠️ [WARNING] response.content (validation) is a list instead of string! Normalizing list: {content}")
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

    return {"final_response": normalized_response}

# 2. Construction du workflow LangGraph
workflow = StateGraph(ValidationState)

workflow.add_node("Retriever", retriever_node)
workflow.add_node("Answerer", answerer_node)

workflow.set_entry_point("Retriever")
workflow.add_edge("Retriever", "Answerer")
workflow.add_edge("Answerer", END)

validation_agent_app = workflow.compile()
