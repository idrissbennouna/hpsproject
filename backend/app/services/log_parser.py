import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.services.spec_loader import get_monitored_function_names
from app.services.field_validator import validate_transaction_fields

# --- Chargement du référentiel ISO 8583 (BASE I) ---
ISO8583_REF_PATH = Path(__file__).resolve().parent.parent / "data" / "iso8583_field_reference.json"

_ISO8583_DATA: Dict[str, Any] = {}
if ISO8583_REF_PATH.exists():
    try:
        with open(ISO8583_REF_PATH, "r", encoding="utf-8") as _f:
            _ISO8583_DATA = json.load(_f)
    except Exception as _e:
        print(f"Warning: Impossible de charger iso8583_field_reference.json: {_e}")

ISO8583_MTI_MAP: Dict[str, str] = _ISO8583_DATA.get("mti", {})
ISO8583_FIELDS_MAP: Dict[str, Dict[str, str]] = _ISO8583_DATA.get("fields", {})


def get_iso_field_info(field_num: str) -> Optional[Dict[str, str]]:
    """Retourne la définition ISO 8583 pour un numéro de champ donné (ex: '011', '037', '11')."""
    padded_num = field_num.zfill(3)
    return ISO8583_FIELDS_MAP.get(padded_num) or ISO8583_FIELDS_MAP.get(field_num)


def get_mti_info(mti: str) -> str:
    """Retourne la description textuelle d'un MTI."""
    return ISO8583_MTI_MAP.get(mti, "Message ISO 8583 Non Spécifié")


# --- Marqueurs structurels du protocole (constantes ISO 8583 / PowerCARD) ---
HEARTBEAT_FIELD = "FLD (070)"
HEARTBEAT_VALUE = "[301]"

# Format des identifiants dans le bloc TLV interne
RE_TRANSACTION_ID = re.compile(r"TRANSACTION_IDENTIFIER\}\s*\d+\s+(\S+)")
RE_STAN = re.compile(r"INTERNAL STAN\}\s*\d+\s+(\S+)")
RE_PAN = re.compile(r"PAN\}\s*\d+\s+(\S+)")
RE_CARD_NUMBER = re.compile(r"CARD_NUMBER\}\s*\d+\s+(\S+)")

# Format des dumps ISO bruts
RE_FLD011_DUMP = re.compile(r"FLD\s*\(011\)\s*:\s*\(\d+\)\s*:\s*\[(\d+)\]")
RE_FLD037_DUMP = re.compile(r"FLD\s*\(037\).*\[(\w+)\]")
RE_FLD039_DUMP = re.compile(r"FLD\s*\(039\).*\[(\w+)\]")
RE_MTI_1110 = re.compile(r"M\.T\.I\s*:\s*1110")

# Extraction générique des champs ISO (pour alimenter le RAG et l'enrichissement)
RE_FLD_GENERIC = re.compile(r"-\s*FLD\s*\((\d+)\)\s*:?\s*\((\d+)\)\s*:?\s*\[([^\]]*)\]")

# Identification de session et triggers de début de transaction
RE_SESSION = re.compile(r"^\S+\s+\S+\s+\S+\s+(\S+?)\|")
RE_START_TRANSACTION = re.compile(r"-\s*M\.T\.I\s*:\s*\[(\d{4})\]")

# Extraction HSM & MTI
RE_TO_HSM = re.compile(r"TO\s+HSM\s*:\s*(?:Len=\[\d+\]-->\s*Data=)?\s*(.*?)$", re.IGNORECASE)
RE_FROM_HSM = re.compile(r"FROM\s+HSM\s*:\s*<--(.*?)$", re.IGNORECASE)
RE_HSM_RESULT = re.compile(r"(?:HsmResultCode\s*=\s*|HSM_RESULT_CODE\s*\.*\s*\)\s*:\s*\[?)(\w+)", re.IGNORECASE)
RE_MTI = re.compile(r"M\.T\.I\s*:\s*\[?(\d{4})\]?")
HEARTBEAT_MTIS = {"0800", "0810"}

