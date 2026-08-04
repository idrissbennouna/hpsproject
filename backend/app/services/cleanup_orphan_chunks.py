# backend/app/services/cleanup_orphan_chunks.py
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

from app.rag.retriever import CONNECTION_STRING


def cleanup_orphan_chunks(confirm_delete: bool = False):
    print("=== Nettoyage des Chunks Orphelins (file_hash IS NULL) ===")
    
    engine = create_engine(CONNECTION_STRING)
    
    # Sélection des chunks avec cmetadata->>'file_hash' IS NULL
    query_select = text(
        "SELECT document, cmetadata "
        "FROM langchain_pg_embedding "
        "WHERE cmetadata->>'file_hash' IS NULL OR cmetadata->>'file_hash' = 'N/A'"
    )
    
    with engine.connect() as conn:
        rows = conn.execute(query_select).fetchall()
        
    print(f"\n[ORPHANS DETECTED] Total de chunks orphelins trouvés : {len(rows)}\n")
    
    if not rows:
        print("Aucun chunk orphelin à traiter.")
        return

    for idx, row in enumerate(rows, 1):
        doc, meta_raw = row[0], row[1]
        meta = meta_raw
        if isinstance(meta_raw, str):
            try:
                meta = json.loads(meta_raw)
            except Exception:
                meta = {}
        meta = meta or {}
        
        session_id = meta.get("session_id", "N/A")
        page = meta.get("page", "N/A")
        doc_len = len(doc) if doc else 0
        snippet = doc[:100].replace("\n", " ").encode("ascii", "replace").decode("ascii") if doc else ""
        
        print(f"[{idx}/{len(rows)}]")
        print(f"  - Session ID : {session_id}")
        print(f"  - Page       : {page}")
        print(f"  - Longueur   : {doc_len} caracteres")
        print(f"  - Snippet    : {snippet}...")
        print()

    if confirm_delete:
        query_delete = text(
            "DELETE FROM langchain_pg_embedding "
            "WHERE cmetadata->>'file_hash' IS NULL OR cmetadata->>'file_hash' = 'N/A'"
        )
        with engine.begin() as conn:
            result = conn.execute(query_delete)
            deleted_count = result.rowcount
        print(f"[ACTION] {deleted_count} chunk(s) orphelin(s) supprimé(s) avec succès de pgvector.")
    else:
        print("[DRY-RUN] Aucun chunk n'a été supprimé. Pour exécuter la suppression, relancez avec --confirm-delete.")


if __name__ == "__main__":
    confirm = "--confirm-delete" in sys.argv
    cleanup_orphan_chunks(confirm_delete=confirm)
