# backend/app/rag/retriever.py
import os
import re
from pathlib import Path
from langchain_community.vectorstores import PGVector
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv

# Charger les variables d'environnement si ce n'est pas déjà fait
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# Config par défaut de la DB et collection pgvector
CONNECTION_STRING = os.getenv(
    "DATABASE_URL", 
    "postgresql+psycopg2://postgres:password@localhost:5432/hps_docs_db"
)
COLLECTION_NAME = "hps_specifications"

# Singletons pour les embeddings et le vectorstore
_embeddings_instance = None
_vectorstore_instance = None
_session_vectorstore_instance = None

def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Retourne l'instance unique (singleton) pour la génération d'embeddings via Gemini."""
    global _embeddings_instance
    if _embeddings_instance is None:
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("La variable d'environnement GOOGLE_API_KEY ou GEMINI_API_KEY est manquante.")
        _embeddings_instance = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=api_key
        )
    return _embeddings_instance

def get_vectorstore() -> PGVector:
    """Retourne l'instance unique (singleton) de la base vectorielle PGVector."""
    global _vectorstore_instance
    if _vectorstore_instance is None:
        embeddings = get_embeddings()
        _vectorstore_instance = PGVector(
            connection_string=CONNECTION_STRING,
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME
        )
    return _vectorstore_instance

# TODO: langchain_community.vectorstores.PGVector avec connection_string= est déprécié.
# Migrer vers langchain_postgres.PGVector avec connection= lors d'une future refactorisation.
def get_session_vectorstore() -> PGVector:
    """Retourne l'instance unique (singleton) de la base vectorielle PGVector pour les sessions éphémères."""
    global _session_vectorstore_instance
    if _session_vectorstore_instance is None:
        embeddings = get_embeddings()
        _session_vectorstore_instance = PGVector(
            connection_string=CONNECTION_STRING,
            embedding_function=embeddings,
            collection_name="hps_session_files"
        )
        ensure_session_id_index()
    return _session_vectorstore_instance

def ensure_session_id_index():
    """Crée des index sur cmetadata->>'session_id' et cmetadata->>'file_hash' si la table existe."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_langchain_pg_embedding_session_id ON langchain_pg_embedding ((cmetadata->>'session_id'))")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_langchain_pg_embedding_file_hash ON langchain_pg_embedding ((cmetadata->>'file_hash'))")
            )
            conn.commit()
        print("[INDEX] Index idx_langchain_pg_embedding_session_id / file_hash verifie / cree avec succes.")
    except Exception as e:
        print(f"[WARN] Remarque indexation pgvector (optionnelle si table non creee) : {e}")

def find_chunks_by_file_hash(file_hash: str) -> dict:
    """Recherche les chunks existants pour un file_hash donné et retourne des métadonnées (count, total_pages et existing_chunk_indices)."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            chunk_count = conn.execute(
                text("SELECT COUNT(*) FROM langchain_pg_embedding WHERE cmetadata->>'file_hash' = :file_hash"),
                {"file_hash": file_hash}
            ).scalar()

            if chunk_count and chunk_count > 0:
                distinct_pages = conn.execute(
                    text("SELECT COUNT(DISTINCT (cmetadata->>'page')::int) FROM langchain_pg_embedding WHERE cmetadata->>'file_hash' = :file_hash AND cmetadata->>'page' IS NOT NULL"),
                    {"file_hash": file_hash}
                ).scalar() or 0

                rows = conn.execute(
                    text("SELECT DISTINCT (cmetadata->>'chunk_index')::int FROM langchain_pg_embedding WHERE cmetadata->>'file_hash' = :file_hash AND cmetadata->>'chunk_index' IS NOT NULL"),
                    {"file_hash": file_hash}
                ).fetchall()
                existing_indices = set(r[0] for r in rows if r[0] is not None)

                return {
                    "found": True,
                    "chunk_count": chunk_count,
                    "total_pages": distinct_pages,
                    "existing_chunk_indices": existing_indices
                }
    except Exception as e:
        print(f"[WARN] find_chunks_by_file_hash failed: {e}")
    return {"found": False, "chunk_count": 0, "total_pages": 0, "existing_chunk_indices": set()}

