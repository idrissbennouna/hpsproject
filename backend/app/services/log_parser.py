import re

def parse_trace_file_for_story(file_path: str) -> dict:
    """
    Scanne le fichier de logs pour extraire la chronologie (Story)
    et isoler les anomalies immédiates.
    """
    events = []
    alerts = []
    
    # Expressions régulières pour capturer les éléments identificateurs clés
    identifiers = {
        "transaction_id": None,
        "stan": None,
        "pan": None
    }

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                # Extraction des identifiants au fil de l'eau si présents
                if "TRANSACTION_IDENTIFIER" in line:
                    match = re.search(r"TRANSACTION_IDENTIFIER\s*:\s*(\d+)", line)
                    if match: identifiers["transaction_id"] = match.group(1)
                if "INTERNAL STAN" in line:
                    match = re.search(r"INTERNAL STAN\s*:\s*(\d+)", line)
                    if match: identifiers["stan"] = match.group(1)

                # --- 1. Reconstitution de la Story (Jalons) ---
                if "Start DumpVisa()" in line:
                    events.append("Message Réseau Entrant (Incoming Visa Request) détecté.")
                elif "IsoToTlv" in line:
                    events.append("Conversion des données : Format réseau ISO 8583 vers format interne TLV.")
                elif "ValidateTlvData" in line:
                    events.append("Contrôle structurel : Validation du format des données TLV.")
                elif "LoadIssuerInfo" in line:
                    events.append("Traitement : Chargement des paramètres de la banque émettrice.")
                
                # --- 2. Surveillance des alertes de non-conformité ---
                elif "GetOriginalAuthData" in line and "NOK" in line:
                    anomalie = "GetOriginalAuthData a retourné une exception NOK (-1)."
                    events.append(f"ALERTE : {anomalie}")
                    alerts.append(anomalie + " Impossible de récupérer l'autorisation d'origine (Problème de format TLV ou historique absent).")
                    
                elif any(func in line for func in ["CheckReqTlvFields", "FrdCheckControl", "CheckAuthSecurity", "CheckLimits"]) and "!= OK" in line:
                    match_func = re.search(r"(\w+)\s*\(\s*\)\s*!= OK", line)
                    func_name = match_func.group(1) if match_func else "Contrôle métier"
                    anomalie = f"La fonction {func_name}() a échoué (Résultat != OK)."
                    events.append(f"ALERTE CRITIQUE : {anomalie}")
                    alerts.append(anomalie + " Bascule automatique en mode dégradé (AuthLocal).")
                    
                elif "CardInSaf" in line and "NOK" in line:
                    anomalie = "CardInSaf() a renvoyé NOK (-1)."
                    events.append(f"ALERTE : {anomalie}")
                    alerts.append(anomalie + " Erreur d'identification dans la table Store-and-Forward ou anomalie de routage On-Us.")
                
                # Fin de traitement
                elif "FLD (039)" in line:
                    match = re.search(r"\[FLD\s*039\]\s*:\s*(\w+)", line)
                    resp_code = match.group(1) if match else "Inconnu"
                    events.append(f"Message Réseau Sortant (Outgoing Response) généré avec le Code Réponse [FLD 039] = {resp_code}.")

    except Exception as e:
        return {"error": f"Erreur lors de la lecture du fichier : {str(e)}"}

    return {
        "identifiers": identifiers,
        "chronology": "\n".join([f"- {ev}" for ev in events]),
        "alerts_found": alerts
    }