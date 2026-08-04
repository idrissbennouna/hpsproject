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
    """
    Recherche les chunks existants pour un file_hash SHA-256 donné et la version de chunking actuelle (CHUNKING_VERSION).
    
    COMPORTEMENT DE CACHE ET DÉDUPLICATION PAR HASH :
    - Vérifie si le fichier PDF a déjà été vectorisé avec la version de chunking actuelle.
    - Si les chunks en base possèdent une version obsolète ou absente, ils sont ignorés (found=False)
      pour forcer un ré-embedding complet propre.
    """
    from app.core.config import CHUNKING_VERSION
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            # 1. Vérification de l'existence de chunks pour ce file_hash (toutes versions confondues)
            total_hash_chunks = conn.execute(
                text("SELECT COUNT(*) FROM langchain_pg_embedding WHERE cmetadata->>'file_hash' = :file_hash"),
                {"file_hash": file_hash}
            ).scalar() or 0

            # 2. Compte des chunks correspondant exactement à CHUNKING_VERSION
            matching_version_chunks = conn.execute(
                text(
                    "SELECT COUNT(*) FROM langchain_pg_embedding "
                    "WHERE cmetadata->>'file_hash' = :file_hash "
                    "AND cmetadata->>'chunking_version' = :version"
                ),
                {"file_hash": file_hash, "version": CHUNKING_VERSION}
            ).scalar() or 0

            # Si des anciens chunks existent mais avec une version obsolète/absente
            if total_hash_chunks > 0 and matching_version_chunks == 0:
                print(f"[CHUNKING_VERSION_MISMATCH] Anciens chunks détectés avec une version de chunking obsolète — ré-embedding complet forcé.")
                return {
                    "found": False,
                    "chunk_count": 0,
                    "total_pages": 0,
                    "existing_chunk_indices": set(),
                    "version_mismatch": True
                }

            if matching_version_chunks and matching_version_chunks > 0:
                distinct_pages = conn.execute(
                    text(
                        "SELECT COUNT(DISTINCT (cmetadata->>'page')::text) FROM langchain_pg_embedding "
                        "WHERE cmetadata->>'file_hash' = :file_hash "
                        "AND cmetadata->>'chunking_version' = :version "
                        "AND cmetadata->>'page' IS NOT NULL"
                    ),
                    {"file_hash": file_hash, "version": CHUNKING_VERSION}
                ).scalar() or 0

                rows = conn.execute(
                    text(
                        "SELECT DISTINCT (cmetadata->>'chunk_index')::int FROM langchain_pg_embedding "
                        "WHERE cmetadata->>'file_hash' = :file_hash "
                        "AND cmetadata->>'chunking_version' = :version "
                        "AND cmetadata->>'chunk_index' IS NOT NULL"
                    ),
                    {"file_hash": file_hash, "version": CHUNKING_VERSION}
                ).fetchall()
                existing_indices = set(r[0] for r in rows if r[0] is not None)

                return {
                    "found": True,
                    "chunk_count": matching_version_chunks,
                    "total_pages": distinct_pages,
                    "existing_chunk_indices": existing_indices,
                    "version_mismatch": False
                }
    except Exception as e:
        print(f"[WARN] find_chunks_by_file_hash failed: {e}")
    return {"found": False, "chunk_count": 0, "total_pages": 0, "existing_chunk_indices": set(), "version_mismatch": False}

def update_session_id_for_file_hash(file_hash: str, session_id: str):
    """
    Met à jour les métadonnées session_id et last_accessed dans cmetadata pour tous les chunks correspondant à file_hash.
    """
    try:
        from datetime import datetime, timezone
        from sqlalchemy import create_engine, text
        now_iso = datetime.now(timezone.utc).isoformat()
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE langchain_pg_embedding "
                    "SET cmetadata = (cmetadata::jsonb || jsonb_build_object('session_id', :session_id, 'last_accessed', :now_iso)) "
                    "WHERE cmetadata->>'file_hash' = :file_hash"
                ),
                {"session_id": session_id, "now_iso": now_iso, "file_hash": file_hash}
            )
            conn.commit()
            print(f"[REUSE_HASH] Metadonnée session_id mise à jour vers '{session_id}' pour file_hash '{file_hash[:10]}...'.")
    except Exception as e:
        print(f"[WARN] Impossible de mettre à jour session_id pour file_hash {file_hash[:10]}: {e}")

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