def count_session_chunks(session_id: str) -> dict:
    """Diagnostic helper: compte les chunks présents pour une session_id donnée et liste les session_ids en base."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            session_count = conn.execute(
                text("SELECT COUNT(*) FROM langchain_pg_embedding WHERE cmetadata->>'session_id' = :session_id"),
                {"session_id": session_id}
            ).scalar()
            
            distinct_sessions_res = conn.execute(
                text("SELECT DISTINCT cmetadata->>'session_id' FROM langchain_pg_embedding WHERE cmetadata->>'session_id' IS NOT NULL")
            ).fetchall()
            distinct_sessions = [row[0] for row in distinct_sessions_res if row[0]]
            
            return {
                "session_id": session_id,
                "chunk_count": session_count,
                "all_active_session_ids": distinct_sessions
            }
    except Exception as e:
        print(f"[WARN] Diagnostic count_session_chunks failed: {e}")
        return {"session_id": session_id, "chunk_count": 0, "all_active_session_ids": [], "error": str(e)}

def search_session_chunks_keyword(session_id: str, keyword: str, file_hashes: list = None, limit: int = 5) -> list:
    """Effectue une recherche textuelle directe ILIKE dans langchain_pg_embedding filtrée par file_hashes ou fallback session_id."""
    try:
        from sqlalchemy import create_engine, text
        from langchain_core.documents import Document
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            if file_hashes:
                # Filtrer par file_hash IN (...) OU fallback session_id
                query = text(
                    "SELECT document, cmetadata FROM langchain_pg_embedding "
                    "WHERE (cmetadata->>'file_hash' = ANY(:file_hashes) OR cmetadata->>'session_id' = :session_id) "
                    "AND document ILIKE :pattern "
                    "LIMIT :limit"
                )
                params = {
                    "file_hashes": file_hashes,
                    "session_id": session_id,
                    "pattern": f"%{keyword}%",
                    "limit": limit
                }
            else:
                query = text(
                    "SELECT document, cmetadata FROM langchain_pg_embedding "
                    "WHERE cmetadata->>'session_id' = :session_id "
                    "AND document ILIKE :pattern "
                    "LIMIT :limit"
                )
                params = {
                    "session_id": session_id,
                    "pattern": f"%{keyword}%",
                    "limit": limit
                }
            
            results = conn.execute(query, params).fetchall()
            
            documents = []
            for row in results:
                doc_text, meta = row[0], row[1]
                import json
                if isinstance(meta, str):
                    meta = json.loads(meta)
                documents.append(Document(page_content=doc_text, metadata=meta or {}))
            return documents
    except Exception as e:
        print(f"[WARN] Hybrid keyword search failed for session '{session_id}', keyword '{keyword}': {e}")
        return []

class QuotaExhaustedError(Exception):
    """Exception levée lorsque le quota API d'embeddings Gemini est totalement épuisé."""
    def __init__(self, message: str, indexed_count: int = 0, total_chunks: int = 0):
        super().__init__(message)
        self.indexed_count = indexed_count
        self.total_chunks = total_chunks

def _is_rate_limit_error(exception: Exception) -> bool:
    """Détermine si l'erreur est un 429 RESOURCE_EXHAUSTED / Rate Limit."""
    err_str = str(exception).lower()
    return "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str or "rate limit" in err_str

def _check_and_increment_daily_embedding_usage(limit: int = 1000):
    """Compteur quotidien SQLite d'appels API d'embedding."""
    import sqlite3
    from datetime import date
    
    db_dir = Path(__file__).resolve().parents[1] / "storage"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "embedding_usage.db"
    
    today_str = date.today().isoformat()
    
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS daily_usage (usage_date TEXT PRIMARY KEY, request_count INTEGER DEFAULT 0)"
        )
        cursor.execute("SELECT request_count FROM daily_usage WHERE usage_date = ?", (today_str,))
        row = cursor.fetchone()
        current_count = row[0] if row else 0
        
        if current_count >= limit:
            raise QuotaExhaustedError(
                f"Proactive Quota Shield: Today's Gemini embedding API requests ({current_count}) reached/exceeded the daily quota limit of {limit} requests."
            )
            
        new_count = current_count + 1
        cursor.execute(
            "INSERT INTO daily_usage (usage_date, request_count) VALUES (?, ?) "
            "ON CONFLICT(usage_date) DO UPDATE SET request_count = ?",
            (today_str, new_count, new_count)
        )
        conn.commit()
        print(f"[USAGE_TRACKER] Gemini Embedding API request count for {today_str}: {new_count}/{limit}")
    finally:
        conn.close()

def estimate_tokens(text: str) -> int:
    """Estime le nombre de tokens d'un texte (approximation 4 caractères = 1 token)."""
    if not text:
        return 0
    return len(text) // 4

