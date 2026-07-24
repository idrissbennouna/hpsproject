# backend/app/services/debug_check_fields.py
from app.rag.retriever import get_vectorstore

db = get_vectorstore()
docs = db.similarity_search("Field 2 Primary Account Number", k=1, filter={"type": "field_definition"})

for doc in docs:
    print(doc.metadata)
    print(doc.page_content[:800])