def list_spec_library() -> list:
    """
    Retourne la liste des documents de spécification déjà indexés en base vectorielle,
    dédoublonnés par file_hash. Pour chaque document distinct, retourne :
    - file_hash (SHA-256)
    - source (nom du fichier d'origine)
    - chunk_count (nombre de chunks)
    - created_at (date d'indexation)
    Triés par last_accessed DESC (les plus récemment utilisés en premier).
    """
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT "
                    "  cmetadata->>'file_hash' AS file_hash, "
                    "  cmetadata->>'source' AS source, "
                    "  COUNT(*) AS chunk_count, "
                    "  MIN(cmetadata->>'created_at') AS created_at, "
                    "  MAX(cmetadata->>'last_accessed') AS last_accessed "
                    "FROM langchain_pg_embedding "
                    "WHERE cmetadata->>'file_hash' IS NOT NULL "
                    "  AND cmetadata->>'source' IS NOT NULL "
                    "GROUP BY cmetadata->>'file_hash', cmetadata->>'source' "
                    "ORDER BY last_accessed DESC NULLS LAST "
                    "LIMIT 50"
                )
            ).fetchall()

            result = []
            for row in rows:
                result.append({
                    "file_hash": row[0],
                    "filename": row[1],
                    "chunk_count": int(row[2]),
                    "created_at": row[3],
                    "last_accessed": row[4],
                })
            return result
    except Exception as e:
        print(f"[WARN] list_spec_library failed: {e}")
        return []


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

def retrieve_session_chunks(session_id: str, query: str, file_hashes: list = None, k: int = 5, max_k: int = 10) -> list:
    """
    Recherche sémantique par similarité dans la base vectorielle PGVector pour les documents d'une session.
    Le paramètre k est strictement plafonné à max_k (par défaut 10 chunks maximum, ~3000-5000 tokens)
    afin de préserver le quota d'entrée Gemini (250 000 TPM limit).
    """
    bounded_k = min(k, max_k)
    try:
        session_db = get_session_vectorstore()
        filter_dict = {}
        if file_hashes and len(file_hashes) == 1:
            filter_dict = {"file_hash": file_hashes[0]}
        elif session_id:
            filter_dict = {"session_id": session_id}

        docs = session_db.similarity_search(query, k=bounded_k, filter=filter_dict)
        return docs
    except Exception as e:
        print(f"[WARN] retrieve_session_chunks failed for session '{session_id}': {e}")
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
    import random
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
    estimated_time_minutes = (total_batches * inter_batch_delay) / 60.0
    print(f"[BATCH] Début de l'ingestion de {total_chunks} chunks découpés en {total_batches} lots dynamiques (max {batch_size} chunks et max {EMBEDDING_MAX_TOKENS_PER_BATCH} tokens/lot, délai inter-lot: {inter_batch_delay}s)...")
    print(f"[INGESTION SUMMARY] Nombre total de chunks: {total_chunks} | Nombre total de lots prévus: {total_batches} | Temps total estimé: {estimated_time_minutes:.2f} minute(s)")
    
    indexed_count = 0
    try:
        from app.services.job_tracker import update_job
        for b_idx, (batch, b_tokens) in enumerate(batches, 1):
            if session_id:
                # Calcul progressif du pourcentage pour la phase embedding (ex: de 10% à 50%)
                pct = int(10 + (b_idx / total_batches) * 40)
                update_job(
                    session_id, 
                    stage="embedding_pdf", 
                    detail=f"Indexation du document de spécification (lot {b_idx}/{total_batches})...",
                    progress_pct=pct
                )

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
                jitter_delay = inter_batch_delay + random.uniform(0, 5)
                time.sleep(jitter_delay)

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


def query_specs(query: str, k: int = 8) -> str:
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


