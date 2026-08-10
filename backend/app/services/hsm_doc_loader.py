"""
Documentation des erreurs / codes HSM (payShield Core Host Commands).

Sources (par ordre de priorité) :
  1. RAG session (PDF joint / placeholder de session)
  2. RAG global (chunks déjà indexés, ex. PUGD0537)
  3. Fichier local PUGD0537-004 Core Host Commands V1.pdf dans storage/
  4. Placeholder JSON backend/app/data/hsm_error_placeholder.json
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_APP_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = _BACKEND_DIR / "app" / "storage"
PUGD_PDF_NAME = "PUGD0537-004 Core Host Commands V1.pdf"
PUGD_PDF_PATH = STORAGE_DIR / PUGD_PDF_NAME
PLACEHOLDER_PATH = _APP_DIR / "data" / "hsm_error_placeholder.json"

_HSM_CODE_RE = re.compile(
    r"(?:"
    r"Code d'erreur HSM\s+([A-Za-z0-9]+)|"
    r"HsmResultCode\s*[:=]?\s*\[?([A-Za-z0-9]+)|"
    r"Erreur HSM[^\dA-Za-z]*([A-Za-z]{2}\d{2}|\d{2,3}|[A-Za-z]{2})|"
    r"\b(?:FROM\s+HSM|TO\s+HSM)[^\n]*?\b([A-Z]{2}\d{0,2})\b|"
    r"\b([A-Z]{2}\d{2})\b|"
    r"\bED\s*[_\-]?\s*(\d{2})\b"
    r")",
    re.IGNORECASE,
)


def parse_hsm_code(raw: str) -> Dict[str, Optional[str]]:
    """
    Normalise un code HSM libre :
      '05' / 'ED05' / 'ED' / 'Erreur HSM ... 05' →
      { lookup_key, command_code, response_code, error_number, display }
    """
    text = (raw or "").strip()
    if not text:
        return {
            "lookup_key": "",
            "command_code": None,
            "response_code": None,
            "error_number": None,
            "display": "",
        }

    # Extraction depuis une phrase d'alerte
    m = _HSM_CODE_RE.search(text)
    token = None
    if m:
        token = next((g for g in m.groups() if g), None)
    if not token:
        token = text.split()[-1].strip(".:[]()\"'")

    token = str(token).strip().upper()
    # ED_05 → ED05
    token = token.replace("_", "").replace("-", "").replace(" ", "")

    command_code = None
    response_code = None
    error_number = None

    if re.fullmatch(r"[A-Z]{2}\d{2}", token):
        response_code = token[:2]
        error_number = token[2:]
        lookup_key = token
    elif re.fullmatch(r"[A-Z]{2}", token):
        response_code = token
        lookup_key = token
    elif re.fullmatch(r"\d{1,3}", token):
        error_number = token.zfill(2) if len(token) <= 2 else token
        lookup_key = error_number
    else:
        lookup_key = token

    # Résoudre commande ↔ réponse via le mapping
    try:
        from app.rag.retriever import _load_command_response_map
        cmd_map = _load_command_response_map()
        inv_map = {v: k for k, v in cmd_map.items()}
        if response_code and response_code in inv_map:
            command_code = inv_map[response_code]
        elif response_code and response_code in cmd_map:
            command_code = response_code
            response_code = cmd_map[response_code]
        elif lookup_key in cmd_map:
            command_code = lookup_key
            response_code = cmd_map[lookup_key]
        elif lookup_key in inv_map:
            command_code = inv_map[lookup_key]
            response_code = lookup_key
    except Exception:
        pass

    display = lookup_key
    if response_code and error_number and not lookup_key.startswith(response_code):
        display = f"{response_code}{error_number}"
    elif response_code and command_code:
        display = f"{command_code} → {response_code}" + (f" / {error_number}" if error_number else "")

    return {
        "lookup_key": lookup_key,
        "command_code": command_code,
        "response_code": response_code,
        "error_number": error_number,
        "display": display or lookup_key,
    }


def extract_hsm_code_from_text(text: str) -> Optional[str]:
    """Retourne un code HSM utilisable pour l'API doc, ou None."""
    if not text:
        return None
    lower = text.lower()
    if not any(k in lower for k in ("hsm", "hsmresult", "from hsm", "to hsm", "erreur hsm")):
        # Accepte aussi un token pur type ED05
        if not re.search(r"\b[A-Z]{2}\d{2}\b|\bED\b|\bEC\b", text, re.I):
            return None
    parsed = parse_hsm_code(text)
    return parsed["lookup_key"] or None


