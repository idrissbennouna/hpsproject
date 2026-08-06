# backend/app/services/field_validator.py
import json
import re
import time
from pathlib import Path

from app.rag.retriever import search_session_chunks_keyword

FIELDS_EXCLUDED_FROM_STRICT_N = {"52"}
# Extrait "<longueur> <type>" depuis le texte Attributes du chapitre 4
# ex: "19 N, 4-bit BCD..." -> longueur=19, type=N ; "40 ANS" -> longueur=40, type=ANS
ATTR_TYPE_RE = re.compile(r"(\d+)\s+([ANS]{1,3})\b")

# ─── Chargement du référentiel ISO 8583 au niveau module ─────────────────────
# Ce référentiel fait AUTORITÉ sur tout document de session (PDF uploadé).
_ISO8583_REF_PATH = Path(__file__).resolve().parent.parent / "data" / "iso8583_field_reference.json"
_ISO8583_FIELDS_REF: dict = {}
try:
    if _ISO8583_REF_PATH.exists():
        with open(_ISO8583_REF_PATH, "r", encoding="utf-8") as _f:
            _ISO8583_FIELDS_REF = json.load(_f).get("fields", {})
except Exception as _e:
    print(f"Warning: Impossible de charger iso8583_field_reference.json dans field_validator: {_e}")