# Détection générique des fonctions en échec non documentées dans l'Excel
# Capture : NomFonction ... NOK | ( NOK ) | (-1) | résultat -1 | result=-1 | != OK
_FAIL_TOKEN = (
    r"(?:"
    r"NOK\s*\(\s*-\d+\s*\)|"
    r"NOK|"
    r"\(\s*NOK\s*\)|"
    r"\(\s*-\d+\s*\)|"
    r"!=\s*OK|"
    r"!=\s*0|"
    r"ERROR|"
    r"(?:r[ée]sultat|result(?:at)?|returned|return(?:ed|s)?|code)"
    r"\s*[=:]?\s*-+\s*[1-9]\d*|"
    r"=\s*-+\s*[1-9]\d*"
    r")"
)
RE_GENERIC_FAILURE = re.compile(
    rf"\b(?P<func>[A-Za-z][A-Za-z0-9_]{{2,}})\b"
    rf"(?:\s*\(\s*\))?"
    rf"\s*(?::\s*)?"
    rf"(?P<fail>{_FAIL_TOKEN})",
    re.IGNORECASE,
)


def _build_function_failure_patterns(spec_path: Optional[str] = None) -> Dict[str, re.Pattern]:
    patterns = {}
    for func in get_monitored_function_names(spec_path):
        patterns[func] = re.compile(
            rf"\b{re.escape(func)}\b(?:\s*\(\s*\))?\s*(?::\s*)?(?P<fail>{_FAIL_TOKEN})",
            re.IGNORECASE,
        )
    return patterns


def _line_has_success_marker(line: str) -> bool:
    return any(w in line for w in ("End", "Exit", "Return", "END", "EXIT"))


def _line_looks_like_failure_near_func(line: str, func_name: str) -> Optional[str]:
    """
    Détection souple d'un code retour négatif / NOK près d'une fonction,
    pour les formats non couverts par le pattern principal
    (ex: 'GetOriginalAuthData() returned -1').
    """
    if func_name not in line:
        return None
    # Fenêtre locale autour du nom de fonction pour limiter les faux positifs
    idx = line.find(func_name)
    window = line[idx : idx + len(func_name) + 80]
    m = re.search(
        rf"(?:{_FAIL_TOKEN})",
        window,
        re.IGNORECASE,
    )
    if m:
        return m.group(0)
    # Fallback : -1 / -2 isolé après la fonction (sans mot-clé résultat)
    m2 = re.search(r"(?<![0-9])-+\s*([1-9]\d*)\b", window)
    if m2:
        return f"-{m2.group(1)}"
    return None


def _parse_line_components(line: str) -> Optional[Dict[str, Any]]:
    """
    Découpe une ligne de log monétique PowerCARD/ISO pour en extraire :
    - session_id
    - timestamp (si présent)
    - level (niveau de log, ex: 4, 5, D, INFO)
    - message (texte utile de la ligne)
    """
    session_match = RE_SESSION.match(line)
    if not session_match:
        return None
    session_id = session_match.group(1)

    parts = line.split("|", 2)
    prefix = parts[0].strip()
    prefix_tokens = prefix.split()

    timestamp = None
    if len(prefix_tokens) >= 2 and (":" in prefix_tokens[0] or ":" in prefix_tokens[1]):
        if "-" in prefix_tokens[0] or "/" in prefix_tokens[0]:
            timestamp = f"{prefix_tokens[0]} {prefix_tokens[1]}"
        else:
            timestamp = prefix_tokens[0]
    elif len(prefix_tokens) >= 1 and ":" in prefix_tokens[0]:
        timestamp = prefix_tokens[0]

    level = parts[1].strip() if len(parts) > 1 else "INFO"
    message = parts[2].strip() if len(parts) > 2 else (parts[-1].strip() if parts else line)

    return {
        "session_id": session_id,
        "timestamp": timestamp,
        "level": level,
        "message": message,
    }


def _new_tx() -> dict:
    return {
        "identifiers": {
            "transaction_id": None,
            "stan": None,
            "pan": None,
            "rrn": None,
            "response_code": None,
        },
        "mti": None,
        "mti_description": None,
        "all_fields": {},  # RAG et validation de format
        "events": [],
        "alerts": [],
        "failed_functions": [],
        "successful_functions": [],
        "hsm_calls": [],
        "is_heartbeat": False,
        "_seen_event_keys": set(),
    }


