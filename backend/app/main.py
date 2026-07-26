import io
import os
import shutil
import html
import re
import tempfile
import hashlib
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Chargement des variables d'environnement
load_dotenv()

# Importations des applications LangGraph
from app.core.agent_graph import compliance_agent_app
from app.core.validation_agent_graph import validation_agent_app

app = FastAPI(
    title="ComplianceVerifier API - HPS",
    description="Backend d'analyse agentique de logs mon�tiques et de sp�cifications",
    version="1.0.0"
)

# 1. Configuration du CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# R�solution s�curis�e du dossier de stockage
CURRENT_DIR = Path(__file__).resolve().parent
STORAGE_DIR = CURRENT_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


# --- Utilitaires Internes ---

def _normalize_response_text(content: any) -> str:
    """Normalise le contenu textuel renvoy� par les agents (liste, dict, objet ou None)."""
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", str(block)))
            elif hasattr(block, "text"):
                parts.append(getattr(block, "text", str(block)))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _generate_reportlab_pdf(final_report_text: str, agent_assigned: str, filename: str, pdf_path: Path) -> None:
    """G�n�re le rapport PDF s�curis� avec la charte graphique HPS."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=54, leftMargin=54,
        topMargin=54, bottomMargin=54
    )
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontSize=22, leading=26,
        textColor=colors.HexColor('#0F172A'), spaceAfter=5, alignment=0
    )
    section_style = ParagraphStyle(
        'SectionTitle', parent=styles['Heading2'], fontSize=14, leading=18,
        textColor=colors.HexColor('#1E3A8A'), spaceBefore=18, spaceAfter=10, keepWithNext=True
    )
    body_style = ParagraphStyle(
        'ReportBody', parent=styles['Normal'], fontSize=10, leading=15,
        textColor=colors.HexColor('#334155'), spaceAfter=8
    )
    header_text_style = ParagraphStyle(
        'HeaderText', parent=styles['Normal'], fontSize=8, leading=10,
        textColor=colors.HexColor('#64748B'), alignment=2
    )
    table_header_style = ParagraphStyle(
        'TableHeader', parent=body_style, fontSize=10, textColor=colors.white
    )

    logo_path = STORAGE_DIR / "HPS_logo.png"
    if logo_path.exists():
        logo_img = Image(str(logo_path), width=100, height=35)
        logo_img.hAlign = 'LEFT'
        story.append(logo_img)
        story.append(Spacer(1, 10))

    story.append(Paragraph("<b>HPS ComplianceAI Platform</b> � Automated Log Verification Terminal", header_text_style))
    story.append(Spacer(1, 15))
    story.append(Paragraph("Rapport de Validation Mon�tique", title_style))
    story.append(Paragraph("<font color='#64748B'><i>Analyse automatis�e de conformit� des traces d'autorisation</i></font>", body_style))
    story.append(Spacer(1, 15))

    meta_data = [
        [Paragraph("<b>Param�tre d'Audit</b>", table_header_style), Paragraph("<b>Valeur / R�f�rence</b>", table_header_style)],
        [Paragraph("Fichier Trace Source", body_style), Paragraph(filename, body_style)],
        [Paragraph("R�f�rence Sp�cification", body_style), Paragraph("Spec_PowerCARD.xlsx", body_style)],
        [Paragraph("Moteur d'Analyse", body_style), Paragraph(agent_assigned, body_style)],
        [Paragraph("Statut Syst�me", body_style), Paragraph("Analyse Termin�e (200 OK)", body_style)]
    ]

    meta_table = Table(meta_data, colWidths=[160, 340])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#1E3A8A')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
    ]))

    story.append(meta_table)
    story.append(Spacer(1, 15))

    story.append(Paragraph("R�sultats de l'Analyse Agentique", section_style))

    for line in final_report_text.split("\n"):
        if line.strip():
            safe_line = html.escape(line)
            if safe_line.strip().startswith("#### "):
                safe_line = "<b>" + safe_line.replace("#### ", "", 1) + "</b>"
            if safe_line.strip().startswith("* "):
                safe_line = safe_line.replace("* ", "&bull; ", 1)
            safe_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe_line)
            safe_line = re.sub(r'`(.*?)`', r'<b>\1</b>', safe_line)
            story.append(Paragraph(safe_line, body_style))

    doc.build(story)


def _process_and_index_pdf(file_bytes: bytes, filename: str, session_id: str) -> dict:
    """Traite et indexe un fichier PDF pour la session de validation."""
    import pdfplumber
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from app.rag.retriever import (
        get_session_vectorstore,
        delete_session_documents,
        batch_add_documents,
        QuotaExhaustedError,
        find_chunks_by_file_hash,
    )
    from app.core.config import MAX_PDF_PAGES, PDF_CHUNK_SIZE, PDF_CHUNK_OVERLAP, EMBEDDING_BATCH_SIZE, EMBEDDING_BATCH_DELAY_SECONDS

    documents = []
    pages_with_text = 0
    total_pages = 0
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    existing_info = find_chunks_by_file_hash(file_hash)
    existing_chunk_indices = existing_info.get("existing_chunk_indices", set())

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            total_pages = len(pdf.pages)

            if total_pages > MAX_PDF_PAGES:
                return {
                    "success": False,
                    "error_type": "too_many_pages",
                    "filename": filename,
                    "message": f"Le nombre de pages ({total_pages}) d�passe la limite autoris�e de {MAX_PDF_PAGES} pages."
                }

            delete_session_documents(session_id)

            for idx, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages_with_text += 1
                    documents.append(Document(
                        page_content=page_text,
                        metadata={
                            "session_id": session_id,
                            "file_hash": file_hash,
                            "source": filename,
                            "page": idx
                        }
                    ))
    except Exception as pdf_err:
        return {
            "success": False,
            "error_type": "pdf_error",
            "filename": filename,
            "message": f"Fichier PDF invalide ou illisible : {pdf_err}",
            "total_pages": 0,
            "extracted_text": ""
        }

    if total_pages > 0 and (pages_with_text == 0 or (pages_with_text / total_pages) < 0.5):
        msg = (
            "Aucun texte extractible trouv� dans le document PDF. Le fichier est probablement scann�."
            if pages_with_text == 0 else
            f"Seulement {pages_with_text}/{total_pages} pages contiennent du texte extractible. Le document semble majoritairement scann�."
        )
        return {
            "success": False,
            "error_type": "scanned_pdf",
            "filename": filename,
            "message": msg,
            "total_pages": total_pages,
            "extracted_text": ""
        }

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=PDF_CHUNK_SIZE, chunk_overlap=PDF_CHUNK_OVERLAP)
    chunks = text_splitter.split_documents(documents)

    for c_idx, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = c_idx

    if existing_info.get("found") and len(existing_chunk_indices) >= len(chunks):
        print(f"[REUSE_HASH] File '{filename}' (hash: {file_hash[:10]}...) completely embedded ({len(existing_chunk_indices)}/{len(chunks)} chunks). Reusing for session '{session_id}'.")
        return {
            "success": True,
            "reused": True,
            "file_hash": file_hash,
            "filename": filename,
            "message": "Fichier �ph�m�re r�utilis� sans r�-embedding.",
            "total_pages": total_pages,
            "extracted_text": f"[Document PDF index� dans la base vectorielle RAG de session. Total : {total_pages} pages.]"
        }

    missing_chunks = [c for c in chunks if c.metadata["chunk_index"] not in existing_chunk_indices]

    if existing_chunk_indices:
        print(f"[RESUME_HASH] File '{filename}' (hash: {file_hash[:10]}...): Resuming ingestion. {len(existing_chunk_indices)}/{len(chunks)} chunks already present, embedding remaining {len(missing_chunks)} chunks.")

    session_db = get_session_vectorstore()
    try:
        indexed_count = batch_add_documents(
            session_db,
            missing_chunks,
            batch_size=EMBEDDING_BATCH_SIZE,
            inter_batch_delay=EMBEDDING_BATCH_DELAY_SECONDS,
            session_id=session_id
        )
        print(f"[INDEX_SUCCESS] Session '{session_id}': {indexed_count}/{len(missing_chunks)} missing chunks index�s avec succ�s.")
    except QuotaExhaustedError as qe:
        return {
            "success": False,
            "error_type": "quota_exhausted",
            "filename": filename,
            "file_hash": file_hash,
            "indexed": qe.indexed_count,
            "total": len(missing_chunks),
            "message": f"Quota API atteint apr�s l'indexation de {qe.indexed_count}/{len(missing_chunks)} chunks."
        }
    except Exception as e:
        return {
            "success": False,
            "error_type": "ingestion_failed",
            "filename": filename,
            "file_hash": file_hash,
            "message": f"Erreur lors de l'indexation vectorielle du PDF : {str(e)}"
        }

    return {
        "success": True,
        "reused": False,
        "file_hash": file_hash,
        "filename": filename,
        "message": "Fichier �ph�m�re extrait et charg� dans la session avec succ�s.",
        "total_pages": total_pages,
        "extracted_text": f"[Document PDF index� dans la base vectorielle RAG de session. Total : {total_pages} pages.]"
    }


# --- Endpoints API ---

@app.get("/")
def read_root():
    return {"status": "online", "message": "Serveur ComplianceVerifier op�rationnel"}


@app.post("/api/v1/logs/analyze")
async def analyze_logs(
    user_prompt: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Re�oit un fichier de traces (.TXT, .LOG, .TRC, .DAT), analyse son contenu
    via le graphe d'agents et produit un rapport PDF.
    """
    safe_filename = Path(file.filename or "upload").name
    filename_lower = safe_filename.lower()
    is_trace_file = any(filename_lower.endswith(ext) for ext in ('.txt', '.log', '.trc', '.dat')) or '.trc' in filename_lower

    if not is_trace_file:
        raise HTTPException(status_code=400, detail="Seuls les fichiers de traces (.TXT, .LOG, .TRC, .DAT) sont accept�s.")

    target_file_path = STORAGE_DIR / safe_filename

    try:
        with target_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"�chec de l'�criture du fichier : {str(e)}")

    try:
        graph_inputs = {
            "user_prompt": user_prompt,
            "file_name": safe_filename,
            "current_agent": "",
            "rag_context": "",
            "log_data_json": "",
            "final_response": ""
        }

        execution_result = await run_in_threadpool(compliance_agent_app.invoke, graph_inputs)

        raw_report = execution_result.get("final_response", "Aucun rapport g�n�r�.")
        final_report_text = _normalize_response_text(raw_report)
        agent_assigned = execution_result.get("current_agent", "ComplianceAuditorAgent")

        pdf_filename = f"Rapport_{Path(safe_filename).stem}.pdf"
        pdf_path = STORAGE_DIR / pdf_filename

        try:
            await run_in_threadpool(_generate_reportlab_pdf, final_report_text, agent_assigned, safe_filename, pdf_path)
        except Exception as pdf_err:
            print(f"Erreur lors de la g�n�ration du PDF principal : {str(pdf_err)}")
            try:
                from reportlab.lib.pagesizes import letter
                from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet

                doc_fail = SimpleDocTemplate(str(pdf_path), pagesize=letter)
                styles_fail = getSampleStyleSheet()
                story_fail = [
                    Paragraph("<b>Rapport d'Audit (Mode Restaur�)</b>", styles_fail['Heading1']),
                    Spacer(1, 15)
                ]
                for raw_line in final_report_text.split("\n"):
                    if raw_line.strip():
                        story_fail.append(Paragraph(html.escape(raw_line), styles_fail['Normal']))
                doc_fail.build(story_fail)
            except Exception as final_err:
                print(f"�chec critique du fallback PDF : {str(final_err)}")

        return {
            "success": True,
            "agent_assigned": agent_assigned,
            "log_chronology": execution_result.get("log_data_json"),
            "analysis_report": final_report_text,
            "pdf_filename": pdf_filename
        }

    except Exception as e:
        from app.services.llm_util import GeminiOverloadedError, GeminiQuotaExhaustedError
        real_exc = e.__cause__ or e
        if isinstance(real_exc, GeminiOverloadedError):
            raise HTTPException(status_code=503, detail="Le service Gemini est temporairement surcharg�. Veuillez r�essayer dans quelques instants.")
        elif isinstance(real_exc, GeminiQuotaExhaustedError):
            raise HTTPException(status_code=429, detail="Le quota de l'API Gemini a �t� atteint. Veuillez r�essayer plus tard.")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse agentique : {str(e)}")


