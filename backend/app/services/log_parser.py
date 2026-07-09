import re

from app.services.spec_loader import get_monitored_function_names

# --- Marqueurs structurels du protocole (constantes ISO 8583 / PowerCARD,
#     indépendantes de la spec métier -> ce ne sont pas des "règles métier
#     en dur", juste des repères de format de log) ---
HEARTBEAT_FIELD = "FLD (070)"
HEARTBEAT_VALUE = "[301]"
RESPONSE_FIELD = "FLD (039)"

# Format réel des lignes d'identifiants dans ce type de trace :
#   296 {   TRANSACTION_IDENTIFIER} 015 384329550314997
#   011 {            INTERNAL STAN} 006 593604
#   002 {                      PAN} 016 4058360***047713
# -> la valeur suit l'accolade fermante et la longueur, pas un ":".
RE_TRANSACTION_ID = re.compile(r"TRANSACTION_IDENTIFIER\}\s*\d+\s+(\S+)")
RE_STAN = re.compile(r"INTERNAL STAN\}\s*\d+\s+(\S+)")
RE_PAN = re.compile(r"PAN\}\s*\d+\s+(\S+)")
RE_CARD_NUMBER = re.compile(r"CARD_NUMBER\}\s*\d+\s+(\S+)")
RE_RESPONSE_CODE = re.compile(r"FLD\s*\(039\).*\[(\w+)\]")


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


def parse_trace_file_for_story(file_path: str, spec_path: str = None) -> list:
    all_transactions = []
    function_patterns = _build_function_failure_patterns(spec_path)

    def new_tx():
        return {
            "identifiers": {"transaction_id": None, "stan": None, "pan": None},
            "events": [],
            "alerts": [],
            "failed_functions": [],  # noms EXACTS des fonctions en échec (évite le parsing par sous-chaîne)
            "is_heartbeat": False,  # Drapeau pour détecter les Echo Tests
        }

    current_tx = new_tx()

    def save_current_transaction():
        # On ne sauvegarde pas si c'est un simple Heartbeat (pour éviter de polluer l'IA)
        if current_tx["is_heartbeat"]:
            return

        if current_tx["events"] or current_tx["identifiers"]["stan"]:
            all_transactions.append({
                "identifiers": current_tx["identifiers"].copy(),
                "chronology": "\n".join(f"- {ev}" for ev in current_tx["events"]),
                "alerts_found": list(current_tx["alerts"]),
                "failed_functions": list(current_tx["failed_functions"]),
            })

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()

                # --- DÉTECTION D'UNE NOUVELLE TRANSACTION ---
                if "Start DumpVisa()" in line:
                    save_current_transaction()
                    current_tx = new_tx()
                    current_tx["events"].append("Message Réseau Entrant (Incoming Visa Request) détecté.")
                    continue

                # --- FILTRAGE DES HEARTBEATS ---
                if HEARTBEAT_FIELD in line and HEARTBEAT_VALUE in line:
                    current_tx["is_heartbeat"] = True
                    continue

                # --- EXTRACTION DES IDENTIFIANTS (regex corrigées) ---
                match = RE_TRANSACTION_ID.search(line)
                if match:
                    current_tx["identifiers"]["transaction_id"] = match.group(1)

                match = RE_STAN.search(line)
                if match:
                    current_tx["identifiers"]["stan"] = match.group(1)

                match = RE_PAN.search(line) or RE_CARD_NUMBER.search(line)
                if match:
                    current_tx["identifiers"]["pan"] = match.group(1)

                # --- 1. RECONSTITUTION DE LA STORY (jalons structurels ISO/TLV) ---
                if "IsoToTlv" in line:
                    current_tx["events"].append("Conversion des données : Format réseau ISO 8583 vers format interne TLV.")
                if "ValidateTlvData" in line:
                    current_tx["events"].append("Contrôle structurel : Validation du format des données TLV.")
                if "LoadIssuerInfo" in line:
                    current_tx["events"].append("Traitement : Chargement des paramètres de la banque émettrice.")

                # --- 2. SURVEILLANCE DES ALERTES (pilotée dynamiquement par Spec_PowerCARD.xlsx) ---
                for func_name, pattern in function_patterns.items():
                    if func_name not in line:
                        continue
                    match = pattern.search(line)
                    if match:
                        code = match.group(1)
                        anomalie = f"{func_name}() a échoué (résultat : {code})."
                        current_tx["events"].append(f"ALERTE : {anomalie}")
                        current_tx["alerts"].append(anomalie)
                        if func_name not in current_tx["failed_functions"]:
                            current_tx["failed_functions"].append(func_name)
                    break  # une ligne de log ne référence qu'une seule fonction métier

                # --- 3. MESSAGE SORTANT (FIN) ---
                if RESPONSE_FIELD in line:
                    match = RE_RESPONSE_CODE.search(line)
                    resp_code = match.group(1) if match else "Inconnu"
                    current_tx["events"].append(
                        f"Message Réseau Sortant (Outgoing Response) généré avec le Code Réponse [FLD 039] = {resp_code}."
                    )

        # Sauvegarde de la dernière transaction
        save_current_transaction()

    except Exception as e:
        print(f"Erreur : {str(e)}")
        return []

    return all_transactions