def extract_code_tokens(query: str) -> list:
    """
    Extrait les codes à 2 lettres majuscules (ex: EC, ED, CA) d'une question.
    Détecte prioritairement les expressions comme :
      - 'code de réponse ED', 'réponse ED', 'la réponse est ED'
      - 'commande EC', 'la commande EC', 'code commande EC'
      - 'commande dont la réponse est ED', 'commande source de ED'
      - Code seul entouré de guillemets/apostrophes : 'ED', "EC"
    Puis fallback sur les tokens 2 lettres hors stopwords.
    """
    if not query:
        return []

    found = []
    # Patterns prioritaires : formulations explicites fr/en
    patterns = [
        # 'code de réponse XX', 'code reponse XX', 'réponse XX', 'reponse XX'
        r'(?:code\s+de\s+réponse|code\s+de\s+reponse|code\s+reponse|code\s+réponse)\s*(?:est|=|:\s*)?\s*[\'"]?([A-Za-z]{2})[\'"]?',
        # 'réponse (est|:) XX' ou 'réponse XX' standalone
        r'\bréponse\s+(?:est\s+|:\s*)?[\'"]?([A-Za-z]{2})[\'"]?(?:\b|\d)',
        r'\breponse\s+(?:est\s+|:\s*)?[\'"]?([A-Za-z]{2})[\'"]?(?:\b|\d)',
        # 'commande dont la réponse est XX'
        r'commande\s+(?:dont\s+la\s+réponse|dont\s+le\s+code\s+de\s+réponse|source\s+(?:du|de)\s+(?:code|la réponse))\s+(?:est\s+)?[\'"]?([A-Za-z]{2})[\'"]?',
        # 'commande XX', 'la commande XX', 'code commande XX', 'command XX'
        r'(?:code\s+)?(?:commande|command|cmd)\s*(?:est|=|:\s*)?\s*[\'"]?([A-Za-z]{2})[\'"]?',
        # 'code XX' générique
        r'\bcode\s*[:\s]?[\'"]([A-Za-z]{2})[\'"]',
        # Code en guillemets seul : 'ED' ou "EC"
        r'[\'"]([A-Za-z]{2})[\'"]',
        # XX est le code / XX est la commande / XX est la réponse
        r'\b([A-Za-z]{2})\s*(?:est\s+le\s+code|est\s+la\s+commande|est\s+le\s+code\s+de\s+réponse|est\s+la\s+réponse)\b',
    ]
    for pat in patterns:
        for m in re.findall(pat, query, re.IGNORECASE):
            code = m.upper()
            if code not in found:
                found.append(code)

    stopwords = {
        "ET", "OU", "DE", "LE", "LA", "DU", "AU", "UN", "EN", "SI", "NO", 
        "CE", "CI", "SA", "SES", "SON", "EST", "PAS", "QUE", "QUI", "PAR", 
        "SUR", "DES", "NE", "ON", "IL", "SE", "MA", "TA", "TE", "ME"
    }

    all_2letter = re.findall(r"\b[A-Z]{2}\b", query.upper())
    for token in all_2letter:
        if token not in stopwords and token not in found:
            found.append(token)

    return found


