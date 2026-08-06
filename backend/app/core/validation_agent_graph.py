# backend/app/core/validation_agent_graph.py
import os
import re
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

def _filter_session_trace_content(raw_content: str, question: str, max_chars: int = 80000) -> str:
    """
    Filtre intelligemment le contenu d'un fichier trace de session pour le LLM.
    Si le contenu dépasse max_chars, sélectionne des blocs de transactions complets
    correspondant aux mots-clés de la question ou contenant des alertes/erreurs.
    Ne tronque JAMAIS à l'intérieur d'une transaction — coupe uniquement entre blocs complets.
    Annote précisément le nombre de transactions incluses vs total.

    Augmentation de max_chars : 15000 → 80000 (Gemini 2.0 Flash supporte 1M tokens;
    une trace de ~1800 lignes représente ~50-70k chars soit ~15-18k tokens, bien en dessous
    du plafond).
    """
    if not raw_content or len(raw_content) <= max_chars:
        return raw_content

    tx_blocks = raw_content.split("=== Transaction ")
    if len(tx_blocks) <= 1:
        return raw_content[:max_chars] + f"\n\n[TRONCATURAGE DE SÉCURITÉ : Trace non structurée de {len(raw_content)} caractères tronquée aux {max_chars} premiers caractères.]"

    # En-tête (synthèse globale si présente)
    header = tx_blocks[0].strip()
    blocks = [f"=== Transaction {b.strip()}" for b in tx_blocks[1:] if b.strip()]
    total_tx = len(blocks)

    from app.rag.retriever import extract_code_tokens
    # Codes 2 lettres (EC, ED, CA...)
    code_tokens_2l = extract_code_tokens(question)
    # Codes alphanumériques plus longs (ED01, ECS, ED01, etc.) : capture [A-Z0-9]{2,6}
    extended_tokens = re.findall(r"\b[A-Z0-9]{2,6}\b", question.upper())
    stopwords_ext = {
        "ET", "OU", "DE", "LE", "LA", "DU", "AU", "UN", "EN", "SI", "NO",
        "CE", "CI", "SA", "SES", "SON", "EST", "PAS", "QUE", "QUI", "PAR",
        "SUR", "DES", "NE", "ON", "IL", "SE", "MA", "TA", "TE", "ME",
        "AVEC", "DANS", "POUR", "CETTE", "QUEL", "QUELLE", "SONT", "LES", "PLUS",
        "COMMENT", "FIELD", "TRANSACTION", "STAN", "PAN", "RRN", "MTI", "CODE", "RESPONSE",
        "QU"
    }
    code_tokens_extended = [t for t in extended_tokens if t not in stopwords_ext]

    q_lower = question.lower()
    stopwords = {w.lower() for w in stopwords_ext}
    q_tokens = [w for w in re.findall(r"\w+", q_lower) if len(w) >= 2 and w not in stopwords]
    # Union de tous les termes de recherche
    all_search_terms = list(set(code_tokens_2l + code_tokens_extended + [t.upper() for t in q_tokens]))

    relevant_blocks = []
    alert_blocks = []
    other_blocks = []

    for blk in blocks:
        blk_upper = blk.upper()
        if any(term in blk_upper for term in all_search_terms):
            relevant_blocks.append(blk)
        elif any(alert_kw in blk.lower() for alert_kw in ["alerte", "alertes:", "erreur", "échec", "nok", "-1", "-2"]):
            alert_blocks.append(blk)
        else:
            other_blocks.append(blk)

    # Assemblage ordonné des blocs sans jamais couper une transaction
    selected_relevant = []
    selected_alerts = []
    selected_other = []
    seen_indices = set()
    current_len = len(header) + 200 if header else 0

    # Blocs pertinents
    for blk in relevant_blocks:
        m = re.search(r"=== Transaction (\d+)", blk)
        tx_idx = m.group(1) if m else blk[:30]
        if tx_idx in seen_indices:
            continue
        if current_len + len(blk) + 4 <= max_chars:
            selected_relevant.append(blk)
            seen_indices.add(tx_idx)
            current_len += len(blk) + 4
        elif len(selected_relevant) == 0:
            selected_relevant.append(blk)
            seen_indices.add(tx_idx)
            current_len += len(blk) + 4
            break

    # Blocs avec alertes
    for blk in alert_blocks:
        m = re.search(r"=== Transaction (\d+)", blk)
        tx_idx = m.group(1) if m else blk[:30]
        if tx_idx in seen_indices:
            continue
        if current_len + len(blk) + 4 <= max_chars:
            selected_alerts.append(blk)
            seen_indices.add(tx_idx)
            current_len += len(blk) + 4
        elif len(selected_relevant) == 0 and len(selected_alerts) == 0:
            selected_alerts.append(blk)
            seen_indices.add(tx_idx)
            current_len += len(blk) + 4
            break

    # Autres blocs
    for blk in other_blocks:
        m = re.search(r"=== Transaction (\d+)", blk)
        tx_idx = m.group(1) if m else blk[:30]
        if tx_idx in seen_indices:
            continue
        if current_len + len(blk) + 4 <= max_chars:
            selected_other.append(blk)
            seen_indices.add(tx_idx)
            current_len += len(blk) + 4
        elif len(selected_relevant) == 0 and len(selected_alerts) == 0 and len(selected_other) == 0:
            selected_other.append(blk)
            seen_indices.add(tx_idx)
            current_len += len(blk) + 4
            break

    included_count = len(selected_relevant) + len(selected_alerts) + len(selected_other)
    result_parts = []
    if header:
        result_parts.append(header)

    if selected_relevant:
        result_parts.append("=== TRANSACTIONS RECHERCHÉES / PERTINENTES ===\n" + "\n\n".join(selected_relevant))
    if selected_alerts:
        result_parts.append("=== TRANSACTIONS AVEC ALERTES / ERREURS DÉTECTÉES ===\n" + "\n\n".join(selected_alerts))
    if selected_other:
        result_parts.append("=== AUTRES TRANSACTIONS DE LA TRACE ===\n" + "\n\n".join(selected_other))

    if included_count < total_tx:
        result_parts.append(
            f"\n[AVERTISSEMENT TRONCATURAGE DE CONTEXTE : {included_count}/{total_tx} transactions complètes incluses dans le contexte LLM "
            f"(limite de {max_chars:,} caractères atteinte). "
            f"Le comptage exact dans les métadonnées ci-dessus est calculé sur l'INTÉGRALITÉ de la trace "
            f"et fait foi — ne pas recompter depuis ce texte partiel. "
            f"Consulter le rapport PDF complet pour les {total_tx - included_count} transaction(s) restante(s).]"
        )
    else:
        result_parts.append(f"\n[TRACE COMPLÈTE : {total_tx}/{total_tx} transactions incluses dans le contexte RAG.]")

    return "\n\n".join(result_parts)


