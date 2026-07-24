# backend/app/services/debug_ingest_small.py
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.vectorstores import PGVector
from app.rag.loaders import load_excel_specs, load_pdf_field_sections
from app.rag.retriever import get_embeddings, CONNECTION_STRING, COLLECTION_NAME

load_dotenv()

LIMIT_PDF_DOCS = 5  # limite temporaire pour ne pas griller le quota Gemini pendant les tests

def main():
    storage_dir = Path(__file__).resolve().parent.parent / "storage"

    excel_docs = load_excel_specs(storage_dir / "Spec_PowerCARD.xlsx")
    pdf_docs_all = load_pdf_field_sections(storage_dir / "vip-system-BASE-i-tech-specs-volume-1.pdf")
    pdf_docs_small = pdf_docs_all[:LIMIT_PDF_DOCS]

    documents = excel_docs + pdf_docs_small
    print(
        f"🧪 Test avec {len(excel_docs)} fonctions Excel + "
        f"{len(pdf_docs_small)} champs PDF (sur {len(pdf_docs_all)} extraits au total)"
    )

    embeddings = get_embeddings()
    db = PGVector.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        connection_string=CONNECTION_STRING,
        pre_delete_collection=True,
    )
    print(f"✅ Test d'ingestion réussi : {len(documents)} documents indexés dans pgvector.")

if __name__ == "__main__":
    main()