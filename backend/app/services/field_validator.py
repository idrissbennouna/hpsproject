# backend/app/services/field_validator.py
import re
import time

from app.rag.retriever import search_session_chunks_keyword


FIELDS_EXCLUDED_FROM_STRICT_N = {"52"}
# Extrait "<longueur> <type>" depuis le texte Attributes du chapitre 4
# ex: "19 N, 4-bit BCD..." -> longueur=19, type=N ; "40 ANS" -> longueur=40, type=ANS
ATTR_TYPE_RE = re.compile(r"(\d+)\s+([ANS]{1,3})\b")


def _parse_expected_type(attributes: str) -> dict | None:
    """Extrait le type attendu (N/A/S/combinaisons) et la longueur max du texte Attributes."""
    if not attributes:
        return None
    match = ATTR_TYPE_RE.search(attributes)
    if not match:
        return None
    length_str, type_code = match.groups()
    if not type_code:
        return None
    return {"max_length": int(length_str), "type_code": type_code}


def _value_matches_type(value: str, type_code: str) -> bool:
    """
    Vérifie si la valeur respecte le type attendu. Les '*' (masquage PAN
    habituel dans les traces) sont retirés avant vérification, jamais
    considérés comme une erreur de format.
    """
    cleaned = value.replace("*", "")
    if not cleaned:
        return True  # valeur entièrement masquée -> rien à valider

    if type_code == "N":
        return cleaned.isdigit()
    if type_code == "A":
        return cleaned.isalpha()
    return True  # ANS/AN/NS... -> pas de règle stricte pour l'instant


def validate_transaction_fields(all_fields: dict, session_id: str = None) -> list:
    """
    Pour chaque champ extrait d'une transaction, interroge EXCLUSIVEMENT le document de session
    (si session_id est fourni). Si AUCUN session_id n'est fourni, retourne une liste vide sans
    effectuer d'appel RAG ou vectoriel.
    
    Les recherches de champs sont dédoublonnées et mises en cache localement par numéro de champ.
    """
    if not session_id or not session_id.strip():
        return []

    alerts = []
    
    # 1. Collecter et dédoublonner tous les numéros de champs à valider
    unique_field_numbers = list(all_fields.keys())
    definitions_cache = {}

    # 2. Effectuer des recherches dédoublonnées sur le store de session
    for idx, field_number in enumerate(unique_field_numbers):
        session_docs = search_session_chunks_keyword(session_id, f"Field {field_number}", limit=1)
        if session_docs:
            definitions_cache[field_number] = {
                "field_number": field_number,
                "field_name": session_docs[0].metadata.get("field_name", f"Field {field_number}"),
                "attributes": session_docs[0].metadata.get("attributes", ""),
                "source_file": session_docs[0].metadata.get("source_file", "document de session"),
            }
        else:
            definitions_cache[field_number] = None

        # Pause de sécurité anti-rate-limit si beaucoup de champs uniques (>10)
        if len(unique_field_numbers) > 10 and (idx + 1) % 10 == 0:
            time.sleep(0.1)

    # 3. Valider chaque champ à partir du cache dédoublonné
    for field_number, field_data in all_fields.items():
        value = field_data.get("value", "")
        definition = definitions_cache.get(field_number)

        if definition is None:
            continue

        expected = _parse_expected_type(definition.get("attributes", ""))
        if expected is None:
            continue

        if expected["type_code"] == "N" and field_number.lstrip("0") in FIELDS_EXCLUDED_FROM_STRICT_N:
            continue  # champ connu pour être hexadécimal malgré son type déclaré "N"

        if not _value_matches_type(value, expected["type_code"]):
            alerts.append({
                "field_number": field_number,
                "field_name": definition.get("field_name", f"Field {field_number}"),
                "value": value,
                "expected_type": expected["type_code"],
                "source_file": definition.get("source_file", "documentation"),
                "message": (
                    f"Field {field_number} ({definition.get('field_name', '')}) : valeur '{value}' "
                    f"ne respecte pas le type attendu '{expected['type_code']}' "
                    f"selon {definition.get('source_file', 'la documentation')}."
                ),
            })

    return alerts