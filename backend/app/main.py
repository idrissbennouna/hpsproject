import os
import shutil
import html
import re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import de ton application LangGraph compilée
from app.core.agent_graph import compliance_agent_app
from app.core.validation_agent_graph import validation_agent_app
from pydantic import BaseModel, Field
from typing import List, Optional

app = FastAPI(
    title="ComplianceVerifier API - HPS",
    description="Backend d'analyse agentique de logs monétiques et de spécifications",
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

# Résolution du dossier storage pour sauvegarder les fichiers téléversés
CURRENT_DIR = Path(__file__).resolve().parent
STORAGE_DIR = CURRENT_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


# 2. Route de base
@app.get("/")
def read_root():
    return {"status": "online", "message": "Serveur ComplianceVerifier opérationnel"}


# 3. Route principale : Analyse de Logs par le Système Multi-Agents
@app.post("/api/v1/logs/analyze")
async def analyze_logs(
    user_prompt: str = Form(...), 
    file: UploadFile = File(...)
):
    """
    Reçoit un fichier de traces .TXT et un prompt utilisateur,
    sauvegarde le fichier localement, l'analyse via LangGraph + Gemini,
    et génère un rapport PDF d'audit technique exclusif pour les testeurs HPS.
    """
    if not file.filename.endswith('.TXT') and not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers de traces au format .TXT sont acceptés.")
    
    target_file_path = STORAGE_DIR / file.filename
    
    try:
        with target_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec de l'écriture du fichier : {str(e)}")
        
    try:
        # 1. Lancement de ton architecture agentique LangGraph
        graph_inputs = {
            "user_prompt": user_prompt,
            "file_name": file.filename,
            "current_agent": "",
            "rag_context": "",
            "log_data_json": "",
            "final_response": ""
        }
        
        execution_result = await run_in_threadpool(compliance_agent_app.invoke, graph_inputs)
        
        final_report_text = execution_result.get("final_response", "Aucun rapport généré.")
        agent_assigned = execution_result.get("current_agent", "ComplianceAuditorAgent")
        
        # 2. Génération du PDF avec design Corporate HPS (Dédié Testeurs & QA)
        pdf_path = STORAGE_DIR / "Rapport_Compliance_HPS.pdf"
        
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
            
            # Configuration du document avec des marges pro
            doc = SimpleDocTemplate(
                str(pdf_path), 
                pagesize=letter, 
                rightMargin=54, leftMargin=54, 
                topMargin=54, bottomMargin=54
            )
            story = []
            styles = getSampleStyleSheet()
            
            # --- Charte Graphique HPS ---
            title_style = ParagraphStyle(
                'DocTitle', 
                parent=styles['Heading1'], 
                fontSize=22, 
                leading=26, 
                textColor=colors.HexColor('#0F172A'), 
                spaceAfter=5,
                alignment=0
            )
            
            section_style = ParagraphStyle(
                'SectionTitle', 
                parent=styles['Heading2'], 
                fontSize=14, 
                leading=18, 
                textColor=colors.HexColor('#1E3A8A'), 
                spaceBefore=18,
                spaceAfter=10,
                keepWithNext=True
            )
            
            body_style = ParagraphStyle(
                'ReportBody', 
                parent=styles['Normal'], 
                fontSize=10, 
                leading=15, 
                textColor=colors.HexColor('#334155'), 
                spaceAfter=8
            )

            header_text_style = ParagraphStyle(
                'HeaderText',
                parent=styles['Normal'],
                fontSize=8,
                leading=10,
                textColor=colors.HexColor('#64748B'),
                alignment=2
            )
            
            table_header_style = ParagraphStyle(
                'TableHeader', 
                parent=body_style, 
                fontSize=10, 
                textColor=colors.white
            )
            
            # --- 0. Insertion du Logo HPS ---
            logo_path = STORAGE_DIR / "HPS_logo.png"
            if logo_path.exists():
                logo_img = Image(str(logo_path), width=100, height=35)
                logo_img.hAlign = 'LEFT'
                story.append(logo_img)
                story.append(Spacer(1, 10))
            
            # --- 1. En-tête Métier ---
            story.append(Paragraph("<b>HPS ComplianceAI Platform</b> — Automated Log Verification Terminal", header_text_style))
            story.append(Spacer(1, 15))
            
            # --- 2. Titre du Document ---
            story.append(Paragraph("Rapport de Validation Monétique", title_style))
            story.append(Paragraph("<font color='#64748B'><i>Analyse automatisée de conformité des traces d'autorisation</i></font>", body_style))
            story.append(Spacer(1, 15))
            
            # --- 3. Tableau de bord technique ---
            meta_data = [
                [Paragraph("<b>Paramètre d'Audit</b>", table_header_style), Paragraph("<b>Valeur / Référence</b>", table_header_style)],
                [Paragraph("Fichier Trace Source", body_style), Paragraph(file.filename, body_style)], 
                [Paragraph("Référence Spécification", body_style), Paragraph("Spec_PowerCARD.xlsx", body_style)],
                [Paragraph("Moteur d'Analyse", body_style), Paragraph(agent_assigned, body_style)],
                [Paragraph("Statut Système", body_style), Paragraph("Analyse Terminée (200 OK)", body_style)]
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
            
            # --- 4. Section : Résultats de l'Analyse Dynamique ---
            story.append(Paragraph("Résultats de l'Analyse Agentique", section_style))
            
            # Traitement sécurisé du texte ligne par ligne
            if isinstance(final_report_text, list):
                print(f"⚠️ [WARNING] final_report_text is a list instead of string! Normalizing list: {final_report_text}")
                parts = []
                for block in final_report_text:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict):
                        parts.append(block.get("text", str(block)))
                    elif hasattr(block, "text"):
                        parts.append(block.text)
                    else:
                        parts.append(str(block))
                final_report_text = "\n".join(parts)
            elif final_report_text is None:
                final_report_text = ""
            else:
                final_report_text = str(final_report_text)

            for line in final_report_text.split("\n"):
                if line.strip():
                    # 1. Échappement HTML global indispensable pour ReportLab
                    safe_line = html.escape(line)
                    
                    # 2. Conversion des structures de titres Markdown
                    if safe_line.strip().startswith("#### "):
                        safe_line = "<b>" + safe_line.replace("#### ", "", 1) + "</b>"
                    
                    # 3. Remplacement propre des puces de listes (* )
                    if safe_line.strip().startswith("* "):
                        safe_line = safe_line.replace("* ", "&bull; ", 1)
                        
                    # 4. Traduction Regex sécurisée du gras (**texte** -> <b>texte</b>)
                    safe_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe_line)
                        
                    # 5. Traduction Regex sécurisée des backticks (`code` -> <b>code</b>)
                    safe_line = re.sub(r'`(.*?)`', r'<b>\1</b>', safe_line)
                    
                    story.append(Paragraph(safe_line, body_style))
            
            doc.build(story)
            
        except Exception as pdf_err:
            print(f"Erreur lors du formatage du PDF professionnel : {str(pdf_err)}")
            # 💡 BLINDAGE : Génération d'un VRAI PDF en cas d'erreur pour éviter l'écran noir du navigateur
            try:
                doc_fail = SimpleDocTemplate(str(pdf_path), pagesize=letter)
                styles_fail = getSampleStyleSheet()
                story_fail = [
                    Paragraph("<b>Rapport d'Audit (Mode Restauré)</b>", styles_fail['Heading1']),
                    Spacer(1, 15)
                ]
                if isinstance(final_report_text, list):
                    print(f"⚠️ [WARNING] final_report_text (fallback) is a list instead of string! Normalizing list: {final_report_text}")
                    parts = []
                    for block in final_report_text:
                        if isinstance(block, str):
                            parts.append(block)
                        elif isinstance(block, dict):
                            parts.append(block.get("text", str(block)))
                        elif hasattr(block, "text"):
                            parts.append(block.text)
                        else:
                            parts.append(str(block))
                    final_report_text = "\n".join(parts)
                elif final_report_text is None:
                    final_report_text = ""
                else:
                    final_report_text = str(final_report_text)

                for raw_line in final_report_text.split("\n"):
                    if raw_line.strip():
                        story_fail.append(Paragraph(html.escape(raw_line), styles_fail['Normal']))
                doc_fail.build(story_fail)
            except Exception as final_err:
                print(f"Échec critique du fallback PDF : {str(final_err)}")
        
        # 3. Réponse JSON
        return {
            "success": True,
            "agent_assigned": agent_assigned,
            "log_chronology": execution_result.get("log_data_json"),
            "analysis_report": final_report_text
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse agentique : {str(e)}")


# 4. Route de téléchargement PDF alignée
@app.get("/api/v1/logs/download-pdf")
async def download_pdf():
    pdf_path = STORAGE_DIR / "Rapport_Compliance_HPS.pdf"
    
    # Si le fichier existe et qu'il contient bien le rapport, on le renvoie direct
    if pdf_path.exists() and pdf_path.stat().st_size > 1000:
        return FileResponse(
            path=str(pdf_path), 
            filename="Rapport_Compliance_HPS.pdf", 
            media_type="application/pdf"
        )
    
    # Si aucun rapport n'a encore été généré par l'analyse
    raise HTTPException(
        status_code=404, 
        detail="Aucun rapport d'analyse disponible. Veuillez d'abord exécuter l'analyse."
    )

# --- CLASSE DE REQUÊTE POUR L'AGENT 2 ---
class ValidationRequest(BaseModel):
    question: str
    chat_history: Optional[List[dict]] = Field(default_factory=list)
    session_id: Optional[str] = None

# 5. Route d'interrogation de l'Agent 2
@app.post("/api/v1/validation/ask")
async def ask_validation_agent(request: ValidationRequest):
    """
    Interroge l'Agent 2 pour poser une question sur les spécifications PowerCARD.
    """
    question = request.question.strip()
    if not question:
        raise HTTPException(
            status_code=400, 
            detail="La question ne peut pas être vide."
        )

    try:
        inputs = {
            "user_question": question,
            "chat_history": request.chat_history,
            "rag_context": "",
            "final_response": "",
            "session_id": request.session_id or "",
            "sources": []
        }
        
        # Invocation du graphe de validation
        result = validation_agent_app.invoke(inputs)
        
        final_response = result.get("final_response", "")
        
        # Normalisation défensive au niveau du controleur API
        if isinstance(final_response, list):
            print(f"⚠️ [WARNING] final_response in ask_validation_agent is a list! Normalizing list: {final_response}")
            parts = []
            for block in final_response:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    parts.append(block.get("text", str(block)))
                elif hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            final_response = "\n".join(parts)
        elif final_response is None:
            final_response = ""
        else:
            final_response = str(final_response)

        # Utilisation des sources structurées définies par retriever_node
        raw_sources = result.get("sources", [])
        sources = [s["label"] for s in raw_sources] if raw_sources else []
 
        return {
            "response": final_response,
            "sources": sources
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'exécution de l'agent de validation : {str(e)}"
        )

# 6. Route d'upload de fichiers éphémères pour l'Agent 2
@app.post("/api/v1/validation/upload")
async def upload_validation_file(
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """
    Reçoit un fichier (.TXT, .PDF, .XLSX), extrait son texte brut, 
    et l'enregistre en mémoire sous le session_id fourni.
    """
    filename = file.filename.lower()
    if not (filename.endswith('.txt') or filename.endswith('.pdf') or filename.endswith('.xlsx')):
        raise HTTPException(
            status_code=400,
            detail="Seuls les formats de fichiers .TXT, .PDF et .XLSX sont supportés."
        )

    try:
        import io
        from app.services.session_storage import add_session_file, compute_file_stats
        
        file_bytes = await file.read()
        content = ""

        # Extraction de texte par type de fichier
        if filename.endswith('.txt'):
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".TXT") as temp_file:
                temp_file.write(file_bytes)
                temp_path = temp_file.name
            try:
                from app.services.log_parser import parse_and_format_log_file
                content = parse_and_format_log_file(temp_path)
                if not content:
                    content = file_bytes.decode("utf-8", errors="ignore")
            finally:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            
        elif filename.endswith('.pdf'):
            import pypdf
            from langchain_core.documents import Document
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            from app.rag.retriever import get_session_vectorstore, delete_session_documents

            pdf_reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            documents = []
            for idx, page in enumerate(pdf_reader.pages, 1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages_text.append(f"[Page {idx}]\n{page_text}")
                    documents.append(Document(
                        page_content=page_text,
                        metadata={
                            "session_id": session_id,
                            "source": file.filename,
                            "page": idx
                        }
                    ))
            content = "\n\n".join(pages_text)
            
            if documents:
                # Nettoyage des anciens documents de la session
                delete_session_documents(session_id)
                
                # Split du texte en chunks
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
                chunks = text_splitter.split_documents(documents)
                
                # Ingestion dans le vectorstore de session
                session_db = get_session_vectorstore()
                session_db.add_documents(chunks)

        elif filename.endswith('.xlsx'):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet_blocks = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                sheet_blocks.append(f"--- Onglet Excel : {sheet_name} ---")
                for r_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                    # Convertit la ligne en texte si non vide
                    row_str = " | ".join([str(val).strip() for val in row if val is not None])
                    if row_str.strip():
                        sheet_blocks.append(f"Ligne {r_idx}: {row_str}")
            content = "\n".join(sheet_blocks)

        # Calcul des stats sur le contenu complet avant troncature
        full_stats = compute_file_stats(content)

        is_rag_file = filename.endswith('.pdf')
        if is_rag_file:
            # Pas besoin de stocker le texte complet brut en mémoire ni de le tronquer pour le RAG
            content = f"[Document PDF indexé dans la base vectorielle RAG de session. Total : {len(documents)} pages.]"
            full_stats["truncated_for_llm"] = False
        else:
            # Limitation de la taille du contenu pour le respect du rate-limit Gemini (max 15 000 char)
            MAX_CHARACTERS = 15000
            was_truncated = len(content) > MAX_CHARACTERS
            full_stats["truncated_for_llm"] = was_truncated
            if was_truncated:
                content = content[:MAX_CHARACTERS] + f"\n\n... [Contenu tronqué pour préserver les limites de jetons de l'API (max {MAX_CHARACTERS} caractères sur {full_stats['char_count']} au total)]"

        # Enregistrement dans la session correspondante
        add_session_file(session_id, file.filename, content, full_stats=full_stats, is_rag=is_rag_file)

        return {
            "success": True,
            "filename": file.filename,
            "message": "Fichier éphémère extrait et chargé dans la session avec succès."
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Échec de l'extraction ou du stockage du fichier : {str(e)}"
        )

# 7. Endpoint d'usage de tokens
@app.get("/api/v1/usage/summary")
def get_tokens_usage_summary():
    """
    Retourne la consommation cumulée de tokens, le budget et le solde restant.
    """
    try:
        from app.services.token_tracker import get_usage_summary
        return get_usage_summary()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Échec de la récupération du résumé de consommation : {str(e)}"
        )

@app.get("/api/v1/usage/history")
def get_tokens_usage_history(limit: int = 50):
    """
    Retourne l'historique des appels LLM et de la consommation de jetons associée.
    """
    try:
        from app.services.token_tracker import get_usage_history
        return get_usage_history(limit)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Échec de la récupération de l'historique de consommation : {str(e)}"
        )
