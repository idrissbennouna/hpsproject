"""
vip_pdf_ingestor.py — Extraction structurée des champs ISO 8583 depuis le PDF
VIP System BASE I (vip-system-BASE-i-tech-specs-volume-1.pdf).

Ce module parse le PDF officiel VIP System BASE I de Visa/HPS et extrait,
pour chaque champ ISO 8583 décrit (section "Field N—Nom"), :
  - field_number  : numéro du champ (str, ex: "10")
  - field_name    : nom complet (ex: "Conversion Rate, Cardholder Billing")
  - length        : longueur maximale (int)
  - type_code     : code type (ex: "N", "ANS", "AN", "A", "B")
  - format        : format interne (ex: "BCD", "EBCDIC", "ASCII") si disponible
  - source        : "vip-system-BASE-i-tech-specs-volume-1.pdf"

Génère ensuite backend/app/data/vip_system_fields.json.

Usage :
    python -m app.services.vip_pdf_ingestor
    # ou depuis Python :
    from app.services.vip_pdf_ingestor import extract_vip_fields, generate_vip_json
"""

import json
import re
import sys
from pathlib import Path

# ── Chemins par défaut ───────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PDF_PATH = _BACKEND_DIR / "app" / "storage" / "vip-system-BASE-i-tech-specs-volume-1.pdf"
DEFAULT_OUTPUT_PATH = _BACKEND_DIR / "app" / "data" / "vip_system_fields.json"

SOURCE_LABEL = "vip-system-BASE-i-tech-specs-volume-1.pdf"

# ── Patterns de reconnaissance ───────────────────────────────────────────────
# Section header : "Field 10—Conversion Rate, Cardholder Billing"
# ou "4.8 Field 10—Conversion Rate..."
_FIELD_SECTION_RE = re.compile(
    r"Field\s+(\d{1,3})\s*[—\-–]+\s*(.+)",
    re.IGNORECASE
)

# Lignes de tableau récapitulatif :
# "10  Conversion Rate, Cardholder Billing  F  4  8  BCD"
# Colonnes (séparées par ≥2 espaces ou tabulations) :
#   [numéro] [nom] [F/V/A] [longueur_indicateur] [longueur_données] [type/format]
# Variantes :
# "3   Processing Code                6    N"
# "22  Point of Service Entry Mode   3    N"
_TABLE_ROW_RE = re.compile(
    r"^\s*(\d{1,3})\s{2,}"          # numéro de champ
    r"(.+?)\s{2,}"                   # nom (non-greedy)
    r"(?:[FVA]\s{2,})?"              # indicateur fixe/variable optionnel
    r"(?:\d+\s{2,})?"                # longueur de l'indicateur (optionnel)
    r"(\d+)\s{2,}"                   # longueur des données
    r"([A-Z]+(?:\s*,\s*[A-Z0-9 ]+)?)"  # type code (N, ANS, AN, BCD, ...)
    r".*$"
)

# Pattern alternatif plus souple pour les lignes courtes du tableau
_TABLE_ROW_SIMPLE_RE = re.compile(
    r"^\s*(\d{1,3})\s{2,}(.+?)\s{2,}(\d+)\s{2,}([A-Z]{1,4})\b"
)

# Type codes reconnus par le système
_KNOWN_TYPES = {"N", "A", "AN", "ANS", "NS", "AS", "B", "Z"}


def _normalize_type(raw_type: str) -> str:
    """Normalise un type raw du PDF vers le code type connu."""
    t = raw_type.strip().upper()
    # BCD est encodage, pas un type : les champs BCD dans VIP sont de type N
    if "BCD" in t:
        return "N"
    if "EBCDIC" in t or "ASCII" in t:
        # Caractère alphanumérique
        return "ANS"
    # Extraire le premier token reconnu
    for known in ["ANS", "AN", "NS", "AS", "N", "A", "B", "Z"]:
        if t.startswith(known):
            return known
    return t.split()[0][:3] if t else "N"


def _extract_format(raw_type: str) -> str:
    """Extrait le format d'encodage (BCD, EBCDIC, ASCII, Binary) depuis la colonne type."""
    t = raw_type.upper()
    if "BCD" in t:
        return "BCD"
    if "EBCDIC" in t:
        return "EBCDIC"
    if "ASCII" in t:
        return "ASCII"
    if "BINARY" in t or t == "B":
        return "Binary"
    return ""