@app.get("/api/v1/logs/download-pdf")
async def download_pdf(filename: Optional[str] = "Rapport_Compliance_HPS.pdf"):
    """Permet le t�l�chargement du rapport PDF g�n�r�."""
    safe_filename = Path(filename or "Rapport_Compliance_HPS.pdf").name
    pdf_path = STORAGE_DIR / safe_filename

    if pdf_path.exists() and pdf_path.stat().st_size > 1000:
        return FileResponse(
            path=str(pdf_path),
            filename=safe_filename,
            media_type="application/pdf"
        )

    raise HTTPException(
        status_code=404,
        detail="Aucun rapport d'analyse disponible sous ce nom. Veuillez ex�cuter l'analyse au pr�alable."
    )


class ValidationRequest(BaseModel):
    question: str
    chat_history: Optional[List[dict]] = Field(default_factory=list)
    session_id: Optional[str] = None


@app.post("/api/v1/validation/ask")
async def ask_validation_agent(request: ValidationRequest):
    """Interroge l'agent de validation sur les sp�cifications PowerCARD."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="La question ne peut pas �tre vide.")

    try:
        inputs = {
            "user_question": question,
            "chat_history": request.chat_history,
            "rag_context": "",
            "final_response": "",
            "session_id": request.session_id or "",
            "sources": []
        }

        result = await run_in_threadpool(validation_agent_app.invoke, inputs)
        final_response = _normalize_response_text(result.get("final_response", ""))

        raw_sources = result.get("sources", [])
        sources = [s["label"] for s in raw_sources if isinstance(s, dict) and "label" in s] if raw_sources else []

        return {
            "response": final_response,
            "sources": sources
        }

    except Exception as e:
        from app.services.llm_util import GeminiOverloadedError, GeminiQuotaExhaustedError
        real_exc = e.__cause__ or e
        if isinstance(real_exc, GeminiOverloadedError):
            raise HTTPException(status_code=503, detail="Le service Gemini est temporairement surcharg�. Veuillez r�essayer dans quelques instants.")
        elif isinstance(real_exc, GeminiQuotaExhaustedError):
            raise HTTPException(status_code=429, detail="Le quota de l'API Gemini a �t� atteint. Veuillez r�essayer plus tard.")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'ex�cution de l'agent de validation : {str(e)}"
        )


@app.post("/api/v1/validation/upload")
async def upload_validation_file(
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """
    Re�oit un fichier (.TXT, .PDF, .XLSX), extrait son texte brut,
    et l'enregistre en m�moire sous le session_id fourni.
    """
    safe_filename = Path(file.filename or "upload").name
    filename_lower = safe_filename.lower()

    is_trace_file = any(filename_lower.endswith(ext) for ext in ('.txt', '.log', '.trc', '.dat')) or '.trc' in filename_lower
    is_pdf_file = filename_lower.endswith('.pdf')
    is_excel_file = filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls')

    if not (is_trace_file or is_pdf_file or is_excel_file):
        raise HTTPException(
            status_code=400,
            detail="Seuls les formats de fichiers de trace (.TXT, .LOG, .TRC), .PDF et .XLSX sont support�s."
        )

    try:
        from app.services.session_storage import add_session_file, compute_file_stats
        from app.core.config import MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB

        file_bytes = await file.read()

        if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"La taille du fichier ({len(file_bytes) / (1024*1024):.1f} Mo) d�passe la limite autoris�e de {MAX_UPLOAD_SIZE_MB} Mo."
            )

        content = ""
        parsed_log_successfully = False
        file_hash = None

        if is_trace_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".TXT") as temp_file:
                temp_file.write(file_bytes)
                temp_path = temp_file.name

            try:
                from app.services.log_parser import parse_and_format_log_file
                content = parse_and_format_log_file(temp_path)
                if content:
                    parsed_log_successfully = True
                else:
                    content = file_bytes.decode("utf-8", errors="ignore")
                    parsed_log_successfully = False
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        elif is_pdf_file:
            pdf_res = await run_in_threadpool(_process_and_index_pdf, file_bytes, safe_filename, session_id)
            if not pdf_res["success"]:
                status_code = 503 if pdf_res.get("error_type") == "quota_exhausted" else 400
                return JSONResponse(status_code=status_code, content=pdf_res)
            content = pdf_res["extracted_text"]
            file_hash = pdf_res.get("file_hash")

        elif is_excel_file:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet_blocks = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                sheet_blocks.append(f"--- Onglet Excel : {sheet_name} ---")
                for r_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                    row_str = " | ".join([str(val).strip() for val in row if val is not None])
                    if row_str.strip():
                        sheet_blocks.append(f"Ligne {r_idx}: {row_str}")
            content = "\n".join(sheet_blocks)

        full_stats = compute_file_stats(content)
        is_rag_file = is_pdf_file

        if is_rag_file or parsed_log_successfully:
            full_stats["truncated_for_llm"] = False
        else:
            MAX_CHARACTERS = 15000
            was_truncated = len(content) > MAX_CHARACTERS
            full_stats["truncated_for_llm"] = was_truncated
            if was_truncated:
                content = content[:MAX_CHARACTERS] + (
                    f"\n\n... [AVERTISSEMENT : Le parsing structur� du fichier de trace a �chou�. "
                    f"Le contenu brut non structur� est partiel et a �t� tronqu� aux {MAX_CHARACTERS} premiers caract�res "
                    f"sur {full_stats['char_count']} au total.]"
                )

        add_session_file(session_id, safe_filename, content, full_stats=full_stats, is_rag=is_rag_file, file_hash=file_hash)

        return {
            "success": True,
            "filename": safe_filename,
            "message": "Fichier �ph�m�re extrait et charg� dans la session avec succ�s."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"�chec de l'extraction ou du stockage du fichier : {str(e)}"
        )


@app.get("/api/v1/usage/summary")
def get_tokens_usage_summary():
    """Consommation cumul�e de tokens."""
    try:
        from app.services.token_tracker import get_usage_summary
        return get_usage_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"�chec de la r�cup�ration du r�sum� : {str(e)}")


@app.get("/api/v1/usage/history")
def get_tokens_usage_history(limit: int = 50):
    """Historique des appels LLM."""
    try:
        from app.services.token_tracker import get_usage_history
        return get_usage_history(limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"�chec de la r�cup�ration de l'historique : {str(e)}")