def _load_command_response_map() -> dict:
    """Charge le mapping command_code -> response_code depuis backend/app/data/command_response_map.json."""
    map_path = Path(__file__).resolve().parents[1] / "data" / "command_response_map.json"
    if map_path.exists():
        try:
            import json
            with open(map_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Impossible de charger command_response_map.json: {e}")
    return {"EC": "ED"}


def query_command_code(command_code: str, session_id: str = None, file_hash: str = None, limit: int = 8) -> list:
    """
    Effectue une recherche EXACTE et BIDIRECTIONNELLE sur les métadonnées command_code / response_code,
    en résolvant command_code <-> response_code via le mapping JSON.
    Retourne les objets langchain Document correspondants.

    Logique de résolution :
      - Si command_code est une CLÉ du mapping (ex: EC) : target_cmd=EC, target_resp=ED
      - Si command_code est une VALEUR du mapping (ex: ED) : target_cmd=EC, target_resp=ED
      - Sinon : cherche directement dans les deux colonnes command_code ET response_code
    La requête SQL filtre simultanément sur command_code ET response_code sans présupposer
    lequel des deux correspond.
    """
    if not command_code:
        return []

    cmd_clean = command_code.strip().upper()
    cmd_map = _load_command_response_map()
    inv_map = {v: k for k, v in cmd_map.items()}

    # Résolution bidirectionnelle
    if cmd_clean in cmd_map:
        target_cmd_code = cmd_clean
        target_resp_code = cmd_map[cmd_clean]
        print(f"[QUERY_COMMAND_CODE] '{cmd_clean}' détecté comme command_code → réponse attendue: '{target_resp_code}'")
    elif cmd_clean in inv_map:
        target_cmd_code = inv_map[cmd_clean]
        target_resp_code = cmd_clean
        print(f"[QUERY_COMMAND_CODE] '{cmd_clean}' détecté comme response_code → commande source: '{target_cmd_code}'")
    else:
        target_cmd_code = cmd_clean
        target_resp_code = cmd_clean
        print(f"[QUERY_COMMAND_CODE] '{cmd_clean}' non trouvé dans le mapping — recherche directe sur command_code ET response_code")

    try:
        from sqlalchemy import create_engine, text
        from langchain_core.documents import Document
        import json

        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            sql_query = text(
                "SELECT document, cmetadata FROM langchain_pg_embedding "
                "WHERE (cmetadata->>'response_code' = :resp_code OR cmetadata->>'command_code' = :cmd_code "
                "       OR cmetadata->>'response_code' = :cmd_code OR cmetadata->>'command_code' = :resp_code "
                "       OR cmetadata->>'contains_error_table' = 'true' "
                "       OR document ILIKE :pat_table "
                "       OR (document ILIKE :pat_cmd AND document ILIKE :pat_resp) "
                "       OR document ILIKE :pat_single) "
                "AND (:session_id IS NULL OR cmetadata->>'session_id' = :session_id OR cmetadata->>'file_hash' = :file_hash) "
                "ORDER BY "
                "  CASE WHEN cmetadata->>'response_code' = :resp_code OR cmetadata->>'command_code' = :cmd_code "
                "            OR cmetadata->>'response_code' = :cmd_code OR cmetadata->>'command_code' = :resp_code THEN 1 "
                "       WHEN cmetadata->>'contains_error_table' = 'true' OR document ILIKE '%PVK parity error%' THEN 2 "
                "       ELSE 3 END "
                "LIMIT :limit"
            )
            params = {
                "resp_code": target_resp_code,
                "cmd_code": target_cmd_code,
                "pat_table": "%PVK parity error%",
                "pat_cmd": f"%{target_cmd_code}%",
                "pat_resp": f"%{target_resp_code}%",
                "pat_single": f"%{cmd_clean}%",
                "session_id": session_id,
                "file_hash": file_hash,
                "limit": limit
            }

            results = conn.execute(sql_query, params).fetchall()

            if not results:
                fallback_query = text(
                    "SELECT document, cmetadata FROM langchain_pg_embedding "
                    "WHERE (document ILIKE :pat1 OR document ILIKE :pat2) "
                    "AND (:session_id IS NULL OR cmetadata->>'session_id' = :session_id OR cmetadata->>'file_hash' = :file_hash) "
                    "LIMIT :limit"
                )
                fb_params = {
                    "pat1": f"%{target_cmd_code}%",
                    "pat2": f"%{target_resp_code}%",
                    "session_id": session_id,
                    "file_hash": file_hash,
                    "limit": limit
                }
                results = conn.execute(fallback_query, fb_params).fetchall()

            documents = []
            for row in results:
                doc_text, meta = row[0], row[1]
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                meta = meta or {}

                # Injection de la correspondance dans les métadonnées et en-tête du document
                meta["command_code"] = target_cmd_code
                meta["response_code"] = target_resp_code

                annotated_text = doc_text
                if target_cmd_code != target_resp_code and f"Code Commande: {target_cmd_code}" not in doc_text:
                    annotation = (
                        f"[CORRESPONDANCE RAG : Code Réponse '{target_resp_code}' <-> Code Commande Source '{target_cmd_code}']\n"
                        f"[Le code de réponse '{target_resp_code}' est généré par la commande '{target_cmd_code}']\n"
                    )
                    annotated_text = annotation + doc_text

                documents.append(Document(page_content=annotated_text, metadata=meta))
            print(f"[QUERY_COMMAND_CODE] {len(documents)} document(s) trouvé(s) pour cmd='{target_cmd_code}' / resp='{target_resp_code}'")
            return documents
    except Exception as e:
        print(f"[WARN] query_command_code failed for command '{command_code}': {e}")
        return []


def purge_old_session_chunks(days: int = 7) -> int:
    """
    Purge les chunks de session dont la métadonnée last_accessed ou created_at est plus ancienne que `days` jours.
    """
    try:
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import create_engine, text
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            res = conn.execute(
                text(
                    "DELETE FROM langchain_pg_embedding "
                    "WHERE (cmetadata->>'last_accessed' IS NOT NULL AND cmetadata->>'last_accessed' < :cutoff) "
                    "   OR (cmetadata->>'created_at' IS NOT NULL AND cmetadata->>'created_at' < :cutoff)"
                ),
                {"cutoff": cutoff}
            )
            conn.commit()
            deleted_count = res.rowcount
            print(f"[PURGE] {deleted_count} chunks de plus de {days} jours supprimés de pgvector.")
            return deleted_count
    except Exception as e:
        print(f"[WARN] purge_old_session_chunks failed: {e}")
        return 0


def purge_chunks_by_file_hash(file_hash: str) -> int:
    """Purge tous les chunks correspondant à un file_hash donné."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            res = conn.execute(
                text("DELETE FROM langchain_pg_embedding WHERE cmetadata->>'file_hash' = :file_hash"),
                {"file_hash": file_hash}
            )
            conn.commit()
            deleted = res.rowcount
            print(f"[PURGE] {deleted} chunks supprimés pour file_hash '{file_hash[:10]}...'.")
            return deleted
    except Exception as e:
        print(f"[WARN] purge_chunks_by_file_hash failed: {e}")
        return 0


def purge_chunks_by_session_id(session_id: str) -> int:
    """Purge tous les chunks correspondant à un session_id donné."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            res = conn.execute(
                text("DELETE FROM langchain_pg_embedding WHERE cmetadata->>'session_id' = :session_id"),
                {"session_id": session_id}
            )
            conn.commit()
            deleted = res.rowcount
            print(f"[PURGE] {deleted} chunks supprimés pour session_id '{session_id}'.")
            return deleted
    except Exception as e:
        print(f"[WARN] purge_chunks_by_session_id failed: {e}")
        return 0