def extract_vip_fields(pdf_path: Path = None) -> dict:
    """
    Extrait tous les champs ISO 8583 du PDF VIP System BASE I.
    Retourne un dict {field_number_str: {name, length, type_code, format, source}}.
    """
    pdf_path = Path(pdf_path or DEFAULT_PDF_PATH)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF VIP System introuvable : {pdf_path}")

    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber est requis pour parser le PDF VIP System. "
            "Installez-le avec : pip install pdfplumber"
        )

    fields: dict = {}

    # ── STRATÉGIE 1 : Extraction depuis les tables du PDF ───────────────────
    # pdfplumber détecte les vrais tableaux PDF (structure vectorielle).
    # C'est la méthode la plus fiable pour les tableaux récapitulatifs.
    print(f"[INFO] Ouverture du PDF : {pdf_path.name} ({pdf_path.stat().st_size // 1024} Ko)")

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
        print(f"   {total_pages} pages trouvees.")

        for page_num, page in enumerate(pdf.pages, 1):
            # 1a. Essayer l'extraction de tables structurées
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or not row[0]:
                        continue
                    # Chercher les lignes dont la première cellule est un numéro de champ
                    cell0 = str(row[0]).strip()
                    if not cell0.isdigit():
                        continue
                    field_num = cell0
                    if int(field_num) < 1 or int(field_num) > 128:
                        continue

                    # Nom : deuxième cellule
                    field_name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                    if not field_name:
                        continue

                    # Chercher longueur et type dans les cellules suivantes
                    length_val = None
                    type_val = None
                    for cell in row[2:]:
                        if cell is None:
                            continue
                        cell_str = str(cell).strip()
                        if not cell_str:
                            continue
                        if length_val is None and cell_str.isdigit():
                            length_val = int(cell_str)
                        elif type_val is None and re.match(r"^[A-Z]{1,5}", cell_str):
                            type_val = cell_str

                    if length_val and type_val:
                        type_code = _normalize_type(type_val)
                        fmt = _extract_format(type_val)
                        if field_num not in fields:
                            fields[field_num] = {
                                "name": field_name,
                                "length": length_val,
                                "type_code": type_code,
                                "format": fmt,
                                "source": SOURCE_LABEL,
                            }
                            print(f"   [TABLE] Champ {field_num}: {field_name} | {length_val} {type_code} {fmt}")

            # 1b. Extraction texte pour les cas non-détectés par l'extracteur de tables
            text = page.extract_text() or ""
            lines = text.splitlines()
            current_section_field = None

            for line in lines:
                # Détecter les headers de section "Field N—Nom"
                m_section = _FIELD_SECTION_RE.search(line)
                if m_section:
                    current_section_field = m_section.group(1)

                # Essayer de parser une ligne de tableau récapitulatif
                m_row = _TABLE_ROW_RE.match(line) or _TABLE_ROW_SIMPLE_RE.match(line)
                if m_row:
                    fn = m_row.group(1)
                    fname = m_row.group(2).strip()
                    flen = int(m_row.group(3))
                    ftype_raw = m_row.group(4).strip()
                    ftype = _normalize_type(ftype_raw)
                    ffmt = _extract_format(ftype_raw)

                    if fn not in fields and 1 <= int(fn) <= 128 and fname:
                        fields[fn] = {
                            "name": fname,
                            "length": flen,
                            "type_code": ftype,
                            "format": ffmt,
                            "source": SOURCE_LABEL,
                        }
                        print(f"   [TEXT] Champ {fn}: {fname} | {flen} {ftype} {ffmt}")

    print(f"\n[OK] {len(fields)} champs extraits depuis le PDF VIP System.")
    return fields