STANDARD_ISO_FIELDS = {
    "1": {"name": "Bitmap", "attributes": "16 AN", "source": "Standard ISO 8583"},
    "2": {"name": "Primary Account Number (PAN)", "attributes": "19 N", "source": "Standard ISO 8583"},
    "3": {"name": "Processing Code", "attributes": "6 N", "source": "Standard ISO 8583"},
    "4": {"name": "Amount, Transaction", "attributes": "12 N", "source": "Standard ISO 8583"},
    "5": {"name": "Amount, Settlement", "attributes": "12 N", "source": "Standard ISO 8583"},
    "6": {"name": "Amount, Cardholder Billing", "attributes": "12 N", "source": "Standard ISO 8583"},
    "7": {"name": "Transmission Date & Time", "attributes": "10 N", "source": "Standard ISO 8583"},
    "8": {"name": "Amount, Cardholder Billing Fee", "attributes": "8 N", "source": "Standard ISO 8583"},
    "9": {"name": "Conversion Rate, Settlement", "attributes": "8 N", "source": "Standard ISO 8583"},
    "10": {"name": "Conversion Rate, Cardholder Billing", "attributes": "8 N", "source": "Standard ISO 8583"},
    "11": {"name": "System Trace Audit Number (STAN)", "attributes": "6 N", "source": "Standard ISO 8583"},
    "12": {"name": "Time, Local Transaction", "attributes": "6 N", "source": "Standard ISO 8583"},
    "13": {"name": "Date, Local Transaction", "attributes": "4 N", "source": "Standard ISO 8583"},
    "14": {"name": "Expiration Date", "attributes": "4 N", "source": "Standard ISO 8583"},
    "15": {"name": "Date, Settlement", "attributes": "4 N", "source": "Standard ISO 8583"},
    "16": {"name": "Date, Conversion", "attributes": "4 N", "source": "Standard ISO 8583"},
    "17": {"name": "Date, Capture", "attributes": "4 N", "source": "Standard ISO 8583"},
    "18": {"name": "Merchant Category Code", "attributes": "4 N", "source": "Standard ISO 8583"},
    "19": {"name": "Acquiring Institution Country Code", "attributes": "3 N", "source": "Standard ISO 8583"},
    "20": {"name": "PAN Country Code", "attributes": "3 N", "source": "Standard ISO 8583"},
    "21": {"name": "Forwarding Institution Country Code", "attributes": "3 N", "source": "Standard ISO 8583"},
    "22": {"name": "Point of Service Entry Mode", "attributes": "3 N", "source": "Standard ISO 8583"},
    "23": {"name": "Card Sequence Number", "attributes": "3 N", "source": "Standard ISO 8583"},
    "24": {"name": "Function Code (NII)", "attributes": "3 N", "source": "Standard ISO 8583"},
    "25": {"name": "Point of Service Condition Code", "attributes": "2 N", "source": "Standard ISO 8583"},
    "26": {"name": "Point of Service Capture Code", "attributes": "2 N", "source": "Standard ISO 8583"},
    "27": {"name": "Authorizing Identification Response Length", "attributes": "1 N", "source": "Standard ISO 8583"},
    "28": {"name": "Amount, Transaction Fee", "attributes": "9 N", "source": "Standard ISO 8583"},
    "29": {"name": "Amount, Settlement Fee", "attributes": "9 N", "source": "Standard ISO 8583"},
    "30": {"name": "Amount, Transaction Processing Fee", "attributes": "9 N", "source": "Standard ISO 8583"},
    "31": {"name": "Amount, Settlement Processing Fee", "attributes": "9 N", "source": "Standard ISO 8583"},
    "32": {"name": "Acquiring Institution Identification Code", "attributes": "11 N", "source": "Standard ISO 8583"},
    "33": {"name": "Forwarding Institution Identification Code", "attributes": "11 N", "source": "Standard ISO 8583"},
    "34": {"name": "Primary Account Number, Extended", "attributes": "28 AN", "source": "Standard ISO 8583"},
    "35": {"name": "Track 2 Data", "attributes": "37 AN", "source": "Standard ISO 8583"},
    "36": {"name": "Track 3 Data", "attributes": "104 AN", "source": "Standard ISO 8583"},
    "37": {"name": "Retrieval Reference Number (RRN)", "attributes": "12 AN", "source": "Standard ISO 8583"},
    "38": {"name": "Authorization Identification Response (Auth Code)", "attributes": "6 AN", "source": "Standard ISO 8583"},
    "39": {"name": "Response Code", "attributes": "2 AN", "source": "Standard ISO 8583"},
    "40": {"name": "Service Restriction Code", "attributes": "3 N", "source": "Standard ISO 8583"},
    "41": {"name": "Card Acceptor Terminal Identification (TID)", "attributes": "8 AN", "source": "Standard ISO 8583"},
    "42": {"name": "Card Acceptor Identification Code (MID)", "attributes": "15 AN", "source": "Standard ISO 8583"},
    "43": {"name": "Card Acceptor Name/Location", "attributes": "40 AN", "source": "Standard ISO 8583"},
    "44": {"name": "Additional Response Data", "attributes": "25 AN", "source": "Standard ISO 8583"},
    "45": {"name": "Track 1 Data", "attributes": "76 AN", "source": "Standard ISO 8583"},
    "46": {"name": "Additional Data - ISO", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "47": {"name": "Additional Data - National", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "48": {"name": "Additional Data - Private", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "49": {"name": "Currency Code, Transaction", "attributes": "3 N", "source": "Standard ISO 8583"},
    "50": {"name": "Currency Code, Settlement", "attributes": "3 N", "source": "Standard ISO 8583"},
    "51": {"name": "Currency Code, Cardholder Billing", "attributes": "3 N", "source": "Standard ISO 8583"},
    "52": {"name": "PIN Data", "attributes": "16 AN", "source": "Standard ISO 8583"},
    "53": {"name": "Security Related Control Information", "attributes": "16 AN", "source": "Standard ISO 8583"},
    "54": {"name": "Additional Amounts", "attributes": "120 AN", "source": "Standard ISO 8583"},
    "55": {"name": "Integrated Circuit Card System Related Data", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "56": {"name": "Original Data Elements", "attributes": "35 N", "source": "Standard ISO 8583"},
    "57": {"name": "Authorization Life Cycle Code", "attributes": "3 N", "source": "Standard ISO 8583"},
    "58": {"name": "Authorizing Agent Institution Id Code", "attributes": "11 AN", "source": "Standard ISO 8583"},
    "59": {"name": "Echo Data", "attributes": "255 AN", "source": "Standard ISO 8583"},
    "60": {"name": "Private Data", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "61": {"name": "Private Data", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "62": {"name": "Private Data", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "63": {"name": "Private Data", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "64": {"name": "Message Authentication Code", "attributes": "8 AN", "source": "Standard ISO 8583"},
    "70": {"name": "Network Management Code", "attributes": "3 N", "source": "Standard ISO 8583"},
    "90": {"name": "Original Data Elements", "attributes": "42 N", "source": "Standard ISO 8583"},
    "102": {"name": "Account Identification 1", "attributes": "28 AN", "source": "Standard ISO 8583"},
    "103": {"name": "Account Identification 2", "attributes": "28 AN", "source": "Standard ISO 8583"},
    "120": {"name": "Private Data (Visa/PowerCARD)", "attributes": "999 AN", "source": "Standard ISO 8583"},
    "127": {"name": "Private Data (PowerCARD Internal)", "attributes": "999 AN", "source": "Standard ISO 8583"}
}


def is_standard_field(field_number: str) -> bool:
    """
    Retourne True si le champ est défini dans le référentiel ISO 8583 standard
    (iso8583_field_reference.json) OU dans le dictionnaire STANDARD_ISO_FIELDS.
    Ces champs sont TOUJOURS résolus par le référentiel standard, jamais par un PDF de session.
    """
    padded = field_number.zfill(3)
    unpadded = field_number.lstrip("0") or "0"
    if padded in _ISO8583_FIELDS_REF or unpadded in _ISO8583_FIELDS_REF:
        return True
    if padded in STANDARD_ISO_FIELDS or unpadded in STANDARD_ISO_FIELDS:
        return True
    return False


def get_iso_field_name(field_number: str) -> str:
    """Retourne le nom ISO 8583 d'un champ depuis le référentiel chargé au module."""
    padded = field_number.zfill(3)
    unpadded = field_number.lstrip("0") or "0"
    # 1. Chercher dans le JSON de référence ISO 8583
    if padded in _ISO8583_FIELDS_REF:
        return _ISO8583_FIELDS_REF[padded].get("name", f"Field {field_number}")
    if unpadded in _ISO8583_FIELDS_REF:
        return _ISO8583_FIELDS_REF[unpadded].get("name", f"Field {field_number}")
    # 2. Fallback sur le dictionnaire statique
    std = STANDARD_ISO_FIELDS.get(padded) or STANDARD_ISO_FIELDS.get(unpadded)
    if std:
        return std.get("name", f"Field {field_number}")
    return f"Field {field_number}"


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
    Pour chaque champ extrait d'une transaction, détermine son type attendu en
    appliquant une PRIORITÉ STRICTE DE RÉFÉRENTIEL :

    1. PRIORITÉ ABSOLUE — Référentiel ISO 8583 standard (iso8583_field_reference.json
       + STANDARD_ISO_FIELDS) : si le champ y est défini, sa définition est utilisée
       DIRECTEMENT avec la source "Standard ISO 8583". Le document de session (PDF
       uploadé) n'est JAMAIS consulté pour ces champs.

    2. UNIQUEMENT si le champ est ABSENT du référentiel standard (champ propriétaire /
       spécifique client) : chercher dans le document de session via RAG, puis dans
       la base globale.

    Cette règle élimine les faux positifs causés par une coïncidence de numérotation
    entre les champs ISO 8583 et les champs d'un manuel HSM (ex: payShield 10K)
    uploadé comme document de session.
    """
    alerts = []

    # 1. Collecter et dédoublonner tous les numéros de champs à valider
    unique_field_numbers = list(all_fields.keys())
    definitions_cache = {}

    # 2. Résoudre la définition de chaque champ (dédoublonnée)
    for idx, field_number in enumerate(unique_field_numbers):
        field_name = None
        attributes = None
        source_file = None

        padded = field_number.zfill(3)
        unpadded = field_number.lstrip("0") or "0"

        # ── ÉTAPE A : Référentiel ISO 8583 STANDARD — PRIORITÉ ABSOLUE ──────────
        # Si le champ est standard, on s'arrête ici. Jamais de lookup RAG/session.
        if is_standard_field(field_number):
            std_info = STANDARD_ISO_FIELDS.get(padded) or STANDARD_ISO_FIELDS.get(unpadded)
            if std_info:
                field_name = std_info.get("name")
                attributes = std_info.get("attributes")
            else:
                # Présent dans le JSON mais pas dans STANDARD_ISO_FIELDS → nom via JSON
                field_name = get_iso_field_name(field_number)
                # Pas d'attributs dans le JSON de référence : on ne génère pas de faux positif
                attributes = None
            source_file = "Standard ISO 8583"

        else:
            # ── ÉTAPE B : Champ NON standard → recherche RAG session (si disponible) ──
            if session_id and session_id.strip():
                try:
                    session_docs = search_session_chunks_keyword(
                        session_id, f"Field {field_number}", limit=1
                    )
                    if session_docs:
                        doc = session_docs[0]
                        field_name = doc.metadata.get("field_name")
                        attributes = doc.metadata.get("attributes")
                        source_file = doc.metadata.get("source_file", "document de session")

                        if (not attributes or not str(attributes).strip()) and doc.page_content:
                            match = ATTR_TYPE_RE.search(doc.page_content)
                            if match:
                                attributes = f"{match.group(1)} {match.group(2)}"
                except Exception as e:
                    print(f"Warning: Session lookup failed for field {field_number}: {e}")

            # ── ÉTAPE C : Base de données globale ────────────────────────────────
            if not field_name or not attributes or not str(attributes).strip():
                try:
                    from app.rag.retriever import _query_field_definition_by_number
                    global_def = _query_field_definition_by_number(field_number)
                    if global_def:
                        field_name = global_def.get("field_name") or field_name
                        attributes = global_def.get("attributes") or attributes
                        source_file = (
                            global_def.get("source_file") or source_file or "global database"
                        )
                        if (not attributes or not str(attributes).strip()) and global_def.get("full_content"):
                            match = ATTR_TYPE_RE.search(global_def["full_content"])
                            if match:
                                attributes = f"{match.group(1)} {match.group(2)}"
                except Exception as e:
                    print(f"Warning: _query_field_definition_by_number failed for field {field_number}: {e}")

            # ── ÉTAPE D : Nom de fallback ────────────────────────────────────────
            if not field_name:
                field_name = get_iso_field_name(field_number)
            if not source_file:
                source_file = "document de session"

        if attributes:
            definitions_cache[field_number] = {
                "field_number": field_number,
                "field_name": field_name,
                "attributes": attributes,
                "source_file": source_file,
            }
        else:
            definitions_cache[field_number] = None

        # Pause de sécurité anti-rate-limit si beaucoup de champs uniques (>10)
        if len(unique_field_numbers) > 10 and (idx + 1) % 10 == 0:
            time.sleep(0.1)

    # 3. Valider chaque champ à partir du cache dédoublonné
    for field_number, field_data in all_fields.items():
        value = field_data.get("value")
        definition = definitions_cache.get(field_number)

        if definition is None:
            continue

        expected = _parse_expected_type(definition.get("attributes", ""))
        if expected is None:
            continue

        type_code = expected["type_code"]
        max_length = expected.get("max_length")

        if type_code == "N" and field_number.lstrip("0") in FIELDS_EXCLUDED_FROM_STRICT_N:
            continue  # champ connu pour être hexadécimal malgré son type déclaré "N"

        # Determine expected_type_label
        type_label = {
            "N": "N (numérique)",
            "A": "A (alphabétique)",
            "AN": "AN (alphanumérique)",
            "ANS": "ANS (alphanumérique + spéciaux)",
            "NS": "NS (numérique + spéciaux)",
        }.get(type_code, type_code)

        is_empty = value is None or str(value).strip() == "" or str(value).strip() == "(vide)"
        
        non_conformity = None
        observed_val = value if value is not None else ""

        if is_empty:
            observed_val = "(vide)"
            non_conformity = "Champ absent de la trace"
        else:
            cleaned_for_check = observed_val.replace("*", "")
            reasons = []
            
            if not _value_matches_type(observed_val, type_code):
                if type_code == "N":
                    reasons.append("contient des lettres/symboles non conformes (attendu numérique)")
                elif type_code == "A":
                    reasons.append("contient des chiffres/symboles non conformes (attendu alphabétique)")
                else:
                    reasons.append(f"ne respecte pas le type attendu {type_label}")
            
            if max_length and len(cleaned_for_check) > max_length:
                reasons.append(f"longueur ({len(cleaned_for_check)}) dépasse le maximum ({max_length})")
                
            if reasons:
                non_conformity = " et ".join(reasons)

        if non_conformity:
            message = (
                f"Champ {definition['field_name']} (FLD {field_number}) : "
                f"type attendu {definition['attributes']} ({definition['source_file']}), "
                f"valeur observée '{observed_val}' — {non_conformity}"
            )
            
            alerts.append({
                "field_number": field_number,
                "field_name": definition["field_name"],
                "value": value if value is not None else "",
                "observed_value": observed_val,
                "expected_type": type_code,
                "expected_type_label": type_label,
                "attributes": definition["attributes"],
                "source": definition["source_file"],
                "source_file": definition["source_file"],
                "non_conformity_type": non_conformity,
                "message": message,
            })

    return alerts