import re

from app.services.spec_loader import get_monitored_function_names

# --- Marqueurs structurels du protocole (constantes ISO 8583 / PowerCARD,
#     indépendantes de la spec métier -> ce ne sont pas des "règles métier
#     en dur", juste des repères de format de log) ---
HEARTBEAT_FIELD = "FLD (070)"
HEARTBEAT_VALUE = "[301]"

# Format réel des lignes d'identifiants dans le bloc TLV interne :
#   296 {   TRANSACTION_IDENTIFIER} 015 384329550314997
#   011 {            INTERNAL STAN} 006 593604
#   002 {                      PAN} 016 4058360***047713
# -> la valeur suit l'accolade fermante et la longueur, pas un ":".
RE_TRANSACTION_ID = re.compile(r"TRANSACTION_IDENTIFIER\}\s*\d+\s+(\S+)")
RE_STAN = re.compile(r"INTERNAL STAN\}\s*\d+\s+(\S+)")
RE_PAN = re.compile(r"PAN\}\s*\d+\s+(\S+)")
RE_CARD_NUMBER = re.compile(r"CARD_NUMBER\}\s*\d+\s+(\S+)")

# Format des dumps ISO bruts (DumpIso / DumpVisa), différent du bloc TLV ci-dessus :
#   - FLD (011) : (006) : [593604]
#   - FLD (037) : (012) : [024500045686]
#   - FLD (039) : (003) : [116]
RE_FLD011_DUMP = re.compile(r"FLD\s*\(011\)\s*:\s*\(\d+\)\s*:\s*\[(\d+)\]")
RE_FLD037_DUMP = re.compile(r"FLD\s*\(037\).*\[(\w+)\]")
RE_FLD039_DUMP = re.compile(r"FLD\s*\(039\).*\[(\w+)\]")
RE_MTI_1110 = re.compile(r"M\.T\.I\s*:\s*1110")


# Chaque ligne de trace commence par :  <date> <heure> <pid> <SESSION>|<niveau>| <message>
# ex: "2411 191711179 38142014 00005657|5| Start IsoToTlv ()"
# Le fichier trace multiplexe PLUSIEURS transactions en parallèle : ce numéro
# de session est le seul identifiant fiable pour savoir à quelle transaction
# une ligne appartient réellement (le simple ordre d'apparition dans le fichier
# ne suffit pas, cf. bug de contamination croisée corrigé ci-dessous).
RE_SESSION = re.compile(r"^\S+\s+\S+\s+\S+\s+(\S+?)\|")


def _build_function_failure_patterns(spec_path: str = None) -> dict:
    """
    Construit dynamiquement les regex de détection d'échec pour CHAQUE
    fonction listée dans Spec_PowerCARD.xlsx (plus de liste ["CheckReqTlvFields",
    "FrdCheckControl", ...] écrite à la main : si YZ/HPS ajoute une fonction
    dans l'Excel, elle est surveillée automatiquement).

    Couvre les formats d'échec réellement observés dans les traces PowerCARD :
        FuncName(NOK)               -> ex: CardInSaf(NOK)
        FuncName ( NOK )            -> ex: End CardInSaf ( NOK )
        FuncName NOK ( -1 )         -> ex: GetAuthRouting NOK ( -1 )
        FuncName(-1, ...)           -> ex: GetOriginalAuthData(-1,Auth(X)...)
        FuncName() != OK            -> format documenté dans la spec (AuthRequestProc)
    """
    patterns = {}
    for func in get_monitored_function_names(spec_path):
        patterns[func] = re.compile(
            rf"{re.escape(func)}\s*\(?\s*(NOK|-1|-2|!=\s*OK)", re.IGNORECASE
        )
    return patterns


def _build_response_code_map(file_path: str) -> dict:
    """
    Le message de réponse (MTI 1110) est parfois dumpé par un thread/session
    interne DIFFÉRENT de celui qui a traité la requête entrante (MTI 1100) —
    le switch PowerCARD sépare le traitement entrant et l'émission sortante
    sur des sessions distinctes. Le seul point de corrélation fiable entre
    les deux est le STAN métier (FLD 011), pas le numéro de session.

    Ce pré-passage construit donc une table { stan_metier -> code_reponse }
    en scannant TOUT le fichier pour les blocs MTI 1110, indépendamment de
    la session qui les traite.
    """
    stan_to_response = {}
    pending = {}  # session_id -> {"stan": ..., "resp": ...} en cours de complétion

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
            "response_code": None
        },
        "events": [],
        "alerts": [],
        "failed_functions": [],
        "successful_functions": [],
        "is_heartbeat": False,
        "_last_event": None,  # pour dédupliquer les événements consécutifs identiques
    }



def _add_event(tx: dict, text: str) -> None:
    """Ajoute un événement à la story, SAUF si c'est une répétition immédiate
    du dernier événement ajouté (cas Start X() + End X() qui matchent tous les
    deux le même mot-clé -> on ne veut qu'un seul jalon dans la story)."""
    if tx["_last_event"] == text:
        return
    tx["events"].append(text)
    tx["_last_event"] = text