# ── Champs VIP System BASE I connus (fallback / seed si PDF parsing partiel) ─
# Source : documentation officielle VIP System BASE I, Volume 1, table récap.
# Ces valeurs font autorité sur STANDARD_ISO_FIELDS existant.
VIP_FIELDS_SEED = {
    "1":  {"name": "Bitmap", "length": 8, "type_code": "B", "format": "Binary", "source": SOURCE_LABEL},
    "2":  {"name": "Primary Account Number (PAN)", "length": 19, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "3":  {"name": "Processing Code", "length": 6, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "4":  {"name": "Amount, Transaction", "length": 12, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "5":  {"name": "Amount, Settlement", "length": 12, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "6":  {"name": "Amount, Cardholder Billing", "length": 12, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "7":  {"name": "Transmission Date & Time", "length": 10, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "9":  {"name": "Conversion Rate, Settlement", "length": 8, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "10": {"name": "Conversion Rate, Cardholder Billing", "length": 8, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "11": {"name": "System Trace Audit Number (STAN)", "length": 6, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "12": {"name": "Time, Local Transaction", "length": 6, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "13": {"name": "Date, Local Transaction", "length": 4, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "14": {"name": "Date, Expiration", "length": 4, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "15": {"name": "Date, Settlement", "length": 4, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "16": {"name": "Date, Conversion", "length": 4, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "17": {"name": "Date, Capture", "length": 4, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "18": {"name": "Merchant Type (MCC)", "length": 4, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "19": {"name": "Acquiring Institution Country Code", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "20": {"name": "PAN Country Code", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "21": {"name": "Forwarding Institution Country Code", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "22": {"name": "Point of Service Entry Mode", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "23": {"name": "Card Sequence Number", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "24": {"name": "Function Code (NII)", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "25": {"name": "Point of Service Condition Code", "length": 2, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "26": {"name": "Point of Service PIN Capture Code", "length": 2, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "28": {"name": "Amount, Transaction Fee", "length": 8, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "29": {"name": "Amount, Settlement Fee", "length": 8, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "30": {"name": "Amount, Transaction Processing Fee", "length": 8, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "31": {"name": "Amount, Settlement Processing Fee", "length": 8, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "32": {"name": "Acquiring Institution Identification Code", "length": 11, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "33": {"name": "Forwarding Institution Identification Code", "length": 11, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "35": {"name": "Track 2 Data", "length": 37, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "37": {"name": "Retrieval Reference Number (RRN)", "length": 12, "type_code": "AN", "format": "EBCDIC", "source": SOURCE_LABEL},
    "38": {"name": "Authorization Identification Response", "length": 6, "type_code": "AN", "format": "EBCDIC", "source": SOURCE_LABEL},
    "39": {"name": "Response Code", "length": 2, "type_code": "AN", "format": "EBCDIC", "source": SOURCE_LABEL},
    "40": {"name": "Service Restriction Code", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "41": {"name": "Card Acceptor Terminal Identification", "length": 8, "type_code": "ANS", "format": "EBCDIC", "source": SOURCE_LABEL},
    "42": {"name": "Card Acceptor Identification Code", "length": 15, "type_code": "ANS", "format": "EBCDIC", "source": SOURCE_LABEL},
    "43": {"name": "Card Acceptor Name/Location", "length": 40, "type_code": "ANS", "format": "EBCDIC", "source": SOURCE_LABEL},
    "49": {"name": "Currency Code, Transaction", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "50": {"name": "Currency Code, Settlement", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "51": {"name": "Currency Code, Cardholder Billing", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "52": {"name": "Personal Identification Number (PIN) Data", "length": 8, "type_code": "B", "format": "Binary", "source": SOURCE_LABEL},
    "55": {"name": "Integrated Circuit Card System Related Data", "length": 255, "type_code": "ANS", "format": "Binary", "source": SOURCE_LABEL},
    "70": {"name": "Network Management Information Code", "length": 3, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
    "90": {"name": "Original Data Elements", "length": 42, "type_code": "N", "format": "BCD", "source": SOURCE_LABEL},
}


def generate_vip_json(pdf_path: Path = None, output_path: Path = None) -> dict:
    """
    Génère vip_system_fields.json en combinant :
    1. Le seed VIP_FIELDS_SEED (valeurs de référence connues)
    2. L'extraction PDF (remplace le seed si conflit, pour des champs supplémentaires)
    """
    pdf_path = Path(pdf_path or DEFAULT_PDF_PATH)
    output_path = Path(output_path or DEFAULT_OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Partir du seed, puis enrichir avec le PDF parsé
    final_fields = dict(VIP_FIELDS_SEED)

    if pdf_path.exists():
        try:
            extracted = extract_vip_fields(pdf_path)
            # Les champs extraits du PDF enrichissent/remplacent le seed
            # SEULEMENT si le parsing a retourné des données cohérentes
            pdf_additions = 0
            for fn, fdata in extracted.items():
                if fdata.get("length") and fdata.get("type_code"):
                    if fn not in final_fields:
                        final_fields[fn] = fdata
                        pdf_additions += 1
                    # Si présent dans le seed ET extrait du PDF avec des valeurs différentes,
                    # on garde le PDF comme source de vérité (mais on log le conflit)
                    elif final_fields[fn]["length"] != fdata["length"] or final_fields[fn]["type_code"] != fdata["type_code"]:
                        print(f"   [WARN] Conflit seed<>PDF pour champ {fn}: "
                              f"seed={final_fields[fn]['length']} {final_fields[fn]['type_code']} "
                              f"vs PDF={fdata['length']} {fdata['type_code']} -> PDF retenu")
                        final_fields[fn] = fdata
            print(f"   + {pdf_additions} champs supplementaires extraits du PDF (non presents dans le seed).")
        except Exception as e:
            print(f"[WARN] Extraction PDF echouee ({e}) - utilisation du seed seul.")
    else:
        print(f"[WARN] PDF non trouve ({pdf_path}) - generation depuis le seed seul.")

    # Écrire le JSON final
    output_data = {
        "version": "1.0",
        "source_document": SOURCE_LABEL,
        "description": (
            "Référentiel officiel des champs ISO 8583 extrait du PDF VIP System BASE I. "
            "Ce fichier fait AUTORITÉ sur STANDARD_ISO_FIELDS pour la validation de conformité."
        ),
        "fields": final_fields,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n[SAVED] {len(final_fields)} champs ecrits dans : {output_path}")
    return final_fields


if __name__ == "__main__":
    print("=" * 60)
    print("VIP System BASE I -- Ingesteur de champs ISO 8583")
    print("=" * 60)
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF_PATH
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT_PATH
    result = generate_vip_json(pdf, out)
    print(f"\nResultat : {len(result)} champs disponibles dans le referentiel VIP System.")