@functools.lru_cache(maxsize=1)
def _load_placeholder() -> dict:
    if not PLACEHOLDER_PATH.exists():
        return {}
    try:
        with open(PLACEHOLDER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[WARN] hsm_error_placeholder.json illisible: {e}")
        return {}


def _placeholder_entry(parsed: Dict[str, Optional[str]]) -> Optional[dict]:
    data = _load_placeholder()
    keys = [
        parsed.get("lookup_key"),
        parsed.get("display"),
        (parsed.get("response_code") or "") + (parsed.get("error_number") or ""),
        parsed.get("error_number"),
        parsed.get("response_code"),
        parsed.get("command_code"),
    ]
    for k in keys:
        if k and str(k) in data:
            return data[str(k)]
        if k and str(k).upper() in data:
            return data[str(k).upper()]
        if k and str(k).lstrip("0") in data:
            return data[str(k).lstrip("0")]
    return None


def _docs_from_rag(parsed: Dict[str, Optional[str]], session_id: Optional[str]) -> List[Any]:
    from app.rag.retriever import query_command_code

    tokens = []
    for t in (
        parsed.get("response_code"),
        parsed.get("command_code"),
        parsed.get("lookup_key"),
    ):
        if t and t not in tokens:
            tokens.append(t)

    # Si code numérique seul, tenter des réponses courantes ED/CX/…
    if parsed.get("error_number") and not parsed.get("response_code"):
        for resp in ("ED", "CX", "ND", "MB"):
            if resp not in tokens:
                tokens.append(resp)

    collected = []
    seen = set()

    # 1) Session d'abord, 2) global (session_id=None)
    for sid in ((session_id or "").strip() or None, None):
        for tok in tokens:
            if len(tok) == 2 and tok.isalpha():
                docs = query_command_code(tok, session_id=sid, limit=6)
            else:
                # Recherche via le token 2 lettres si ED05
                letter = tok[:2] if len(tok) >= 2 and tok[:2].isalpha() else tok
                docs = query_command_code(letter, session_id=sid, limit=6) if letter else []
            for d in docs:
                key = (d.page_content[:120], d.metadata.get("page"), d.metadata.get("source"))
                if key in seen:
                    continue
                # Filtrer sur le numéro d'erreur si présent
                err_n = parsed.get("error_number")
                if err_n and err_n not in d.page_content and f" {err_n.lstrip('0')} " not in f" {d.page_content} ":
                    # garder quand même si tableau d'erreurs générique
                    if "error" not in d.page_content.lower() and "parity" not in d.page_content.lower():
                        continue
                seen.add(key)
                collected.append(d)
        if collected:
            break
    return collected


@functools.lru_cache(maxsize=64)
def _search_pugd_pdf(lookup_key: str, error_number: str, response_code: str, command_code: str) -> Tuple[dict, ...]:
    """Extrait les pages du PDF PUGD contenant le code recherché."""
    if not PUGD_PDF_PATH.exists():
        return tuple()

    needles = [n for n in {lookup_key, error_number, response_code, command_code, (response_code or "") + (error_number or "")} if n]
    if not needles:
        return tuple()

    try:
        import pdfplumber
    except ImportError:
        return tuple()

    hits = []
    try:
        with pdfplumber.open(str(PUGD_PDF_PATH)) as pdf:
            for idx, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                if not text.strip():
                    continue
                upper = text.upper()
                if not any(str(n).upper() in upper for n in needles):
                    continue
                # Scorer : numéro d'erreur + code réponse > présence simple
                score = 0
                if error_number and error_number in text:
                    score += 3
                if response_code and response_code in upper:
                    score += 2
                if command_code and command_code in upper:
                    score += 1
                if "error" in text.lower() or "response" in text.lower():
                    score += 1
                hits.append({
                    "page": idx,
                    "score": score,
                    "content": text.strip()[:2500],
                    "source": PUGD_PDF_NAME,
                })
    except Exception as e:
        print(f"[WARN] PUGD PDF search failed: {e}")
        return tuple()
    hits.sort(key=lambda h: (-h["score"], h["page"]))
    return tuple(hits[:4])


# ── LLM synthesis cache (in-memory, by lookup_key) ───────────────────────────
_LLM_HSM_CACHE: Dict[str, Any] = {}


def clean_pagination_artifacts(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        l_strip = line.strip()
        # Supprimer les marqueurs de page
        if re.match(r"^--- Page \d+ ---$", l_strip):
            continue
        if re.match(r"^--- Début page suivante.*$", l_strip):
            continue
        if re.match(r"^\[CORRESPONDANCE RAG.*\]$", l_strip):
            continue
        if re.match(r"^\[Le code de réponse.*\]$", l_strip):
            continue
        if "payShield 10K Core Host Commands" in l_strip:
            continue
        if "Thales Group" in l_strip and "Page" in l_strip:
            continue
        if "All Rights Reserved" in l_strip:
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def score_excerpt(ex: dict, cmd_code: Optional[str], resp_code: Optional[str]) -> float:
    content = (ex.get("content") or "").upper()
    score = 0.0
    
    meta_cmd = (ex.get("command_code") or "").upper()
    meta_resp = (ex.get("response_code") or "").upper()
    
    # Si les métadonnées mentionnent une AUTRE commande, c'est probablement hors-sujet
    if cmd_code:
        if meta_cmd and meta_cmd != cmd_code:
            score -= 100.0
        if meta_resp and meta_resp != resp_code:
            score -= 100.0
            
    # Présence des codes commande/réponse comme jetons indépendants dans le texte
    if cmd_code and re.search(r'\b' + re.escape(cmd_code) + r'\b', content):
        score += 20.0
    if resp_code and re.search(r'\b' + re.escape(resp_code) + r'\b', content):
        score += 20.0
        
    # Indices indiquant qu'il s'agit d'une table d'erreur
    if "ERROR CODE" in content or "RESPONSE CODE" in content:
        score += 15.0
    if "NO ERROR" in content:
        score += 10.0
        
    # Contient la structure d'une table d'erreur comme '01' ou '10' avec description
    if re.search(r"'\d{2}':", content) or re.search(r"'\d{2}'\s*:", content):
        score += 15.0
        
    # Pénaliser les chunks qui mentionnent d'autres chapitres hors-sujet s'ils ne concernent pas la commande demandée
    if "AS2805" in content and (cmd_code != "A0" and cmd_code != "A2"):
        score -= 30.0
        
    # Pénaliser la Table des Matières
    if "VERIFY AN INTERCHANGE PIN USING THE ABA PVV METHOD" in content and "275" in content:
        score -= 5.0
        
    return score


def _build_llm_synthesis(parsed: Dict[str, Optional[str]], excerpts: List[dict], placeholder_block: Optional[dict]) -> Optional[dict]:
    """
    Envoie le contenu filtré et nettoyé au LLM Gemini
    et retourne une synthèse structurée en JSON.
    """
    cache_key = parsed.get("lookup_key", "") or ""
    if cache_key in _LLM_HSM_CACHE:
        return _LLM_HSM_CACHE[cache_key]

    cmd = (parsed.get("command_code") or "").upper() or "?"
    resp = (parsed.get("response_code") or "").upper() or "?"
    err_n = parsed.get("error_number") or "?"

    # 1) Nettoyer et scorer les extraits
    scored_exs = []
    for ex in excerpts:
        content_cleaned = clean_pagination_artifacts(ex.get("content") or "")
        ex_copy = dict(ex)
        ex_copy["content"] = content_cleaned
        
        score = score_excerpt(ex_copy, parsed.get("command_code"), parsed.get("response_code"))
        # Exclure les extraits avec un score fortement négatif (comme d'autres commandes)
        if score >= -20:
            scored_exs.append((score, ex_copy))
            
    # Trier par score décroissant
    scored_exs.sort(key=lambda x: x[0], reverse=True)
    
    # Limiter aux 1-2 extraits les plus pertinents pour le LLM
    filtered_excerpts = [ex for score, ex in scored_exs[:2]]

    # Assembler le contenu brut
    raw_parts: List[str] = []

    # Placeholder d'abord (données connues, nettoyées)
    if placeholder_block:
        ph_text = (
            f"Code HSM : {parsed.get('display', '')}\n"
            f"Description : {placeholder_block.get('description', '')}\n"
            f"Signification : {placeholder_block.get('meaning', '')}\n"
            f"Piste diagnostic : {placeholder_block.get('diagnostic_hint', '')}"
        )
        raw_parts.append(ph_text)

    for ex in filtered_excerpts:
        content = (ex.get("content") or "").strip()
        src = ex.get("source", "")
        if content:
            raw_parts.append(f"[Source: {src}]\n{content}")

    if not raw_parts:
        return None

    combined_raw = "\n\n---\n\n".join(raw_parts)
    display = parsed.get("display") or parsed.get("lookup_key") or "?"

    try:
        from app.core.agent_graph import llm
        from app.services.llm_util import invoke_llm_with_retry
        from langchain_core.prompts import ChatPromptTemplate
        import json as _json

        hsm_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "Tu es un expert en sécurité et cryptographie sur les HSM Thales payShield (Core Host Commands).\n"
                "À partir des informations brutes fournies sur un code / erreur HSM, génère un OBJET JSON STRICTEMENT VALIDE.\n"
                "\n"
                "CONSTRAINTES STRICTES :\n"
                "1. Utilise EXCLUSIVEMENT le nom de fonction qui apparaît explicitement dans les extraits fournis (souvent en tête de section, motif 'Verify a/an [...] Using the [...] Method' ou similaire).\n"
                "2. N'invente JAMAIS de sigle technique (ARQC, CVV, EMV, etc.) absent du texte source.\n"
                "3. Si le nom exact n'est pas clairement identifiable dans les extraits, utilise exactement la chaîne de caractères suivante : 'nom de fonction non clairement identifié dans les extraits disponibles'. N'invente jamais de nom de fonction.\n"
                "4. Extrais la table des codes d'erreur possibles de manière extrêmement fidèle et exhaustive, ligne par ligne, depuis le texte source (ex: '00', '01', '10', '11', '17', '27', '68', '69' etc. avec leur libellé exact).\n"
                "5. Pour 'diagnostic_hint', fournis une phrase de piste de diagnostic générique ou spécifique de résolution (ex: 'vérifier le sous-code d'erreur retourné pour identifier la cause précise').\n"
                "\n"
                "Format de sortie JSON attendu (aucune balise markdown, aucun texte avant ou après, pas de fioritures) :\n"
                "{{\n"
                '  "command_response": "<Code de commande → Code de réponse, ex: EC → ED>",\n'
                '  "function_name": "<Nom exact de la fonction extrait littéralement du texte source>",\n'
                '  "description": "<Description courte de 1-2 phrases sur le rôle de la commande>",\n'
                '  "error_codes": [\n'
                '    {{"code": "XX", "meaning": "<Libellé exact de l\'erreur>"}}\n'
                '  ],\n'
                '  "diagnostic_hint": "<Conseil ou piste de diagnostic, ex: vérifier le sous-code d\'erreur retourné pour identifier la cause précise>"\n'
                "}}"
            )),
            ("user", (
                "Code HSM : {display}\n"
                "Commande : {cmd} | Réponse : {resp} | Numéro erreur : {err_n}\n\n"
                "Documentation brute disponible :\n{raw_doc}"
            )),
        ])

        llm_resp = invoke_llm_with_retry(
            llm,
            hsm_prompt.format_messages(
                display=display, cmd=cmd, resp=resp, err_n=err_n,
                raw_doc=combined_raw[:5000]
            )
        )
        content_val = getattr(llm_resp, "content", llm_resp)
        if isinstance(content_val, list):
            parts = []
            for part in content_val:
                if isinstance(part, dict) and "text" in part:
                    parts.append(part["text"])
                elif isinstance(part, str):
                    parts.append(part)
            resp_text = "".join(parts).strip()
        else:
            resp_text = str(content_val or "").strip()
        
        # Nettoyer les balises markdown éventuelles
        if resp_text.startswith("```"):
            import re
            resp_text = re.sub(r"^```(?:json)?\s*", "", resp_text, flags=re.IGNORECASE)
            resp_text = re.sub(r"\s*```$", "", resp_text).strip()
            
        parsed_json = _json.loads(resp_text)
        if isinstance(parsed_json, dict) and "function_name" in parsed_json:
            _LLM_HSM_CACHE[cache_key] = parsed_json
            return parsed_json
    except Exception as e:
        print(f"[WARN] HSM LLM synthesis failed for '{display}': {e}\nRaw LLM response was:\n{resp_text if 'resp_text' in locals() else 'None'}")

    return None


