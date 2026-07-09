import re

def parse_trace_file_for_story(file_path: str) -> list:
    all_transactions = []
    
    current_tx = {
        "identifiers": {"transaction_id": None, "stan": None, "pan": None},
        "events": [],
        "alerts": [],
        "is_heartbeat": False  # Drapeau pour détecter les Echo Tests
    }
    
    def save_current_transaction():
        # On ne sauvegarde pas si c'est un simple Heartbeat (pour éviter de polluer l'IA)
        if current_tx["is_heartbeat"]:
            return
            
        if current_tx["events"] or current_tx["identifiers"]["stan"]:
            all_transactions.append({
                "identifiers": current_tx["identifiers"].copy(),
                "chronology": "\n".join([f"- {ev}" for ev in current_tx["events"]]),
                "alerts_found": list(current_tx["alerts"])
            })

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                # --- DÉTECTION D'UNE NOUVELLE TRANSACTION ---
                if "Start DumpVisa()" in line:
                    save_current_transaction()
                    current_tx = {
                        "identifiers": {"transaction_id": None, "stan": None, "pan": None},
                        "events": ["Message Réseau Entrant (Incoming Visa Request) détecté."],
                        "alerts": [],
                        "is_heartbeat": False
                    }
                    continue

                # --- FILTRAGE DES HEARTBEATS ---
                if "FLD (070)" in line and "[301]" in line:
                    current_tx["is_heartbeat"] = True
                    continue

                # --- EXTRACTION DES IDENTIFIANTS ---
                if "TRANSACTION_IDENTIFIER" in line:
                    match = re.search(r"TRANSACTION_IDENTIFIER\s*:\s*(\d+)", line)
                    if match: current_tx["identifiers"]["transaction_id"] = match.group(1)
                    
                if "INTERNAL STAN" in line:
                    match = re.search(r"INTERNAL STAN\s*:\s*(\d+)", line)
                    if match: current_tx["identifiers"]["stan"] = match.group(1)

                if "PAN" in line or "CARD_NUMBER" in line:
                    match = re.search(r"(?:PAN|CARD_NUMBER)\s*:\s*(\d+)", line)
                    if match: current_tx["identifiers"]["pan"] = match.group(1)

                # --- 1. RECONSTITUTION DE LA STORY (IF INDÉPENDANTS) ---
                if "IsoToTlv" in line:
                    current_tx["events"].append("Conversion des données : Format réseau ISO 8583 vers format interne TLV.")
                if "ValidateTlvData" in line:
                    current_tx["events"].append("Contrôle structurel : Validation du format des données TLV.")
                if "LoadIssuerInfo" in line:
                    current_tx["events"].append("Traitement : Chargement des paramètres de la banque émettrice.")
                
                # --- 2. SURVEILLANCE DES ALERTES ---
                if "GetOriginalAuthData" in line and "NOK" in line:
                    anomalie = "GetOriginalAuthData a retourné une exception NOK (-1)."
                    current_tx["events"].append(f"ALERTE : {anomalie}")
                    current_tx["alerts"].append(anomalie + " Impossible de récupérer l'autorisation d'origine.")
                    
                if "!= OK" in line and any(func in line for func in ["CheckReqTlvFields", "FrdCheckControl", "CheckAuthSecurity", "CheckLimits"]):
                    match_func = re.search(r"(\w+)\s*(\(\s*\))?\s*!= OK", line)
                    func_name = match_func.group(1) if match_func else "Contrôle métier"
                    anomalie = f"La fonction {func_name}() a échoué (Résultat != OK)."
                    current_tx["events"].append(f"ALERTE CRITIQUE : {anomalie}")
                    current_tx["alerts"].append(anomalie + " Bascule automatique en mode dégradé (AuthLocal).")
                    
                if "CardInSaf" in line and "NOK" in line:
                    anomalie = "CardInSaf() a renvoyé NOK (-1)."
                    current_tx["events"].append(f"ALERTE : {anomalie}")
                    current_tx["alerts"].append(anomalie + " Erreur dans la table Store-and-Forward ou anomalie de routage On-Us.")
                
                # --- 3. MESSAGE SORTANT (FIN) ---
                if "FLD (039)" in line:
                    match = re.search(r"FLD\s*\(039\).*\[(\w+)\]", line)
                    resp_code = match.group(1) if match else "Inconnu"
                    current_tx["events"].append(f"Message Réseau Sortant (Outgoing Response) généré avec le Code Réponse [FLD 039] = {resp_code}.")

        # Sauvegarde de la dernière transaction
        save_current_transaction()

    except Exception as e:
        print(f"Erreur : {str(e)}")
        return []

    return all_transactions