def _add_event(tx: dict, text: str, line_num: Optional[int] = None, timestamp: Optional[str] = None, level: Optional[str] = None) -> None:
    """
    Ajoute un événement à la chronologie avec une clé de dédoublonnage fine
    (ligne, horodatage, niveau, texte) pour éviter la suppression abusive
    de répétitions légitimes.
    """
    key = (line_num, timestamp, level, text)
    if key in tx["_seen_event_keys"]:
        return

    tx["_seen_event_keys"].add(key)
    tx["events"].append(text)


def _merge_request_response_pairs(all_transactions: list) -> list:
    """
    Deux passes de fusion :
    Passe A — Fusionne les fragments orphelins (sans STAN/transaction_id mais avec RRN)
               dans leur transaction primaire correspondante, en s'appuyant sur le RRN.
    Passe B — Fusionne les doublons de STAN : quand un même fichier contient plusieurs
               occurrences d'une transaction avec le même STAN (re-tentatives, multi-sessions),
               agrège failed_functions, alerts_found et successful_functions dans une seule
               entrée (la première apparition) pour ne pas perdre les fonctions en échec
               détectées dans les occurrences suivantes.
    """
    indexed = list(enumerate(all_transactions))

    # --- Passe A : Fusion des fragments orphelins par RRN ---
    primaries_by_rrn = {}
    for idx, tx in indexed:
        rrn = tx["identifiers"].get("rrn")
        has_business_id = tx["identifiers"].get("stan") or tx["identifiers"].get("transaction_id")
        if has_business_id and rrn and rrn not in primaries_by_rrn:
            primaries_by_rrn[rrn] = (idx, tx)

    final = []
    already_added_ids = set()
    for idx, tx in indexed:
        rrn = tx["identifiers"].get("rrn")
        has_business_id = tx["identifiers"].get("stan") or tx["identifiers"].get("transaction_id")

        if has_business_id:
            if id(tx) not in already_added_ids:
                final.append(tx)
                already_added_ids.add(id(tx))
            continue

        primary_entry = primaries_by_rrn.get(rrn) if rrn else None
        if primary_entry is None or (tx.get("is_heartbeat") and not primary_entry[1].get("is_heartbeat")):
            final.append(tx)
            continue

        primary_idx, primary = primary_entry
        for field_num, field_val in tx["all_fields"].items():
            primary["all_fields"].setdefault(field_num, field_val)
        for alert in tx.get("alerts_found", []):
            if alert not in primary["alerts_found"]:
                primary["alerts_found"].append(alert)
        if not primary["identifiers"].get("response_code") and tx["identifiers"].get("response_code"):
            primary["identifiers"]["response_code"] = tx["identifiers"]["response_code"]
        for func in tx.get("failed_functions", []):
            if func not in primary["failed_functions"]:
                primary["failed_functions"].append(func)
        for func in tx.get("successful_functions", []):
            if func not in primary["successful_functions"]:
                primary["successful_functions"].append(func)
        for hsm in tx.get("hsm_calls", []):
            if hsm not in primary.get("hsm_calls", []):
                primary.setdefault("hsm_calls", []).append(hsm)
        # Fusionner la chronologie du fragment orphelin dans la transaction primaire
        if tx.get("chronology"):
            primary["chronology"] = (primary.get("chronology", "") + "\n" + tx["chronology"]).strip()

    # --- Passe B : Fusion des doublons par STAN ---
    # Quand plusieurs transactions ont le même STAN (re-tentatives, multi-sessions),
    # on agrège toutes leurs données dans la première occurrence trouvée.
    primary_by_stan: dict = {}
    deduped: list = []
    for tx in final:
        stan = tx["identifiers"].get("stan")
        if not stan:
            # Sans STAN : pas de déduplication possible, on conserve
            deduped.append(tx)
            continue

        if stan not in primary_by_stan:
            # Première occurrence de ce STAN : c'est la transaction primaire
            primary_by_stan[stan] = tx
            deduped.append(tx)
        else:
            # Occurrence suivante : fusionner dans la primaire
            primary = primary_by_stan[stan]
            for func in tx.get("failed_functions", []):
                if func not in primary["failed_functions"]:
                    primary["failed_functions"].append(func)
            for func in tx.get("successful_functions", []):
                if func not in primary["successful_functions"]:
                    primary["successful_functions"].append(func)
            for alert in tx.get("alerts_found", []):
                if alert not in primary["alerts_found"]:
                    primary["alerts_found"].append(alert)
            for field_num, field_val in tx.get("all_fields", {}).items():
                primary["all_fields"].setdefault(field_num, field_val)
            if not primary["identifiers"].get("rrn") and tx["identifiers"].get("rrn"):
                primary["identifiers"]["rrn"] = tx["identifiers"]["rrn"]
            if not primary["identifiers"].get("response_code") and tx["identifiers"].get("response_code"):
                primary["identifiers"]["response_code"] = tx["identifiers"]["response_code"]
            for hsm in tx.get("hsm_calls", []):
                if hsm not in primary.get("hsm_calls", []):
                    primary.setdefault("hsm_calls", []).append(hsm)
            if tx.get("chronology"):
                primary["chronology"] = (primary.get("chronology", "") + "\n" + tx["chronology"]).strip()

    return deduped


