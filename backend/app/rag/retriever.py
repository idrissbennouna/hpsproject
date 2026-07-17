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
    return _session_vectorstore_instance

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
        print(f"🗑️ Documents de la session '{session_id}' supprimés de pgvector.")
    except Exception as e:
        print(f"⚠️ Impossible de supprimer les documents de session dans pgvector : {e}")


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
