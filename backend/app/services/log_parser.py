import re

from app.services.spec_loader import get_monitored_function_names
from app.services.field_validator import validate_transaction_fields

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

# Extraction générique des champs ISO (pour alimenter le RAG)
RE_FLD_GENERIC = re.compile(r"-\s*FLD\s*\((\d+)\)\s*\((\d+)\)\s*\[([^\]]*)\]")

# Identification de session et triggers de début de transaction
RE_SESSION = re.compile(r"^\S+\s+\S+\s+\S+\s+(\S+?)\|")
RE_START_TRANSACTION = re.compile(r"Start\s+(?:Dump[A-Za-z0-9_]*|dump_buffer)\(\)", re.IGNORECASE)

# Extraction HSM & MTI (Mises à jour collègue)
RE_TO_HSM = re.compile(r"TO\s+HSM\s*:\s*(?:Len=\[\d+\]-->\s*Data=)?\s*(.*?)$", re.IGNORECASE)
RE_FROM_HSM = re.compile(r"FROM\s+HSM\s*:\s*<--(.*?)$", re.IGNORECASE)
RE_HSM_RESULT = re.compile(r"(?:HsmResultCode\s*=\s*|HSM_RESULT_CODE\s*\.*\s*\)\s*:\s*\[?)(\w+)", re.IGNORECASE)
RE_MTI = re.compile(r"M\.T\.I\s*:\s*\[?(\d{4})\]?")
HEARTBEAT_MTIS = {"0800", "0810"}


def _build_function_failure_patterns(spec_path: str = None) -> dict:
    patterns = {}
    for func in get_monitored_function_names(spec_path):
        patterns[func] = re.compile(
            rf"{re.escape(func)}\s*\(?\s*(NOK|-1|-2|!=\s*OK)", re.IGNORECASE
        )
    return patterns


def _build_response_code_map(file_path: str) -> dict:
    stan_to_response = {}
    pending = {}

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            session_match = RE_SESSION.match(line)
            if not session_match:
                continue
            session_id = session_match.group(1)

            if RE_MTI_1110.search(line):
                pending[session_id] = {"stan": None, "resp": None}
                continue

            if session_id in pending:
                match_stan = RE_FLD011_DUMP.search(line)
                if match_stan:
                    pending[session_id]["stan"] = match_stan.group(1)

                match_resp = RE_FLD039_DUMP.search(line)
                if match_resp:
                    pending[session_id]["resp"] = match_resp.group(1)

                if pending[session_id]["stan"] and pending[session_id]["resp"]:
                    stan_to_response[pending[session_id]["stan"]] = pending[session_id]["resp"]
                    del pending[session_id]

    return stan_to_response


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
        "all_fields": {},  # <-- Conservé pour le RAG
        "events": [],
        "alerts": [],
        "failed_functions": [],
        "successful_functions": [],
        "is_heartbeat": False,
        "_last_event": None,
    }


def _add_event(tx: dict, text: str) -> None:
    if tx["_last_event"] == text:
        return
    tx["events"].append(text)
    tx["_last_event"] = text