class ParsedTransactionList(list):
    """Liste de transactions analysées avec métadonnée du nombre de heartbeats filtrés."""
    def __init__(self, items=None, heartbeat_count: int = 0):
        super().__init__(items or [])
        self.heartbeat_count = heartbeat_count


def parse_trace_file(
    file_path: str,
    spec_path: Optional[str] = None,
    doc_session_id: Optional[str] = None,
    mode: str = "full",
    include_heartbeats: bool = False
) -> ParsedTransactionList:
    """
    Module unique de parsing de trace de logs monétiques PowerCARD / ISO 8583.

    EXCLUSION DES HEARTBEATS (0800 / 0810 / FLD(070)=[301]) :
    Les messages de network management et heartbeats sont automatiquement détectés
    pendant le parsing pour permettre la fusion des fragments orphelins (par RRN),
    mais ils sont SYSTÉMATIQUEMENT EXCLUS de la liste de transactions finale retournée
    (sauf si include_heartbeats=True).
    Raison : ils constituent du bruit analytique sans valeur métier et gonflent inutilement
    la taille des prompts envoyés aux modèles LLM (risque d'épuisement de quota TPM Gemini 429).

    :param file_path: Chemin absolu du fichier .txt de trace
    :param spec_path: Chemin optionnel de la spécification métier
    :param doc_session_id: ID de session pour validation de format RAG
    :param mode: "full" (capture exhaustive pour rapport PDF) ou "compact" (synthétique pour agent conversationnel)
    :param include_heartbeats: Si True, conserve les heartbeats dans la liste finale.
    :return: ParsedTransactionList (liste de transactions + attribut heartbeat_count)
    """
    all_transactions = []
    function_patterns = _build_function_failure_patterns(spec_path)

    response_code_map = {}
    pending_mti_sessions = {}
    sessions = {}

    def save(tx):
        # On conserve le statut is_heartbeat tel quel sans le masquer sous prétexte d'événements TLV.
        # Cela permet d'exécuter la fusion par RRN d'abord, puis de filtrer strictement les heartbeats après.
        is_hb = bool(tx.get("is_heartbeat"))

        idents = tx["identifiers"]
        if not is_hb and not idents.get("stan") and not idents.get("transaction_id") and not idents.get("rrn") and not idents.get("pan"):
            return

        stan = tx["identifiers"]["stan"]
        response_code = response_code_map.get(stan) if stan else None
        if response_code:
            _add_event(
                tx,
                f"Message Réseau Sortant (Outgoing Response) généré avec le Code Réponse [FLD 039] = {response_code}.",
            )
        elif stan:
            _add_event(
                tx,
                "Aucun message de réponse (MTI 1110) retrouvé pour ce STAN dans le fichier — "
                "transaction probablement mise en attente (Store-and-Forward) ou trace incomplète.",
            )

        # --- VALIDATION DE FORMAT DES CHAMPS (RAG) ---
        format_alerts = validate_transaction_fields(tx["all_fields"], session_id=doc_session_id)
        for fa in format_alerts:
            _add_event(tx, f"ALERTE FORMAT : {fa['message']}")
            tx["alerts"].append(fa["message"])

        all_transactions.append({
            "identifiers": tx["identifiers"].copy(),
            "mti": tx["mti"],
            "mti_description": tx["mti_description"],
            "all_fields": tx["all_fields"].copy(),
            "chronology": "\n".join(f"- {ev}" for ev in tx["events"]),
            "alerts_found": list(tx["alerts"]),
            "format_alerts": format_alerts,
            "failed_functions": list(tx["failed_functions"]),
            "successful_functions": list(tx["successful_functions"]),
            "hsm_calls": list(tx.get("hsm_calls", [])),
            "is_heartbeat": is_hb,
        })

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_idx, raw_line in enumerate(f, 1):
                line = raw_line.strip()
                if not line:
                    continue

                parsed_comp = _parse_line_components(line)
                if parsed_comp is None:
                    continue

                session_id = parsed_comp["session_id"]
                timestamp = parsed_comp["timestamp"]
                level = parsed_comp["level"]
                message = parsed_comp["message"]

                # Métadonnées de ligne (pour mode full ou traçabilité)
                time_prefix = f"[{timestamp} | {level}] " if timestamp else f"[{level}] "
                line_meta = f"Ligne {line_idx}"
                prefix_str = f"({line_meta}) {time_prefix}" if mode == "full" else ""

                # 1. Détection des codes réponses
                if RE_MTI_1110.search(line):
                    pending_mti_sessions[session_id] = {"stan": None, "resp": None}
                elif session_id in pending_mti_sessions:
                    match_stan = RE_FLD011_DUMP.search(line)
                    if match_stan:
                        pending_mti_sessions[session_id]["stan"] = match_stan.group(1)
                    match_resp = RE_FLD039_DUMP.search(line)
                    if match_resp:
                        pending_mti_sessions[session_id]["resp"] = match_resp.group(1)
                    if pending_mti_sessions[session_id]["stan"] and pending_mti_sessions[session_id]["resp"]:
                        response_code_map[pending_mti_sessions[session_id]["stan"]] = pending_mti_sessions[session_id]["resp"]
                        del pending_mti_sessions[session_id]

                # 2. Détection d'une nouvelle transaction (marqueur MTI universel)
                start_match = RE_START_TRANSACTION.search(line)
                if start_match:
                    previous_tx = sessions.get(session_id)
                    if previous_tx is not None:
                        save(previous_tx)
                    tx = _new_tx()
                    mti_val = start_match.group(1)
                    mti_desc = get_mti_info(mti_val)
                    tx["mti"] = mti_val
                    tx["mti_description"] = mti_desc
                    _add_event(
                        tx,
                        f"{prefix_str}Message Réseau Entrant (Incoming Request) MTI [{mti_val}] ({mti_desc}) détecté.",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    if mti_val in HEARTBEAT_MTIS:
                        tx["is_heartbeat"] = True
                    sessions[session_id] = tx
                    continue

                tx = sessions.get(session_id)
                if tx is None:
                    tx = _new_tx()
                    sessions[session_id] = tx

                enriched_event_added = False

                mti_match = RE_MTI.search(line)
                if mti_match:
                    mti_val = mti_match.group(1)
                    tx["mti"] = mti_val
                    tx["mti_description"] = get_mti_info(mti_val)
                    if mti_val in HEARTBEAT_MTIS:
                        tx["is_heartbeat"] = True

                if HEARTBEAT_FIELD in line and HEARTBEAT_VALUE in line:
                    tx["is_heartbeat"] = True

                # Identifiants
                match = RE_TRANSACTION_ID.search(line)
                if match:
                    tx["identifiers"]["transaction_id"] = match.group(1)

                match = RE_STAN.search(line)
                if match:
                    tx["identifiers"]["stan"] = match.group(1)

                match = RE_PAN.search(line) or RE_CARD_NUMBER.search(line)
                if match:
                    tx["identifiers"]["pan"] = match.group(1)

                match = RE_FLD037_DUMP.search(line)
                if match:
                    val_rrn = match.group(1)
                    tx["identifiers"]["rrn"] = val_rrn
                    _add_event(
                        tx,
                        f"{prefix_str}Champ [FLD 037] (Retrieval Reference Number / RRN) détecté : {val_rrn}.",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    enriched_event_added = True

                match = RE_FLD039_DUMP.search(line)
                if match:
                    val_rc = match.group(1)
                    tx["identifiers"]["response_code"] = val_rc
                    status = "Approuvée" if val_rc in ["00", "000"] else f"Déclinée (Code: {val_rc})"
                    _add_event(
                        tx,
                        f"{prefix_str}Champ [FLD 039] (Response Code) détecté : {val_rc} ({status}).",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    enriched_event_added = True

                # Extraction RAG & Enrichissement ISO 8583 généralisé via Référentiel
                match = RE_FLD_GENERIC.search(line)
                if match:
                    field_number, declared_length, value = match.groups()
                    field_info = get_iso_field_info(field_number)
                    field_name = field_info["name"] if field_info else f"FLD {field_number}"
                    field_desc = field_info["description"] if field_info else "Champ ISO 8583"

                    tx["all_fields"][field_number] = {
                        "value": value,
                        "declared_length": declared_length,
                        "name": field_name,
                        "description": field_desc,
                    }

                    # En mode compact ou full, enrichir la chronologie pour les champs ISO notables (autres que 037/039 déjà traités)
                    if field_number not in ["037", "039"]:
                        _add_event(
                            tx,
                            f"{prefix_str}Champ [FLD {field_number}] ({field_name} - {field_desc}) : [{value}]",
                            line_num=line_idx, timestamp=timestamp, level=level
                        )
                        enriched_event_added = True

                # Suivi HSM / Sécurité
                match_to_hsm = RE_TO_HSM.search(line)
                if match_to_hsm:
                    hsm_cmd = match_to_hsm.group(1).strip()
                    if hsm_cmd:
                        _add_event(
                            tx,
                            f"{prefix_str}Échange HSM (TO HSM) : Commande transmise au HSM -> {hsm_cmd}",
                            line_num=line_idx, timestamp=timestamp, level=level
                        )
                        if hsm_cmd not in tx["hsm_calls"]:
                            tx["hsm_calls"].append(hsm_cmd)
                        enriched_event_added = True

                match_from_hsm = RE_FROM_HSM.search(line)
                if match_from_hsm:
                    hsm_resp = match_from_hsm.group(1).strip()
                    if hsm_resp:
                        _add_event(
                            tx,
                            f"{prefix_str}Échange HSM (FROM HSM) : Réponse reçue du HSM -> {hsm_resp}",
                            line_num=line_idx, timestamp=timestamp, level=level
                        )
                        enriched_event_added = True

                match_hsm_res = RE_HSM_RESULT.search(line)
                if match_hsm_res:
                    hsm_res_code = match_hsm_res.group(1).strip()
                    _add_event(
                        tx,
                        f"{prefix_str}Code Résultat HSM (HsmResultCode) : {hsm_res_code}",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    enriched_event_added = True
                    if hsm_res_code and hsm_res_code not in ["00", "000", "0"]:
                        anomalie = f"Erreur HSM détectée : Code d'erreur HSM {hsm_res_code}."
                        if anomalie not in tx["alerts"]:
                            tx["alerts"].append(anomalie)

                # Jalons TLV
                is_end_line = message.startswith("End")
                if is_end_line and "IsoToTlv" in line:
                    _add_event(
                        tx,
                        f"{prefix_str}Conversion des données : Format réseau ISO 8583 vers format interne TLV.",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    enriched_event_added = True
                if is_end_line and "ValidateTlvData" in line:
                    _add_event(
                        tx,
                        f"{prefix_str}Contrôle structurel : Validation du format des données TLV.",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    enriched_event_added = True
                if is_end_line and "LoadIssuerInfo" in line:
                    _add_event(
                        tx,
                        f"{prefix_str}Traitement : Chargement des paramètres de la banque émettrice.",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    enriched_event_added = True

                # Surveillance fonctions métier (liste Excel)
                # Deux passes distinctes :
                #   Passe 1 — fonctions surveillées (Excel) : pattern d'échec ou trace de succès
                #   Passe 2 — détection générique, TOUJOURS exécutée (indépendamment de la passe 1)
                #             pour capturer les fonctions absentes de l'Excel sur la même ligne
                monitored_functions = get_monitored_function_names(spec_path)

                # --- Passe 1 : fonctions Excel documentées ---
                # Ensemble des fonctions déjà identifiées en échec par le pattern Excel
                # (utilisé en passe 2 pour éviter les doublons d'alerte)
                excel_failed_funcs = set()

                for func_name in monitored_functions:
                    # Recherche insensible à la casse pour robustesse (espaces multiples, etc.)
                    if func_name not in line:
                        continue

                    pattern = function_patterns.get(func_name)
                    match_fail = pattern.search(line) if pattern else None
                    soft_fail_code = None if match_fail else _line_looks_like_failure_near_func(line, func_name)

                    if match_fail or soft_fail_code:
                        code = (
                            match_fail.group("fail")
                            if match_fail and "fail" in match_fail.groupdict()
                            else (match_fail.group(1) if match_fail else soft_fail_code)
                        )
                        anomalie = f"{func_name}() a échoué (résultat : {code})."
                        _add_event(
                            tx,
                            f"{prefix_str}ALERTE : {anomalie}",
                            line_num=line_idx, timestamp=timestamp, level=level
                        )
                        enriched_event_added = True
                        if anomalie not in tx["alerts"]:
                            tx["alerts"].append(anomalie)
                        if func_name not in tx["failed_functions"]:
                            tx["failed_functions"].append(func_name)
                        excel_failed_funcs.add(func_name)
                    elif _line_has_success_marker(line):
                        # Ne jamais classer en succès si un code négatif/NOK est présent sur la ligne
                        if _line_looks_like_failure_near_func(line, func_name):
                            continue
                        res_match = re.search(rf"{re.escape(func_name)}\s*\(\s*([^)]*)\)", line)
                        res_str = res_match.group(1).strip() if res_match and res_match.group(1) else "OK"
                        _add_event(
                            tx,
                            f"{prefix_str}Fonction {func_name}() exécutée avec succès (résultat : {res_str}).",
                            line_num=line_idx, timestamp=timestamp, level=level
                        )
                        enriched_event_added = True
                        if func_name not in tx["successful_functions"]:
                            tx["successful_functions"].append(func_name)

                # --- Passe 2 : détection générique (toujours exécutée) ---
                # Capture les fonctions en échec NON présentes dans l'Excel (ex: GetTimers absent
                # de Spec_PowerCARD.xlsx, swimon_check_msg_id, etc.) ainsi que les fonctions Excel
                # dont le pattern n'a pas matché mais que RE_GENERIC_FAILURE détecte quand même.
                GENERIC_BLACKLIST = {"END", "START", "FLD", "MTI", "PAN", "STAN", "RRN", "FROM", "TO", "HSM", "LEVEL"}
                for gen_match in RE_GENERIC_FAILURE.finditer(line):
                    generic_func = gen_match.group("func")
                    generic_code = gen_match.group("fail")

                    if generic_func.upper() in GENERIC_BLACKLIST:
                        continue

                    # Ne pas dupliquer une alerte déjà émise par la passe Excel
                    if generic_func in excel_failed_funcs:
                        continue

                    is_monitored = generic_func in monitored_functions

                    if is_monitored:
                        # Fonction Excel dont le pattern spécifique n'a pas matché mais
                        # RE_GENERIC_FAILURE la détecte quand même : la signaler comme documentée
                        anomalie_text = f"{generic_func}() a échoué (résultat : {generic_code})."
                    else:
                        anomalie_text = (
                            f"{generic_func}() a échoué (résultat : {generic_code})"
                            " — fonction non documentée dans Spec_PowerCARD.xlsx."
                        )

                    _add_event(
                        tx,
                        f"{prefix_str}ALERTE : {anomalie_text}",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )
                    enriched_event_added = True
                    if anomalie_text not in tx["alerts"]:
                        tx["alerts"].append(anomalie_text)
                    if generic_func not in tx["failed_functions"]:
                        tx["failed_functions"].append(generic_func)

                # Mode "full" : capture également toute ligne non enrichie
                if mode == "full" and not enriched_event_added and message:
                    _add_event(
                        tx,
                        f"{prefix_str}{message}",
                        line_num=line_idx, timestamp=timestamp, level=level
                    )

        for tx in sessions.values():
            save(tx)

        # Fusion des fragments orphelins (par RRN) AVANT de filtrer les heartbeats
        all_transactions = _merge_request_response_pairs(all_transactions)

    except Exception as e:
        print(f"Erreur lors du parsing de la trace: {str(e)}")
        return ParsedTransactionList([])

    # Décompte exact des transactions heartbeat identifiées
    heartbeat_count = sum(1 for tx in all_transactions if tx.get("is_heartbeat"))

    if not include_heartbeats:
        # Ne filtrer un heartbeat que s'il n'a AUCUNE fonction en échec ni alerte
        final_transactions = [
            tx for tx in all_transactions
            if not (tx.get("is_heartbeat") and not tx.get("failed_functions") and not tx.get("alerts_found"))
        ]
    else:
        final_transactions = all_transactions

    return ParsedTransactionList(final_transactions, heartbeat_count=heartbeat_count)


def parse_and_format_log_file(file_path: str, mode: str = "compact") -> str:
    """
    Formate la trace de log sous forme textuelle structurée.
    Exclut systématiquement les transactions heartbeat (0800/0810 / FLD(070)=[301])
    du corps du texte et affiche un décompte explicite dans le bloc de synthèse globale.

    :param file_path: Chemin du fichier de trace
    :param mode: "compact" (pour agent de validation / questions libres) ou "full" (pour agent d'analyse)
    :return: Chaîne de caractères formatée
    """
    transactions = parse_trace_file(file_path, mode=mode, include_heartbeats=False)
    heartbeat_count = getattr(transactions, "heartbeat_count", 0)

    if not transactions and heartbeat_count == 0:
        return ""

    # Synthese globale
    total_tx = len(transactions)
    all_hsm_calls = []
    total_alerts = 0

    for tx in transactions:
        all_hsm_calls.extend(tx.get("hsm_calls", []))
        total_alerts += len(tx.get("alerts_found", []))

    distinct_hsm = sorted(list(set(all_hsm_calls)))

    summary_header = (
        "=== SYNTHÈSE GLOBALE DE LA TRACE ===\n"
        f"Transactions analysées : {total_tx}\n"
        f"Messages heartbeat (0800/0810) : {heartbeat_count} détectés et ignorés dans cette trace\n"
        f"Appels HSM détectés    : {len(all_hsm_calls)}\n"
        f"Commandes HSM uniques  : {', '.join(distinct_hsm) if distinct_hsm else 'Aucune'}\n"
        f"Alertes / Anomalies    : {total_alerts}\n"
        "====================================="
    )

    blocks = [summary_header]

    for idx, tx in enumerate(transactions, 1):
        idents = tx.get("identifiers", {})
        chronology = tx.get("chronology", "")
        alerts = tx.get("alerts_found", [])
        mti_desc = tx.get("mti_description") or ""
        mti_str = f"MTI {tx.get('mti')} ({mti_desc})" if tx.get("mti") else "MTI non spécifié"

        rrn = idents.get("rrn") or "N/A"
        rc = idents.get("response_code") or "N/A"
        status = "Approuvée" if rc in ["00", "000"] else f"Déclinée (Code: {rc})" if rc != "N/A" else "Inconnue"

        mode_label = "synthétique" if mode == "compact" else "exhaustive"

        blocks.append(
            f"=== Transaction {idx} [{mti_str}] ===\n"
            f"STAN: {idents.get('stan') or 'N/A'} | PAN: {idents.get('pan') or 'N/A'} | ID: {idents.get('transaction_id') or 'N/A'}\n"
            f"RRN [FLD 037]: {rrn} | Code Réponse [FLD 039]: {rc} ({status})\n"
            f"Chronologie ({mode_label}):\n{chronology}\n"
            f"Alertes: {', '.join(alerts) if alerts else 'Aucune'}\n"
            f"Fonctions OK: {', '.join(tx.get('successful_functions', [])) if tx.get('successful_functions') else 'Aucune'}"
        )

    return "\n\n".join(blocks)


# --- Aliases de rétrocompatibilité ---
def parse_trace_file_for_story(file_path: str, spec_path: Optional[str] = None, doc_session_id: Optional[str] = None) -> list:
    return parse_trace_file(file_path, spec_path=spec_path, doc_session_id=doc_session_id, mode="compact")


def parse_trace_file_for_story_v2(file_path: str, spec_path: Optional[str] = None, doc_session_id: Optional[str] = None) -> list:
    return parse_trace_file(file_path, spec_path=spec_path, doc_session_id=doc_session_id, mode="full")


def parse_and_format_log_file_v2(file_path: str) -> str:
    return parse_and_format_log_file(file_path, mode="full")