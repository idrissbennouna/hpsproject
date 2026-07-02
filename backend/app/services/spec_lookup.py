# app/services/spec_lookup.py
import openpyxl
from pathlib import Path

_SPEC_CACHE = None

def load_spec(excel_path: str = None) -> dict:
    """Charge Spec_PowerCARD.xlsx une seule fois et l'indexe par nom de fonction."""
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE

    if excel_path is None:
        current_dir = Path(__file__).resolve().parent
        excel_path = current_dir.parent / "storage" / "Spec_PowerCARD.xlsx"

    wb = openpyxl.load_workbook(str(excel_path), data_only=True)
    ws = wb["Lib"]
    spec = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        func_name, source, path, description, exception = row[:5]
        if func_name:
            key = func_name.strip()
            spec[key] = {
                "source": source,
                "path": path,
                "description": description or "",
                "conditions": exception or "",
            }
    _SPEC_CACHE = spec
    return spec


def find_relevant_specs(alerts_text: str) -> str:
    """
    Cherche dans le texte des alertes les noms de fonctions connus de la spec
    et retourne un bloc de contexte formaté à injecter dans le prompt du LLM.
    Retourne une chaîne vide si aucune fonction connue n'est trouvée.
    """
    spec = load_spec()
    matched_blocks = []

    for func_name, details in spec.items():
        # Recherche insensible à la casse, tolère les espaces parasites
        if func_name.strip().lower() in alerts_text.lower():
            block = (
                f"### Fonction : {func_name.strip()} (source: {details['source']}, {details['path']})\n"
                f"Description : {details['description']}\n"
                f"Conditions documentées :\n{details['conditions']}\n"
            )
            matched_blocks.append(block)

    if not matched_blocks:
        return ""

    return "\n---\n".join(matched_blocks)