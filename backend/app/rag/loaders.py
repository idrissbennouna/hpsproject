# backend/app/rag/loaders.py
import os
from pathlib import Path
from langchain_core.documents import Document
import openpyxl

def load_excel_specs(excel_path: Path) -> list[Document]:
    """
    Convertit chaque fonction documentée de Spec_PowerCARD.xlsx en Document réel.
    Cette fonction est extraite de ingest_docs.py pour être partagée.
    """
    excel_path = Path(excel_path)
    if not excel_path.exists():
        print(f"⚠️ Fichier Excel introuvable : {excel_path} — ignoré.")
        return []

    wb = openpyxl.load_workbook(str(excel_path), data_only=True)
    if "Lib" in wb.sheetnames:
        ws = wb["Lib"]
    else:
        ws = wb[wb.sheetnames[0]]
        print(f"⚠️ Onglet 'Lib' introuvable dans {excel_path.name}, utilisation du premier onglet '{ws.title}' à la place.")

    documents = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        func_name, source, path, description, exception = row[:5]
        if func_name:
            content = (
                f"Fonction {func_name.strip()} (module {source}, fichier {path})\n"
                f"Description : {description}\n"
                f"Conditions : {exception}"
            )
            documents.append(Document(
                page_content=content,
                metadata={
                    "source_file": "Spec_PowerCARD.xlsx", 
                    "function": func_name.strip(),
                    "module": str(source).strip() if source else "",
                    "file_path": str(path).strip() if path else ""
                }
            ))
    print(f"📊 {len(documents)} fonctions extraites de Spec_PowerCARD.xlsx.")
    return documents

def load_pdf_field_sections(pdf_path: Path) -> list[Document]:
    """
    TODO: Découper les PDF de specs par section de champ numérotée type
    '4.105 Field 110—...'.
    Retourne une liste vide pour le moment.
    """
    # STUB pour l'instant
    print(f"📝 STUB load_pdf_field_sections appelé pour {pdf_path}. Non implémenté.")
    return []

def load_all_docs(storage_dir: Path) -> list[Document]:
    """
    Parcourt le dossier de stockage et charge tous les documents supportés.
    """
    storage_dir = Path(storage_dir)
    documents = []
    
    # Ingestion Excel
    excel_path = storage_dir / "Spec_PowerCARD.xlsx"
    if excel_path.exists():
        documents.extend(load_excel_specs(excel_path))
    else:
        print(f"⚠️ Fichier Spec_PowerCARD.xlsx introuvable dans {storage_dir}")
        
    # Ingestion PDF (Stub)
    for file_path in storage_dir.glob("*.pdf"):
        documents.extend(load_pdf_field_sections(file_path))
        
    return documents
