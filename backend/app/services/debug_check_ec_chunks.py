# backend/app/services/debug_check_ec_chunks.py
# ATTENTION : ce script fait un SEUL appel d'embedding Gemini à l'exécution. Ne jamais boucler similarity_search() sur plusieurs documents ici — cela épuise le quota API en quelques secondes.

import json
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Chargement du .env et réutilisation de CONNECTION_STRING et get_session_vectorstore
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

from app.rag.retriever import CONNECTION_STRING, get_session_vectorstore


def debug_check_ec_chunks():
    print("=== Diagnostic RAG - Recherche SQL directe des chunks EC/ED ===")
    
    # 1. Le script fait UNE SEULE requête SQL (déjà fait, garder tel quel)
    engine = create_engine(CONNECTION_STRING)
    query = text(
        "SELECT document, cmetadata "
        "FROM langchain_pg_embedding "
        "WHERE document ILIKE '%PVK parity error%' "
        "   OR document ILIKE '%PIN Block format has been disabled%' "
        "   OR document ILIKE '%ZPK parity error%'"
    )
    
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()
        
    if not rows:
        print("AUCUN CHUNK NE CONTIENT LA TABLE D'ERREUR EC/ED EN BASE — problème d'extraction/chunking à l'ingestion.")
        return

    print(f"\n[OK] {len(rows)} chunk(s) trouvé(s) en base par SQL.")
    
    # 3. Filtrer les résultats SQL pour ne garder QUE la ligne où metadata->>'page' contient '276'
    target_row = None
    target_meta = {}
    target_doc = ""

    for row in rows:
        document, meta_raw = row[0], row[1]
        meta = meta_raw
        if isinstance(meta_raw, str):
            try:
                meta = json.loads(meta_raw)
            except Exception:
                meta = {}
        meta = meta or {}
        
        page_val = str(meta.get("page", ""))
        if "276" in page_val:
            target_row = row
            target_meta = meta
            target_doc = document
            break

    if not target_row:
        print("AUCUN CHUNK DE LA PAGE 276 TROUVÉ PARMI LES RÉSULTATS SQL.")
        return

    session_id = target_meta.get("session_id", "N/A")
    file_hash = target_meta.get("file_hash", "N/A")
    page = target_meta.get("page", "N/A")
    
    print(f"\n--- Chunk Cible (Page {page}) ---")
    print(f"  - Session ID  : {session_id}")
    print(f"  - File Hash   : {file_hash}")
    print(f"  - Longueur    : {len(target_doc)} caracteres")

    # 2. Le script ne doit faire QU'UN SEUL appel similarity_search() au total dans toute son exécution
    session_db = None
    try:
        session_db = get_session_vectorstore()
    except Exception as err:
        print(f"[WARN] Impossible d'initialiser get_session_vectorstore(): {err}")
        return

    filter_dict = {}
    if file_hash != "N/A":
        filter_dict["file_hash"] = file_hash
    elif session_id != "N/A":
        filter_dict["session_id"] = session_id

    # 3. Unique appel similarity_search
    try:
        top_docs = session_db.similarity_search(
            "codes d'erreur commande EC",
            k=8,
            filter=filter_dict if filter_dict else None
        )
        
        # 4. Afficher : le rang de ce chunk dans les 8 résultats, ou "ABSENT DU TOP 8" s'il n'y est pas
        rank = None
        for i, doc in enumerate(top_docs, 1):
            if doc.page_content == target_doc or (target_doc and target_doc[:100] in doc.page_content):
                rank = i
                break

        if rank is not None:
            print(f"\nRESULTAT : RETROUVÉ dans le Top 8 (Rang #{rank})")
        else:
            print("\nRESULTAT : ABSENT DU TOP 8")
    except Exception as e:
        print(f"\nErreur lors de similarity_search: {e}")


if __name__ == "__main__":
    debug_check_ec_chunks()
    