def _extract_retry_delay_seconds(retry_state) -> float:
    """Extrait le délai de retry ('retryDelay') de la dernière exception si disponible dans retry_state."""
    if not retry_state or not retry_state.outcome:
        return 0.0
    try:
        exc = retry_state.outcome.exception()
    except Exception:
        exc = None
    if not exc:
        return 0.0

    import re
    err_str = str(exc)
    match = re.search(r"retryDelay[\"']?\s*:\s*[\"']?(\d+(?:\.\d+)?)s?[\"']?", err_str, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1)) + 1.0  # +1.0s buffer
        except ValueError:
            pass
    return 0.0

def batch_add_documents(
    vectorstore,
    documents: list,
    batch_size: int = None,
    inter_batch_delay: float = None,
    max_retries: int = 5,
    initial_delay: float = 5.0,
    session_id: str = None
):
    """
    Ingère les documents par lots (batches) dynamiques basés sur le nombre de documents et le nombre de tokens
    estimés, avec retry/backoff ou parsing de retryDelay sur 429, suivi de quota quotidien SQLite et logs détaillés.
    """
    import time
    from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception
    from app.core.config import (
        EMBEDDING_BATCH_SIZE, 
        EMBEDDING_BATCH_DELAY_SECONDS, 
        EMBEDDING_MAX_TOKENS_PER_BATCH
    )

    if batch_size is None:
        batch_size = EMBEDDING_BATCH_SIZE
    if inter_batch_delay is None:
        inter_batch_delay = EMBEDDING_BATCH_DELAY_SECONDS

    total_chunks = len(documents)
    if total_chunks == 0:
        return 0

    # Decoupage dynamique token-aware en lots
    batches = []
    current_batch = []
    current_batch_tokens = 0

    for doc in documents:
        doc_tokens = estimate_tokens(doc.page_content or "")
        
        # Un chunk individuel géant dépasse à lui seul le cap : on le force dans son propre lot
        if current_batch and (len(current_batch) >= batch_size or (current_batch_tokens + doc_tokens > EMBEDDING_MAX_TOKENS_PER_BATCH)):
            batches.append((current_batch, current_batch_tokens))
            current_batch = []
            current_batch_tokens = 0
            
        current_batch.append(doc)
        current_batch_tokens += doc_tokens

    if current_batch:
        batches.append((current_batch, current_batch_tokens))

    total_batches = len(batches)
    print(f"[BATCH] Début de l'ingestion de {total_chunks} chunks découpés en {total_batches} lots dynamiques (max {batch_size} chunks et max {EMBEDDING_MAX_TOKENS_PER_BATCH} tokens/lot, délai inter-lot: {inter_batch_delay}s)...")
    
    indexed_count = 0
    try:
        for b_idx, (batch, b_tokens) in enumerate(batches, 1):
            # Proactive quota check before sending API request
            _check_and_increment_daily_embedding_usage(limit=1000)

            print(
                f"[BATCH] Lot {b_idx}/{total_batches} : {len(batch)} chunks (~{b_tokens:,} tokens estimés). "
                f"Attente {inter_batch_delay}s après traitement (quota RPM/TPM Gemini)..."
            )

            retryer = Retrying(
                stop=stop_after_attempt(max_retries),
                wait=wait_exponential(multiplier=1.0, min=initial_delay, max=60.0),
                retry=retry_if_exception(_is_rate_limit_error),
                reraise=True
            )
            
            try:
                for attempt in retryer:
                    with attempt:
                        if attempt.retry_state.attempt_number > 1:
                            delay_override = _extract_retry_delay_seconds(attempt.retry_state)
                            if delay_override > 0:
                                print(f"[WARN] 429 reçu avec retryDelay spécifié. Pause forcée de {delay_override:.1f}s...")
                                time.sleep(delay_override)
                            else:
                                print(
                                    f"[WARN] tentative {attempt.retry_state.attempt_number}/{max_retries} pour le lot "
                                    f"{b_idx}/{total_batches} suite à 429 / Rate Limit..."
                                )
                        vectorstore.add_documents(batch)
            except Exception as err:
                print(f"[ERROR] Échec lors de l'ingestion du lot {b_idx}/{total_batches} ({len(batch)} chunks) après retries. Type: {type(err).__name__}, Détails: {err}")
                if _is_rate_limit_error(err):
                    raise QuotaExhaustedError(
                        f"Gemini free-tier quota exhausted after indexing {indexed_count}/{total_chunks} chunks.",
                        indexed_count=indexed_count,
                        total_chunks=total_chunks
                    ) from err
                raise err

            indexed_count += len(batch)
            print(f"[PROGRESS] Embedded {indexed_count}/{total_chunks} chunks dans pgvector.")
            
            if b_idx < total_batches and inter_batch_delay > 0:
                time.sleep(inter_batch_delay)

        return total_chunks

    except Exception as e:
        # NOTE: Do NOT delete already-embedded chunks here.
        # Successfully embedded chunks remain persisted in pgvector so resuming is possible.
        raise e



