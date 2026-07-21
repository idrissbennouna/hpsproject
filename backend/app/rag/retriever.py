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
    """Crée un index sur la colonne cmetadata->>'session_id' si la table existe."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_langchain_pg_embedding_session_id ON langchain_pg_embedding ((cmetadata->>'session_id'))")
            )
            conn.commit()
        print("[INDEX] Index idx_langchain_pg_embedding_session_id verifie / cree avec succes.")
    except Exception as e:
        print(f"[WARN] Remarque indexation pgvector (optionnelle si table non creee) : {e}")

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

def search_session_chunks_keyword(session_id: str, keyword: str, limit: int = 5) -> list:
    """Effectue une recherche textuelle directe ILIKE dans langchain_pg_embedding filtrée par session_id."""
    try:
        from sqlalchemy import create_engine, text
        from langchain_core.documents import Document
        engine = create_engine(CONNECTION_STRING)
        with engine.connect() as conn:
            query = text(
                "SELECT document, cmetadata FROM langchain_pg_embedding "
                "WHERE cmetadata->>'session_id' = :session_id "
                "AND document ILIKE :pattern "
                "LIMIT :limit"
            )
            results = conn.execute(query, {
                "session_id": session_id,
                "pattern": f"%{keyword}%",
                "limit": limit
            }).fetchall()
            
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
    pass

def _is_rate_limit_error(exception: Exception) -> bool:
    """Détermine si l'erreur est un 429 RESOURCE_EXHAUSTED / Rate Limit."""
    err_str = str(exception).lower()
    return "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str or "rate limit" in err_str

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
    Ingère les documents par lots (batches) dans le vectorstore avec retry/backoff exponentiel sur 429
    et affichage de la progression.
    """
    import time
    from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception
    from app.core.config import EMBEDDING_BATCH_SIZE, EMBEDDING_BATCH_DELAY_SECONDS

    if batch_size is None:
        batch_size = EMBEDDING_BATCH_SIZE
    if inter_batch_delay is None:
        inter_batch_delay = EMBEDDING_BATCH_DELAY_SECONDS

    total_chunks = len(documents)
    if total_chunks == 0:
        return 0

    print(f"[BATCH] Début de l'ingestion de {total_chunks} chunks par lots de {batch_size} (délai inter-lot: {inter_batch_delay}s)...")
    
    try:
        for i in range(0, total_chunks, batch_size):
            batch = documents[i:i + batch_size]
            
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
                            print(
                                f"[WARN] tentative {attempt.retry_state.attempt_number}/{max_retries} pour le lot "
                                f"{i//batch_size + 1}/{(total_chunks + batch_size - 1)//batch_size} suite à 429 / Rate Limit..."
                            )
                        vectorstore.add_documents(batch)
            except Exception as err:
                print(f"[ERROR] Échec critique lors de l'ingestion du lot {i}-{i+len(batch)} après retries: {err}")
                if _is_rate_limit_error(err):
                    raise QuotaExhaustedError(
                        "Le quota de l'API Gemini pour les embeddings a été atteint. "
                        "Réessayez plus tard ou contactez l'administrateur pour augmenter le quota (passage à un plan payant)."
                    ) from err
                raise err

            processed = min(i + batch_size, total_chunks)
            print(f"[PROGRESS] Embedded {processed}/{total_chunks} chunks dans pgvector.")
            
            if processed < total_chunks and inter_batch_delay > 0:
                time.sleep(inter_batch_delay)

        return total_chunks

    except Exception as e:
        if session_id:
            print(f"[CLEANUP] Suppression du state partiel de la session {session_id} suite à une erreur...")
            delete_session_documents(session_id)
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