# Nœud 1 : Retriever
def retriever_node(state: ValidationState) -> Dict[str, Any]:
    """
    Interroge le RAG partagé avec la question de l'utilisateur pour extraire
    les extraits de spécifications pertinents, et y accole les documents de session éphémères.
    """
    question = state.get("user_question", "")
    session_id = state.get("session_id", "")
    chat_history = state.get("chat_history", [])

    recent_turns = chat_history[-2:] if chat_history else []
    context_snippet = " ".join(
        turn.get("content", "") for turn in recent_turns if turn.get("content")
    )
    search_query = f"{context_snippet} {question}".strip() if context_snippet else question
    
    sources = []
    
    # 1. Requête du RAG persistant classique
    official_specs = query_specs(search_query, k=8)
    
    context_blocks = []
    if official_specs.strip():
        context_blocks.append(f"=== SPÉCIFICATIONS OFFICIELLES (RAG) ===\n{official_specs}")
        sources.append({"type": "spec", "label": "Spec PowerCARD"})
    else:
        context_blocks.append("=== SPÉCIFICATIONS OFFICIELLES (RAG) ===\nAucune spécification officielle correspondante trouvée.")

    # 2. Contexte éphémère de la session
    if session_id:
        from app.rag.retriever import count_session_chunks, search_session_chunks_keyword, query_command_code, extract_code_tokens
        diag = count_session_chunks(session_id)
        print(
            f"[RETRIEVER_DIAG] Filter session_id: '{session_id}' | "
            f"Chunks in DB for this session: {diag.get('chunk_count', 0)} | "
            f"All active session_ids in DB: {diag.get('all_active_session_ids', [])}"
        )

        session_files = get_session_files(session_id)
        if session_files:
            file_hashes = [f["file_hash"] for f in session_files if f.get("file_hash")]
            
            file_blocks = []
            for file_info in session_files:
                filename = file_info["name"]
                stats = file_info.get("stats", {})
                raw_file_content = file_info.get("content", "")
                
                # Si c'est un fichier indexé via RAG éphémère (PDF)
                if file_info.get("is_rag") or filename.lower().endswith('.pdf'):
                    try:
                        from app.rag.retriever import get_session_vectorstore
                        session_db = get_session_vectorstore()

                        broad_keywords = [
                            "résume", "resume", "summarize", "summary", "overview", 
                            "combien de", "toutes les", "tous les", "sommaire", "global",
                            "structure", "chapitres", "sections", "présente", "presente"
                        ]
                        q_lower = question.lower()
                        is_broad_query = any(kw in q_lower for kw in broad_keywords)
                        session_k = 16 if is_broad_query else 8

                        field_pattern = re.compile(r'(?:field|champ|fld)\s*0*(\d+)', re.IGNORECASE)
                        field_matches = field_pattern.findall(question)

                        cmd_matches = extract_code_tokens(question)

                        keyword_docs = []
                        if field_matches:
                            for field_num in field_matches:
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
                                    found = search_session_chunks_keyword(
                                        session_id, 
                                        term, 
                                        file_hashes=file_hashes if file_hashes else None, 
                                        limit=3
                                    )
                                    if found:
                                        keyword_docs.extend(found)

                        if cmd_matches:
                            for cmd_code in cmd_matches:
                                cmd_docs = query_command_code(cmd_code, session_id=session_id, limit=5)
                                if cmd_docs:
                                    keyword_docs.extend(cmd_docs)
                            
                            parity_docs = search_session_chunks_keyword(
                                session_id,
                                "parity error",
                                file_hashes=file_hashes if file_hashes else None,
                                limit=3
                            )
                            if parity_docs:
                                keyword_docs.extend(parity_docs)

                        target_file_hash = file_info.get("file_hash")
                        filter_dict = {"file_hash": target_file_hash} if target_file_hash else {"session_id": session_id}

                        semantic_docs = session_db.similarity_search(
                            search_query, 
                            k=session_k, 
                            filter=filter_dict
                        )

                        seen_contents = set()
                        relevant_docs = []
                        for doc in keyword_docs + semantic_docs:
                            content_snippet = doc.page_content.strip()
                            if content_snippet not in seen_contents:
                                seen_contents.add(content_snippet)
                                relevant_docs.append(doc)

                        MAX_RAG_CHUNKS = 10
                        relevant_docs = relevant_docs[:MAX_RAG_CHUNKS]

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
                    content = _filter_session_trace_content(raw_file_content, question)

                # --- COMPTAGE ET RECHERCHE EXACTE DÉTERMINISTE SUR TRACE COMPLÈTE ---
                # Cette section opère sur raw_file_content (trace COMPLÈTE), jamais sur le
                # texte potentiellement filtré/tronqué. Les valeurs ici font autorité.
                exact_count_notes = []
                detected_query_tokens = extract_code_tokens(question)
                # Ajouter également les jetons alerte/erreur : codes alphanumériques 2-6 chars
                additional_tokens = re.findall(r"\b[A-Z0-9]{2,6}\b", question.upper())
                stopwords_count = {
                    "COMBIEN", "NOMBRE", "TRACE", "ERREUR", "AVEC", "DANS", "POUR",
                    "CETTE", "QUEL", "SONT", "LES", "DES", "ET", "OU", "DE", "LE",
                    "LA", "DU", "AU", "UN", "EN", "SI", "NO", "CE", "CI", "SA",
                    "EST", "PAS", "QUE", "QUI", "PAR", "SUR", "NE", "ON", "IL"
                }
                for tok in additional_tokens:
                    if tok not in detected_query_tokens and tok not in stopwords_count:
                        detected_query_tokens.append(tok)

                if raw_file_content and detected_query_tokens:
                    tx_blocks = raw_file_content.split("=== Transaction ")
                    total_tx_in_raw = len(tx_blocks) - 1 if len(tx_blocks) > 1 else 1

                    for tok in detected_query_tokens:
                        occurrences = raw_file_content.count(tok)
                        if occurrences > 0:
                            matched_txs = []
                            if len(tx_blocks) > 1:
                                for idx, b in enumerate(tx_blocks[1:], 1):
                                    if tok in b:
                                        matched_txs.append(f"#{idx}")
                            tx_info_str = f" (dans transaction(s): {', '.join(matched_txs)})" if matched_txs else ""
                            exact_count_notes.append(
                                f"Code/Terme '{tok}' : exactement {occurrences} occurrence(s) sur l'ensemble de la trace{tx_info_str}"
                            )

                count_summary = (" | " + " ; ".join(exact_count_notes)) if exact_count_notes else ""

                # --- ENRICHISSEMENT RAG SPECS POUR FICHIERS TRACE (non-PDF) ---
                # Si des codes HSM sont détectés et que le fichier est une trace (pas un PDF),
                # on injecte aussi les extraits de spécification correspondants pour que le LLM
                # puisse expliquer les codes (ex: ED → EC) sans dépendre d'un PDF de specs uploadé.
                spec_enrichment = ""
                if not (file_info.get("is_rag") or filename.lower().endswith('.pdf')):
                    spec_codes_detected = list(detected_query_tokens)  # codes détectés dans la question
                    spec_snippets = []
                    from app.rag.retriever import query_command_code as _qcc
                    for tok in spec_codes_detected:
                        if len(tok) == 2 and tok.isalpha():  # seulement les codes 2 lettres purs (EC, ED, CA...)
                            spec_docs = _qcc(tok, limit=3)
                            for sd in spec_docs:
                                snippet = sd.page_content.strip()
                                if snippet and snippet not in spec_snippets:
                                    # Injecter l'annotation de correspondance si disponible
                                    cmd_c = sd.metadata.get("command_code", "")
                                    resp_c = sd.metadata.get("response_code", "")
                                    corresp = ""
                                    if cmd_c and resp_c and cmd_c != resp_c:
                                        corresp = f"[Code Commande '{cmd_c}' ↔ Code Réponse '{resp_c}'] "
                                    spec_snippets.append(f"{corresp}{snippet}")
                    if spec_snippets:
                        spec_enrichment = (
                            f"\n\n--- Spécifications HSM correspondantes (extraites du référentiel) ---\n"
                            + "\n\n".join(spec_snippets[:4])
                        )

                truncation_note = (
                    " (le texte ci-dessous contient les extraits les plus pertinents basés sur votre recherche)"
                    if file_info.get("is_rag") or filename.lower().endswith('.pdf')
                    else (" (valeurs calculées sur l'intégralité du fichier de session original)")
                )
                meta_header = (
                    f"[Métadonnées calculées automatiquement sur le fichier COMPLET — "
                    f"valeurs exactes à respecter obligatoirement, ne pas recompter sur le texte tronqué{truncation_note}]\n"
                    f"Lignes : {stats.get('line_count', '?')} | "
                    f"Lignes non vides : {stats.get('non_empty_line_count', '?')} | "
                    f"Caractères : {stats.get('char_count', '?')}{count_summary}"
                )

                file_blocks.append(
                    f"--- Fichier uploadé : {filename} ---\n"
                    f"{meta_header}\n"
                    f"{content}"
                    f"{spec_enrichment}"
                )
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

    chat_history_raw = chat_history_raw[-6:]

    formatted_messages = []
    for msg in chat_history_raw:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            formatted_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            formatted_messages.append(AIMessage(content=content))

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", (
            "Tu es un Agent Expert en Spécifications PowerCARD et validation de traces pour les testeurs HPS.\n"
            "Ton but est d'aider les testeurs à valider le comportement de la plateforme en répondant à leurs questions.\n\n"
            "Règles strictes :\n"
            "1. Réponds STRICTEMENT et EXCLUSIVEMENT à partir du contexte RAG (RAG Context) fourni ci-dessous. N'invente pas d'informations et n'utilise pas tes connaissances externes ou générales.\n"
            "2. Si l'information demandée n'est pas présente dans le RAG Context, dis explicitement que tu ne trouves pas l'information dans les spécifications fournies au lieu d'extrapoler, d'inventer ou de deviner.\n"
            "3. RÈGLE D'ARRÊT STRICTE (HARD STOP) : Si l'information demandée n'est VRAIMENT pas présente dans le RAG Context, indique-le clairement et arrête ta réponse. Toutefois, si des données équivalentes ou sous une forme proche existent dans le RAG Context (par exemple des trames réseau, échanges ou commandes/réponses HSM type 'TO HSM:', 'FROM HSM:', 'ECS', 'ED01' ou des codes d'erreur), utilise-les pour répondre à la question de l'utilisateur sans déclencher de refus injustifié.\n"
            "4. Prends en compte l'historique de la conversation pour comprendre le contexte des questions de suivi.\n"
            "5. Formate tes réponses dans un Markdown clair, soigné, structuré et professionnel (tableaux, listes à puces si approprié).\n"
            "6. Réponds en français.\n"
            "7. RÈGLE DES MÉTADONNÉES : Si des métadonnées calculées automatiquement sont présentes (ex: '[Métadonnées calculées automatiquement sur le fichier COMPLET...]'), tu DOIS obligatoirement utiliser ces valeurs et nombres exacts (ex: nombre exact d'occurrences d'une erreur ou nombre total de transactions). Ne recompte jamais toi-même à partir du texte partiel tronqué du prompt.\n"
            "8. CORRESPONDANCE CODE COMMANDE / RÉPONSE : Lorsqu'un code de réponse est interrogé (ex: ED), si le contexte RAG indique qu'il correspond à un code de commande (ex: EC), tu DOIS obligatoirement citer le code de commande correspondant (ex: 'Le code de réponse ED correspond à la commande EC') et décrire sa fonction.\n"
            "9. Aide l'utilisateur à comprendre les détails des transactions comme les champs [FLD 037] (RRN) et [FLD 039] (Response Code pour l'approbation) ou les fonctions exécutées avec succès (OK) par rapport aux échecs tant que l'information est présente dans le RAG Context.\n\n"
            "RAG Context :\n"
            "{rag_context}"
        )),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{user_question}")
    ])

    # Diagnostic du nombre de tokens par composant
    from app.rag.retriever import estimate_tokens
    tok_rag = estimate_tokens(rag_context)
    tok_hist = sum(estimate_tokens(getattr(m, "content", str(m))) for m in formatted_messages)
    tok_q = estimate_tokens(question)
    tok_total = tok_rag + tok_hist + tok_q

    print(
        f"=== [PROMPT TOKEN DIAGNOSTICS] (ValidationAgent) ===\n"
        f"   ↳ Contexte RAG/Trace : ~{tok_rag:,} tokens\n"
        f"   ↳ Historique Chat    : ~{tok_hist:,} tokens\n"
        f"   ↳ Question Utilisateur: ~{tok_q:,} tokens\n"
        f"   ↳ TOTAL ESTIMÉ PROMPT: ~{tok_total:,} tokens (Plafond Gemini Free Tier : 250 000 TPM)\n"
        f"=========================================================================="
    )

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