def parse_trace_file_for_story(file_path: str, spec_path: str = None, doc_session_id: str = None) -> list:
    all_transactions = []
    function_patterns = _build_function_failure_patterns(spec_path)

    response_code_map = {}
    pending_mti_sessions = {}
    sessions = {}

    def save(tx):
        has_real_content = (
            bool(tx["identifiers"]["stan"])
            or bool(tx["alerts"])
            or bool(tx["identifiers"]["transaction_id"])
        )
        final_is_heartbeat = tx["is_heartbeat"] and not has_real_content
        if final_is_heartbeat:
            return

        if not tx["identifiers"]["stan"] and not tx["identifiers"]["transaction_id"] and len(tx["events"]) <= 1:
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
            "all_fields": tx["all_fields"].copy(),  # <-- RAG préservé
            "chronology": "\n".join(f"- {ev}" for ev in tx["events"]),
            "alerts_found": list(tx["alerts"]),
            "failed_functions": list(tx["failed_functions"]),
            "successful_functions": list(tx["successful_functions"]),
            "is_heartbeat": final_is_heartbeat,
        })

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()

                session_match = RE_SESSION.match(line)
                session_id = session_match.group(1) if session_match else None

                if session_id is None:
                    continue

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

                # 2. Détection d'une nouvelle transaction (Trigger élargi du collègue)
                if RE_START_TRANSACTION.search(line):
                    previous_tx = sessions.get(session_id)
                    if previous_tx is not None:
                        save(previous_tx)
                    tx = _new_tx()
                    _add_event(tx, "Message Réseau Entrant (Incoming Request) détecté.")
                    sessions[session_id] = tx
                    continue

                tx = sessions.get(session_id)
                if tx is None:
                    continue

                # Filtrage Heartbeat via MTI
                mti_match = RE_MTI.search(line)
                if mti_match:
                    mti_val = mti_match.group(1)
                    tx["mti"] = mti_val
                    if mti_val in HEARTBEAT_MTIS:
                        tx["is_heartbeat"] = True

                if HEARTBEAT_FIELD in line and HEARTBEAT_VALUE in line:
                    tx["is_heartbeat"] = True

                # Identification des transactions
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
                    _add_event(tx, f"Champ [FLD 037] (Retrieval Reference Number) détecté : {val_rrn}.")

                match = RE_FLD039_DUMP.search(line)
                if match:
                    val_rc = match.group(1)
                    tx["identifiers"]["response_code"] = val_rc
                    status = "Approuvée" if val_rc in ["00", "000"] else f"Déclinée (Code: {val_rc})"
                    _add_event(tx, f"Champ [FLD 039] (Response Code) détecté : {val_rc} ({status}).")

                # Extraction des champs pour validation RAG
                match = RE_FLD_GENERIC.search(line)
                if match:
                    field_number, declared_length, value = match.groups()
                    tx["all_fields"][field_number] = {
                        "value": value,
                        "declared_length": declared_length,
                    }

                # Suivi HSM / Sécurité
                match_to_hsm = RE_TO_HSM.search(line)
                if match_to_hsm:
                    hsm_cmd = match_to_hsm.group(1).strip()
                    if hsm_cmd:
                        _add_event(tx, f"Échange HSM (TO HSM) : Commande transmise au HSM -> {hsm_cmd}")

                match_from_hsm = RE_FROM_HSM.search(line)
                if match_from_hsm:
                    hsm_resp = match_from_hsm.group(1).strip()
                    if hsm_resp:
                        _add_event(tx, f"Échange HSM (FROM HSM) : Réponse reçue du HSM -> {hsm_resp}")

                match_hsm_res = RE_HSM_RESULT.search(line)
                if match_hsm_res:
                    hsm_res_code = match_hsm_res.group(1).strip()
                    _add_event(tx, f"Code Résultat HSM (HsmResultCode) : {hsm_res_code}")
                    if hsm_res_code and hsm_res_code not in ["00", "000", "0"]:
                        anomalie = f"Erreur HSM détectée : Code d'erreur HSM {hsm_res_code}."
                        if anomalie not in tx["alerts"]:
                            tx["alerts"].append(anomalie)

                # Chronologie / Jalons TLV
                message = line.split("|")[-1].strip() if "|" in line else line
                is_end_line = message.startswith("End")

                if is_end_line and "IsoToTlv" in line:
                    _add_event(tx, "Conversion des données : Format réseau ISO 8583 vers format interne TLV.")
                if is_end_line and "ValidateTlvData" in line:
                    _add_event(tx, "Contrôle structurel : Validation du format des données TLV.")
                if is_end_line and "LoadIssuerInfo" in line:
                    _add_event(tx, "Traitement : Chargement des paramètres de la banque émettrice.")

                # Surveillance fonctions métier
                monitored_functions = get_monitored_function_names(spec_path)
                for func_name in monitored_functions:
                    if func_name not in line:
                        continue

                    if "End" in line:
                        pattern = function_patterns.get(func_name)
                        match = pattern.search(line) if pattern else None

                        if match:
                            code = match.group(1)
                            anomalie = f"{func_name}() a échoué (résultat : {code})."
                            _add_event(tx, f"ALERTE : {anomalie}")
                            tx["alerts"].append(anomalie)
                            if func_name not in tx["failed_functions"]:
                                tx["failed_functions"].append(func_name)
                        else:
                            res_match = re.search(rf"{re.escape(func_name)}\s*\(\s*([^)]*)\)", line)
                            res_str = res_match.group(1).strip() if res_match and res_match.group(1) else "OK"
                            _add_event(tx, f"Fonction {func_name}() exécutée avec succès (résultat : {res_str}).")
                            if func_name not in tx["successful_functions"]:
                                tx["successful_functions"].append(func_name)
                        break

        for tx in sessions.values():
            save(tx)

    except Exception as e:
        print(f"Erreur : {str(e)}")
        return []

    return all_transactions


def parse_and_format_log_file(file_path: str) -> str:
    transactions = parse_trace_file_for_story(file_path)
    if not transactions:
        return ""
    blocks = []
    for idx, tx in enumerate(transactions, 1):
        idents = tx.get("identifiers", {})
        chronology = tx.get("chronology", "")
        alerts = tx.get("alerts_found", [])

        rrn = idents.get("rrn") or "N/A"
        rc = idents.get("response_code") or "N/A"
        status = "Approuvée" if rc in ["00", "000"] else f"Déclinée (Code: {rc})" if rc != "N/A" else "Inconnue"

        blocks.append(
            f"=== Transaction {idx} ===\n"
            f"STAN: {idents.get('stan') or 'N/A'} | PAN: {idents.get('pan') or 'N/A'} | ID: {idents.get('transaction_id') or 'N/A'}\n"
            f"RRN [FLD 037]: {rrn} | Code Réponse [FLD 039]: {rc} ({status})\n"
            f"Chronologie:\n{chronology}\n"
            f"Alertes: {', '.join(alerts) if alerts else 'Aucune'}\n"
            f"Fonctions OK: {', '.join(tx.get('successful_functions', [])) if tx.get('successful_functions') else 'Aucune'}"
        )
    return "\n\n".join(blocks)