FIELD_NUMBER_RE = re.compile(
    r"(?:field|champ|fld)\s*0*(\d+)",
    re.IGNORECASE,
)


def _query_field_definition_by_number(field_number: str) -> dict | None:
    """
    Recherche EXACTE par numéro de champ (metadata field_number) dans la
    collection hps_specifications, via requête SQL directe.
    """
    try:
        from sqlalchemy import create_engine, text
        import json

        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT document, cmetadata FROM langchain_pg_embedding "
                    "WHERE cmetadata->>'type' = 'field_definition' "
                    "AND cmetadata->>'field_number' = :field_number "
                    "LIMIT 1"
                ),
                {"field_number": field_number},
            ).fetchone()

        if not row:
            return None

        content, meta = row[0], row[1]
        if isinstance(meta, str):
            meta = json.loads(meta)

        return {
            "field_number": meta.get("field_number"),
            "field_name": meta.get("field_name"),
            "attributes": meta.get("attributes", ""),
            "source_file": meta.get("source_file"),
            "full_content": content,
        }
    except Exception as e:
        print(f"⚠️ Recherche exacte par field_number échouée pour '{field_number}' : {e}")
        return None


def query_field_definition(field_name: str, k: int = 1) -> dict | None:
    """
    Recherche la définition d'un champ (chapitre 4 du PDF) : priorité à une
    correspondance EXACTE sur le numéro de champ si la requête en contient
    un (ex: "Field 37"), sinon recherche sémantique filtrée sur
    type=field_definition (ex: "PAN" -> Field 2-Primary Account Number).
    """
    number_match = FIELD_NUMBER_RE.search(field_name)
    if number_match:
        exact_result = _query_field_definition_by_number(number_match.group(1))
        if exact_result:
            return exact_result

    try:
        db = get_vectorstore()
        docs = db.similarity_search(
            field_name,
            k=k,
            filter={"type": "field_definition"},
        )
    except Exception as e:
        print(f"⚠️ Recherche sémantique de définition de champ échouée pour '{field_name}' : {e}")
        return None

    if not docs:
        return None

    doc = docs[0]
    return {
        "field_number": doc.metadata.get("field_number"),
        "field_name": doc.metadata.get("field_name"),
        "attributes": doc.metadata.get("attributes", ""),
        "source_file": doc.metadata.get("source_file"),
        "full_content": doc.page_content,
    }