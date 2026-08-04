# backend/app/services/debug_check_response_code.py
"""
Script de diagnostic : vérifie si la metadata 'response_code' a bien
été extraite et stockée pour le chunk de la page 276 (table d'erreur
de la commande EC / réponse ED).

ATTENTION : ce script ne fait AUCUN appel d'embedding Gemini (uniquement
du SQL brut) — il peut être exécuté autant de fois que nécessaire sans
risque d'épuiser le quota API.
"""
from dotenv import load_dotenv
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

from app.rag.retriever import CONNECTION_STRING

def main():
    from sqlalchemy import create_engine, text

    engine = create_engine(CONNECTION_STRING)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cmetadata->>'response_code' AS response_code, "
                "cmetadata->>'page' AS page, "
                "LEFT(document, 150) AS preview "
                "FROM langchain_pg_embedding "
                "WHERE cmetadata->>'page' LIKE '%276%'"
            )
        ).fetchall()

    print(f"=== {len(rows)} ligne(s) trouvée(s) pour la page 276 ===\n")
    if not rows:
        print("AUCUNE LIGNE TROUVÉE — le PDF n'a peut-être pas été ré-uploadé "
              "depuis le dernier correctif, ou le chunking a changé les numéros de page.")
        return

    for i, row in enumerate(rows, 1):
        print(f"--- Ligne {i} ---")
        print(f"  response_code : {row.response_code!r}")
        print(f"  page          : {row.page}")
        print(f"  preview       : {row.preview}")
        print()

if __name__ == "__main__":
    main()