def delete_session_documents(session_id: str):
    """Supprime tous les documents associés à une session dans PGVector."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM langchain_pg_embedding WHERE cmetadata->>'session_id' = :session_id"),
                {"session_id": session_id}
            )
            conn.commit()
        print(f"[DELETE] Documents de la session '{session_id}' memoires/supprimes de pgvector.")
    except Exception as e:
        print(f"[WARN] Impossible de supprimer les documents de session dans pgvector : {e}")


def _local_excel_fallback(query: str, k: int = 4) -> str:
    """Fallback local : recherche textuelle simple par mot-clé dans Spec_PowerCARD.xlsx"""
    try:
        from app.services.spec_loader import load_function_specs
        project_root = Path(__file__).resolve().parents[2]
        
        # Résolution du chemin du fichier Excel
        excel_path = project_root / "app" / "storage" / "Spec_PowerCARD.xlsx"
        if not excel_path.exists():
            excel_path = project_root / "backend" / "app" / "storage" / "Spec_PowerCARD.xlsx"
            
        if excel_path.exists():
            specs = load_function_specs(str(excel_path))
            matches = []
            
            # Nettoyage et découpage de la requête en mots-clés
            keywords = [kw.lower() for kw in re.findall(r"\w+", query) if len(kw) > 2]
            
            for func_name, info in specs.items():
                score = 0
                func_name_lower = func_name.lower()
                desc_lower = info.get("description", "").lower()
                exc_lower = info.get("exception", "").lower()
                
                # Recherche par mot-clé avec système de score simple
                for kw in keywords:
                    if kw in func_name_lower:
                        score += 10
                    if kw in desc_lower:
                        score += 3
                    if kw in exc_lower:
                        score += 2
                        
                # Si le nom de la fonction est directement dans la requête (exact match)
                if func_name_lower in query.lower():
                    score += 20
                    
                MIN_RELEVANCE_SCORE = 8
                if score >= MIN_RELEVANCE_SCORE:
                    matches.append((score, func_name, info))
            
            # Tri des correspondances par pertinence décroissante
            matches.sort(key=lambda x: x[0], reverse=True)
            top_matches = matches[:k]
            
            if top_matches:
                formatted_docs = []
                for i, (score, func_name, info) in enumerate(top_matches, 1):
                    content = (
                        f"Fonction {func_name.strip()} (module {info['source']}, fichier {info['path']})\n"
                        f"Description : {info['description']}\n"
                        f"Conditions : {info['exception']}"
                    )
                    formatted_docs.append(
                        f"--- Extrait {i} (Source: Spec_PowerCARD.xlsx (Fallback Local), Fonction: {func_name}) ---\n"
                        f"{content}"
                    )
                return "\n\n".join(formatted_docs)
    except Exception as fallback_err:
        print(f"❌ Échec critique du fallback de recherche Excel : {fallback_err}")
        
    return ""


def query_specs(query: str, k: int = 4) -> str:
    """
    Exécute une recherche de similarité sur les spécifications PowerCARD.
    Formate le résultat en un unique bloc textuel propre indiquant la source de chaque segment.
    """
    try:
        db = get_vectorstore()
        docs = db.similarity_search(query, k=k)
        
        # Vérification si les documents matchent le ou les mots-clés/fonctions de la requête
        query_words = {w.lower() for w in re.findall(r"\w+", query) if w}
        has_matching_doc = False
        if docs:
            for doc in docs:
                func_name = doc.metadata.get("function")
                if func_name:
                    func_lower = str(func_name).strip().lower()
                    if func_lower in query_words or any(w in func_lower for w in query_words):
                        has_matching_doc = True
                        break
                        
        if docs and has_matching_doc:
            formatted_docs = []
            for i, doc in enumerate(docs, 1):
                source = doc.metadata.get("module") or doc.metadata.get("source_file", "Inconnu")
                function_name = doc.metadata.get("function", "N/A")
                formatted_docs.append(
                    f"--- Extrait {i} (Source: {source}, Fonction: {function_name}) ---\n"
                    f"{doc.page_content.strip()}"
                )
            return "\n\n".join(formatted_docs)
        else:
            print("⚠️ Aucun document pgvector trouvé ou aucun ne correspond aux fonctions de la requête. Utilisation du fallback Excel...")
            return _local_excel_fallback(query, k=k)
    except Exception as e:
        print(f"⚠️ Recherche vectorielle échouée (Erreur: {type(e).__name__} - {str(e)}). Utilisation du fallback Excel local...")
        return _local_excel_fallback(query, k=k)
