"""
Chargement DYNAMIQUE de la spécification métier PowerCARD (Spec_PowerCARD.xlsx).

Ce module remplace toute liste ou tout texte "en dur" concernant les fonctions
métier (CardInSaf, GetOriginalAuthData, CheckLimits, ...) par une lecture directe
du fichier Excel de spécification fourni par l'équipe HPS.

Tant que la base pgvector (RAG de YZ) n'est pas branchée, ce module sert de
"source de vérité" locale pour :
  - la liste des fonctions métier à surveiller dans les traces (plus besoin de
    les recopier à la main dans log_parser.py et agent_graph.py)
  - le texte de spécification (description + codes retour) à injecter dans le
    contexte du LLM, à la place des chaînes de texte écrites manuellement
"""

import os
import functools
import openpyxl


DEFAULT_SPEC_PATH = os.getenv(
    "POWERCARD_SPEC_PATH",
    os.path.join("app", "storage", "Spec_PowerCARD.xlsx"),
)


@functools.lru_cache(maxsize=4)
def load_function_specs(spec_path: str = None) -> dict:
    """
    Lit la feuille 'Lib' du fichier Excel de spécification et retourne :
        { "NomFonction": {"source", "path", "description", "exception"} }

    Résultat mis en cache (le fichier de spec ne change pas en cours d'exécution).
    Utiliser load_function_specs.cache_clear() si le fichier est modifié à chaud.
    """
    path = spec_path or DEFAULT_SPEC_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Fichier de spécification introuvable : '{path}'. "
            "Définis la variable d'environnement POWERCARD_SPEC_PATH si besoin."
        )

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Lib"]

    specs = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        padded = list(row) + [None] * 5
        func_name, source, rel_path, description, exception = padded[:5]

        if not func_name:
            continue

        clean_name = str(func_name).strip()
        specs[clean_name] = {
            "source": str(source).strip() if source else "",
            "path": str(rel_path).strip() if rel_path else "",
            "description": str(description).strip() if description else "",
            "exception": str(exception).strip() if exception else "",
        }

    return specs


def get_monitored_function_names(spec_path: str = None) -> list:
    """Liste des fonctions métier à surveiller, dérivée dynamiquement du fichier de spec."""
    return list(load_function_specs(spec_path).keys())


def get_spec_context_for_functions(func_names, spec_path: str = None) -> str:
    """
    Construit un texte de contexte à partir des vraies entrées de spec pour
    les fonctions données. Sert de RAG local en attendant la vraie base
    pgvector de YZ.
    """
    specs = load_function_specs(spec_path)
    blocks = []
    for name in func_names:
        entry = specs.get(name)
        if not entry:
            continue
        blocks.append(
            f"### Fonction {name} (source: {entry['source']}, path: {entry['path']})\n"
            f"Description : {entry['description']}\n"
            f"Codes retour / Exceptions :\n{entry['exception']}"
        )
    return "\n\n".join(blocks)