def lookup_hsm_documentation(code: str, session_id: Optional[str] = None) -> dict:
    """
    Point d'entrée principal pour GET /api/v1/hsm/{code}/doc.
    Retourne la documentation HSM enrichie par LLM (synthèse structurée).
    """
    parsed = parse_hsm_code(code)
    if not parsed.get("lookup_key"):
        return {
            "found": False,
            "code": code,
            "message": "Code HSM invalide ou manquant.",
            "sources": [],
            "excerpts": [],
            "llm_synthesis": None,
        }

    excerpts: List[dict] = []
    sources: List[str] = []

    # 1 + 2 : RAG session puis global
    try:
        rag_docs = _docs_from_rag(parsed, session_id)
        for d in rag_docs[:5]:
            src = d.metadata.get("source") or "Référentiel HSM (RAG)"
            page = d.metadata.get("page")
            label = f"{src}" + (f" (p. {page})" if page else "")
            excerpts.append({
                "source": label,
                "page": page,
                "command_code": d.metadata.get("command_code") or parsed.get("command_code"),
                "response_code": d.metadata.get("response_code") or parsed.get("response_code"),
                "content": d.page_content.strip()[:2500],
                "origin": "rag_session" if session_id and session_id in str(d.metadata.get("session_id", "")) else "rag",
            })
            if label not in sources:
                sources.append(label)
    except Exception as e:
        print(f"[WARN] HSM RAG lookup failed: {e}")

    # 3 : PDF local PUGD0537 (seulement si aucun extrait RAG n'a été trouvé pour éviter le scan très lourd de 746 pages)
    if not excerpts:
        pdf_hits = _search_pugd_pdf(
            parsed.get("lookup_key") or "",
            parsed.get("error_number") or "",
            parsed.get("response_code") or "",
            parsed.get("command_code") or "",
        )
        for h in pdf_hits:
            label = f"{h['source']} (p. {h['page']})"
            excerpts.append({
                "source": label,
                "page": h["page"],
                "command_code": parsed.get("command_code"),
                "response_code": parsed.get("response_code"),
                "content": h["content"],
                "origin": "pugd_pdf",
            })
            if label not in sources:
                sources.append(label)

    # 4 : Placeholder JSON
    ph = _placeholder_entry(parsed)
    placeholder_block = None
    if ph:
        placeholder_block = {
            "title": ph.get("title") or f"Code HSM {parsed['display']}",
            "description": ph.get("description") or "",
            "meaning": ph.get("meaning") or ph.get("error_meaning") or "",
            "diagnostic_hint": ph.get("diagnostic_hint") or "",
            "source": ph.get("source") or "hsm_error_placeholder.json",
        }
        src_label = placeholder_block["source"]
        if src_label not in sources:
            sources.append(src_label)

    found = bool(excerpts) or bool(placeholder_block)

    # 5 : Synthèse LLM (à partir des extraits + placeholder)
    llm_synthesis = None
    if found:
        try:
            llm_synthesis = _build_llm_synthesis(parsed, excerpts, placeholder_block)
        except Exception as e:
            print(f"[WARN] HSM LLM synthesis call failed: {e}")

    if not found:
        return {
            "found": False,
            "code": parsed["lookup_key"],
            "display": parsed["display"],
            "command_code": parsed.get("command_code"),
            "response_code": parsed.get("response_code"),
            "error_number": parsed.get("error_number"),
            "message": (
                f"Aucune documentation HSM trouvée pour le code '{parsed['display']}' "
                f"dans le référentiel RAG, le fichier {PUGD_PDF_NAME}, ni le placeholder local."
            ),
            "doc_title": PUGD_PDF_NAME,
            "sources": [],
            "excerpts": [],
            "placeholder": None,
            "llm_synthesis": None,
        }

    return {
        "found": True,
        "code": parsed["lookup_key"],
        "display": parsed["display"],
        "command_code": parsed.get("command_code"),
        "response_code": parsed.get("response_code"),
        "error_number": parsed.get("error_number"),
        "doc_title": PUGD_PDF_NAME,
        "sources": sources,
        "excerpts": excerpts,
        "placeholder": placeholder_block,
        "llm_synthesis": llm_synthesis,
        "message": None,
    }
