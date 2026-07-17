# backend/app/services/ingest_docs.py
import sys
import os
from pathlib import Path

print("🔄 Démarrage du script d'ingestion (version refactorisée)...")

try:
    from dotenv import load_dotenv
    from langchain_community.vectorstores import PGVector
    from app.rag.loaders import load_all_docs
    from app.rag.retriever import get_embeddings, CONNECTION_STRING, COLLECTION_NAME
    print("✅ Tous les modules requis ont été importés avec succès.")
except ImportError as e:
    print(f"❌ Erreur d'importation : {e}")
    sys.exit(1)

load_dotenv()

def initialiser_et_ingerer():
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Erreur : La variable d'environnement GOOGLE_API_KEY / GEMINI_API_KEY est introuvable.")
        return

    try:
        embeddings = get_embeddings()

        current_dir = Path(__file__).resolve().parent
        # Dans la structure du projet, app/storage est au niveau backend/app/storage, c'est-à-dire :
        # current_dir est backend/app/services. Le dossier storage est backend/app/storage.
        # Donc parent / "storage"
        storage_dir = current_dir.parent / "storage"

        print(f"📂 Recherche des documents dans le dossier de stockage : {storage_dir}")
        documents_specs = load_all_docs(storage_dir)

        if not documents_specs:
            print("❌ Aucun document réel à ingérer. Arrêt.")
            return

        print("📥 Connexion à PostgreSQL et initialisation de pgvector...")

        db = PGVector.from_documents(
            documents=documents_specs,
            embedding=embeddings,
            collection_name=COLLECTION_NAME,
            connection_string=CONNECTION_STRING,
            pre_delete_collection=True
        )

        print(f"✅ Base de données PostgreSQL initialisée avec succès : {len(documents_specs)} spécifications réelles indexées !")

    except Exception as e:
        print(f"❌ Une erreur est survenue lors de l'initialisation de la DB : {e}")

if __name__ == "__main__":
    initialiser_et_ingerer()