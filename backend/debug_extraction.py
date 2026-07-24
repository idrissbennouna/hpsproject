# debug_extraction.py — à lancer depuis backend/ avec : python -m debug_extraction
from pathlib import Path
from app.rag.loaders import load_pdf_field_sections

docs = load_pdf_field_sections(Path("app/storage/vip-system-BASE-i-tech-specs-volume-1.pdf"))

# Affiche 3 champs au hasard pour vérifier à l'œil
for doc in docs[:3]:
    print("=" * 60)
    print(doc.metadata)
    print("-" * 60)
    print(doc.page_content[:500])
    print()