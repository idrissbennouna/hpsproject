import re

def parse_trace_file_for_story(file_path: str) -> list:
    """
    Scanne le fichier de logs et regroupe les lignes par bloc de transaction unique.
    Retourne une liste de dictionnaires (un par transaction/autorisation).
    """
    all_transactions = []
    
    # Structure pour stocker la transaction en cours de lecture
    current_tx = {
        "identifiers": {"transaction_id": None, "stan": None, "pan": None},
        "events": [],
        "alerts": []
    }
    
    def save_current_transaction():
        # On ne sauvegarde que si la transaction contient au moins quelques événements
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
                # Si on croise un nouveau "Start", on sauvegarde la précédente et on réinitialise
                if "Start DumpVisa()" in line:
                    save_current_transaction()
                    current_tx = {
                        "identifiers": {"transaction_id": None, "stan": None, "pan": None},
                        "events": ["Message Réseau Entrant (Incoming Visa Request) détecté."],
                        "alerts": []
                    }
                    continue

                # Extraction des identifiants au fil de l'eau
                if "TRANSACTION_IDENTIFIER" in line:
                    match = re.search(r"TRANSACTION_IDENTIFIER\s*:\s*(\d+)", line)
                    if match: current_tx["identifiers"]["transaction_id"] = match.group(1)
                    
                if "INTERNAL STAN" in line:
                    match = re.search(r"INTERNAL STAN\s*:\s*(\d+)", line)
                    if match: current_tx["identifiers"]["stan"] = match.group(1)

                # --- 1. Reconstitution de la Story (Jalons) ---
                if "IsoToTlv" in line:
                    current_tx["events"].append("Conversion des données : Format réseau ISO 8583 vers format interne TLV.")
                elif "ValidateTlvData" in line:
                    current_tx["events"].append("Contrôle structurel : Validation du format des données TLV.")
                elif "LoadIssuerInfo" in line:
                    current_tx["events"].append("Traitement : Chargement des paramètres de la banque émettrice.")
                
                # --- 2. Surveillance des alertes de non-conformité ---
                elif "GetOriginalAuthData" in line and "NOK" in line:
                    anomalie = "GetOriginalAuthData a retourné une exception NOK (-1)."
                    current_tx["events"].append(f"ALERTE : {anomalie}")
                    current_tx["alerts"].append(anomalie + " Impossible de récupérer l'autorisation d'origine (Problème de format TLV ou historique absent).")
                    
                elif any(func in line for func in ["CheckReqTlvFields", "FrdCheckControl", "CheckAuthSecurity", "CheckLimits"]) and "!= OK" in line:
                    match_func = re.search(r"(\w+)\s*\(\s*\)\s*!= OK", line)
                    func_name = match_func.group(1) if match_func else "Contrôle métier"
                    anomalie = f"La fonction {func_name}() a échoué (Résultat != OK)."
                    current_tx["events"].append(f"ALERTE CRITIQUE : {anomalie}")
                    current_tx["alerts"].append(anomalie + " Bascule automatique en mode dégradé (AuthLocal).")
                    
                elif "CardInSaf" in line and "NOK" in line:
                    anomalie = "CardInSaf() a renvoyé NOK (-1)."
                    current_tx["events"].append(f"ALERTE : {anomalie}")
                    current_tx["alerts"].append(anomalie + " Erreur d'identification dans la table Store-and-Forward ou anomalie de routage On-Us.")
                
                # Fin de traitement (Message sortant)
                elif "FLD (039)" in line or "[FLD 039]" in line:
                    match = re.search(r"\[FLD\s*039\]\s*:\s*(\w+)", line)
                    resp_code = match.group(1) if match else "Inconnu"
                    current_tx["events"].append(f"Message Réseau Sortant (Outgoing Response) généré avec le Code Réponse [FLD 039] = {resp_code}.")

        # Ne pas oublier de sauvegarder la toute dernière transaction du fichier
        save_current_transaction()

    except Exception as e:
        print(f"Erreur lors de la lecture du fichier : {str(e)}")
        return []

    return all_transactions