def parse_trace_file_for_story(file_path: str, spec_path: str = None) -> list:
    all_transactions = []
    function_patterns = _build_function_failure_patterns(spec_path)

    response_code_map = {}
    pending_mti_sessions = {}
    sessions = {}  # session_id -> transaction en cours pour CETTE session uniquement

    def save(tx):
        # On ne jette comme "Heartbeat" QUE si aucun contenu métier réel n'a été
        # trouvé par ailleurs. En pratique, certaines fenêtres contiennent un
        # résidu du cycle d'echo-test précédent (flush tardif du FLD070=[301])
        # juste avant une vraie transaction sur la même session : on ne veut pas
        # perdre cette transaction à cause de ce résidu.
        has_real_content = (
            bool(tx["identifiers"]["stan"])
            or bool(tx["alerts"])
            or bool(tx["identifiers"]["transaction_id"])
        )
        final_is_heartbeat = tx["is_heartbeat"] and not has_real_content
        if final_is_heartbeat:
            return
        
        # Bug secondaire : rejette les stubs vides
        if not tx["identifiers"]["stan"] and not tx["identifiers"]["transaction_id"] and len(tx["events"]) <= 1:
            return

        # Corrélation croisée : le vrai code réponse (MTI 1110) peut avoir été
        # dumpé sur une AUTRE session que celle-ci -> on le rattache ici via le
        # STAN métier plutôt que de se fier à un FLD039 vu localement.
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

        all_transactions.append({
            "identifiers": tx["identifiers"].copy(),
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

                # Ligne qu'on ne peut pas rattacher à une session (bruit/format inattendu) -> ignorée
                if session_id is None:
                    continue

                # --- 1. DÉTECTION ET ENREGISTREMENT DES CODES RÉPONSES MTI 1110 (Single Pass) ---
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

                # --- 2. DÉTECTION D'UNE NOUVELLE TRANSACTION (scindée par session) ---
                if "Start DumpVisa()" in line:
                    previous_tx = sessions.get(session_id)
                    if previous_tx is not None:
                        save(previous_tx)
                    tx = _new_tx()
                    _add_event(tx, "Message Réseau Entrant (Incoming Visa Request) détecté.")
                    sessions[session_id] = tx
                    continue

                tx = sessions.get(session_id)
                if tx is None:
                    # Ligne appartenant à une session dont on n'a pas encore vu le
                    # "Start DumpVisa()" (début de fichier tronqué) -> on l'ignore
                    # plutôt que de la rattacher à la mauvaise transaction.
                    continue

                # --- FILTRAGE DES HEARTBEATS ---
                if HEARTBEAT_FIELD in line and HEARTBEAT_VALUE in line:
                    tx["is_heartbeat"] = True
                    continue

                # --- EXTRACTION DES IDENTIFIANTS (regex corrigées) ---
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

                # --- 1. RECONSTITUTION DE LA STORY (jalons structurels ISO/TLV) ---
                # On ne déclenche que sur la ligne "End ..." (fin d'exécution réelle),
                # pas sur "Start ..." : avant, les deux matchaient le même mot-clé et
                # dupliquaient chaque jalon.
                message = line.split("|")[-1].strip() if "|" in line else line
                is_end_line = message.startswith("End")

                if is_end_line and "IsoToTlv" in line:
                    _add_event(tx, "Conversion des données : Format réseau ISO 8583 vers format interne TLV.")
                if is_end_line and "ValidateTlvData" in line:
                    _add_event(tx, "Contrôle structurel : Validation du format des données TLV.")
                if is_end_line and "LoadIssuerInfo" in line:
                    _add_event(tx, "Traitement : Chargement des paramètres de la banque émettrice.")

                # --- 2. SURVEILLANCE ET CHRONOLOGIE DES FONCTIONS MÉTIER (SUCCÈS OU ÉCHEC) ---
                # Piloté dynamiquement par Spec_PowerCARD.xlsx
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
                            # C'est un succès (ligne End et aucun motif d'erreur NOK / négatif détecté)
                            res_match = re.search(rf"{re.escape(func_name)}\s*\(\s*([^)]*)\)", line)
                            res_str = res_match.group(1).strip() if res_match and res_match.group(1) else "OK"
                            _add_event(tx, f"Fonction {func_name}() exécutée avec succès (résultat : {res_str}).")
                            if func_name not in tx["successful_functions"]:
                                tx["successful_functions"].append(func_name)
                        break  # une ligne de log ne référence qu'une seule fonction métier

        # Sauvegarde de toutes les transactions encore ouvertes en fin de fichier
        for tx in sessions.values():
            save(tx)

    except Exception as e:
        print(f"Erreur : {str(e)}")
        return []

    return all_transactions


def parse_and_format_log_file(file_path: str) -> str:
    """
    Parses a log file using parse_trace_file_for_story and returns a formatted
    text representation of its transactions.
    """
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
