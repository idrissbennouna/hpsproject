# backend/app/services/debug_query_field.py
from app.rag.retriever import query_field_definition

print("=== Test recherche exacte (numéro de champ) ===")
print(query_field_definition("Field 2"))

print("\n=== Test recherche sémantique (nom sans numéro) ===")
print(query_field_definition("PAN"))