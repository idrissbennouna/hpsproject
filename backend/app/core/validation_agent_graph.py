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

raw_model = os.getenv("GEMINI_MODEL_NAME", "gemini-3.5-flash")
GEMINI_MODEL_NAME = raw_model.strip() if raw_model else "gemini-3.5-flash"
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
    chat_history = state.get("chat_history", [])

    # Construit une requête de recherche enrichie du contexte conversationnel récent,
    # pour que les questions de suivi ("et si ça échoue ?") retrouvent le bon document
    # même sans répéter le nom de la fonction/du champ concerné.
    recent_turns = chat_history[-2:] if chat_history else []
    context_snippet = " ".join(
        turn.get("content", "") for turn in recent_turns if turn.get("content")
    )
    search_query = f"{context_snippet} {question}".strip() if context_snippet else question
    
    sources = []
    
    # 1. Requête du RAG persistant classique (k=2 pour économiser les tokens)
    official_specs = query_specs(search_query, k=2)
    
    context_blocks = []
    if official_specs.strip():
        context_blocks.append(f"=== SPÉCIFICATIONS OFFICIELLES (RAG) ===\n{official_specs}")
        # Une seule entrée sources de type "spec" quand le RAG persistant est non vide
        sources.append({"type": "spec", "label": "Spec PowerCARD"})
    else:
        context_blocks.append("=== SPÉCIFICATIONS OFFICIELLES (RAG) ===\nAucune spécification officielle correspondante trouvée.")

    # 2. Contexte éphémère de la session s'il y en a un
    if session_id:
        from app.rag.retriever import count_session_chunks, search_session_chunks_keyword
        diag = count_session_chunks(session_id)
        print(
            f"[RETRIEVER_DIAG] Filter session_id: '{session_id}' | "
            f"Chunks in DB for this session: {diag.get('chunk_count', 0)} | "
            f"All active session_ids in DB: {diag.get('all_active_session_ids', [])}"
        )

        session_files = get_session_files(session_id)
        if session_files:
            file_blocks = []
            for file_info in session_files:
                filename = file_info["name"]
                stats = file_info.get("stats", {})
                
                # Si c'est un fichier indexé via RAG éphémère (comme un PDF)
                if file_info.get("is_rag") or filename.lower().endswith('.pdf'):
                    try:
                        from app.rag.retriever import get_session_vectorstore
                        session_db = get_session_vectorstore()

                        # Détection d'intention pour requêtes globales/résumés
                        broad_keywords = [
                            "résume", "resume", "summarize", "summary", "overview", 
                            "combien de", "toutes les", "tous les", "sommaire", "global",
                            "structure", "chapitres", "sections", "présente", "presente"
                        ]
                        q_lower = question.lower()
                        is_broad_query = any(kw in q_lower for kw in broad_keywords)
                        session_k = 16 if is_broad_query else 4

                        # 4. Hybrid Search: Vérification de motif spécifique (ex: Field 37, Champ 39, FLD 011, etc.)
                        import re
                        field_pattern = re.compile(r'(?:field|champ|fld)\s*0*(\d+)', re.IGNORECASE)
                        field_matches = field_pattern.findall(question)

                        keyword_docs = []
                        if field_matches:
                            for field_num in field_matches:
                                # Chercher les motifs textuels probables : "Field 37", "Field37", "Champ 37", "FLD 037", "37"
                                search_terms = [
                                    f"Field {field_num}",
                                    f"Field{field_num}",
                                    f"Champ {field_num}",
                                    f"Champ{field_num}",
                                    f"FLD {field_num.zfill(3)}",
                                    f"FLD{field_num.zfill(3)}",
                                    f"FLD {field_num}"
                                ]
                                for term in search_terms:
                                    found = search_session_chunks_keyword(session_id, term, limit=3)
                                    if found:
                                        keyword_docs.extend(found)

                        semantic_docs = session_db.similarity_search(
                            search_query, 
                            k=session_k, 
                            filter={"session_id": session_id}
                        )

                        # Fusion dédoublonnée (Keyword matches prioritaires)
                        seen_contents = set()
                        relevant_docs = []
                        for doc in keyword_docs + semantic_docs:
                            content_snippet = doc.page_content.strip()
                            if content_snippet not in seen_contents:
                                seen_contents.add(content_snippet)
                                relevant_docs.append(doc)

                        if relevant_docs:
                            chunk_blocks = []
                            for idx, doc in enumerate(relevant_docs, 1):
                                page_num = doc.metadata.get("page", "?")
                                chunk_blocks.append(
                                    f"[Extrait RAG {idx} (Page {page_num})] :\n{doc.page_content.strip()}"
                                )
                            content = "\n\n".join(chunk_blocks)
                        else:
                            content = "Aucun passage pertinent trouvé dans ce document pour la question posée."
                    except Exception as e:
                        content = f"Erreur lors de la recherche vectorielle RAG de session : {e}"
                else:
                    content = file_info["content"]

                # Injection explicite des métadonnées calculées
                truncation_note = (
                    " (le texte ci-dessous contient les extraits les plus pertinents basés sur votre recherche)"
                    if file_info.get("is_rag") or filename.lower().endswith('.pdf')
                    else (" (le texte ci-dessous est tronqué pour limiter la consommation de "
                          "tokens, mais ces statistiques portent sur le fichier ORIGINAL complet)"
                          if stats.get("truncated_for_llm") else "")
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
            "1. Réponds STRICTEMENT et EXCLUSIVEMENT à partir du contexte RAG (RAG Context) fourni ci-dessous. N'invente pas d'informations et n'utilise pas tes connaissances externes ou générales.\n"
            "2. Si l'information demandée n'est pas présente dans le RAG Context, dis explicitement que tu ne trouves pas l'information dans les spécifications fournies au lieu d'extrapoler, d'inventer ou de deviner.\n"
            "3. RÈGLE D'ARRÊT STRICTE (HARD STOP) : Si l'information demandée n'est VRAIMENT pas présente dans le RAG Context, indique-le clairement et arrête ta réponse. Toutefois, si des données équivalentes ou sous une forme proche existent dans le RAG Context (par exemple des trames réseau, échanges ou commandes/réponses HSM type 'TO HSM:', 'FROM HSM:', 'ECS', 'ED01' ou des codes d'erreur), utilise-les pour répondre à la question de l'utilisateur sans déclencher de refus injustifié.\n"
            "   Exemple de comportement obligatoire :\n"
            "   Question : 'Quelle est la taille du champ 37 dans la spécification ?'\n"
            "   Réponse : 'Je ne trouve pas l'information concernant le champ 37 dans le contexte RAG actuel.' (Et STOP. Ne rien ajouter d'autre après cette phrase).\n"
            "4. Prends en compte l'historique de la conversation pour comprendre le contexte des questions de suivi.\n"
            "5. Formate tes réponses dans un Markdown clair, soigné, structuré et professionnel (tableaux, listes à puces si approprié).\n"
            "6. Réponds en français.\n"
            "7. Si une métadonnée est fournie avec une mention du type '[Métadonnées calculées automatiquement...]', tu DOIS utiliser cette valeur telle quelle. Ne recalcule/ne recompte jamais toi-même à partir du texte brut : tu n'es pas fiable pour compter du texte (lignes, caractères, etc.). Cite uniquement et mot pour mot la valeur donnée dans ces métadonnées.\n"
            "8. Tu peux également répondre à des questions sur les documents de spécification ou guides techniques (fichiers PDF, Excel, ou textes) que l'utilisateur a uploadés pour cette session de test (présents dans la section des documents éphémères du RAG Context).\n"
            "9. Aide l'utilisateur à comprendre les détails des transactions comme les champs [FLD 037] (RRN) et [FLD 039] (Response Code pour l'approbation) ou les fonctions exécutées avec succès (OK) par rapport aux échecs tant que l'information est présente dans le RAG Context.\n\n"
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
        print(f"[WARNING] response.content (validation) is a list instead of string! Normalizing list: {content}")
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
