import os
import shutil
import html
import re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Import de ton application LangGraph compilée
from app.core.agent_graph import compliance_agent_app

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
        
        execution_result = compliance_agent_app.invoke(graph_inputs)
        
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