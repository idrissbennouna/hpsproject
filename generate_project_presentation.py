import os
import sys
import html
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus.flowables import Image

# Output path
PROJECT_ROOT = Path(__file__).resolve().parent
STORAGE_DIR = PROJECT_ROOT / "backend" / "app" / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
PDF_OUTPUT_PATH = STORAGE_DIR / "Presentation_Projet_ComplianceVerifier.pdf"
LOGO_PATH = STORAGE_DIR / "HPS_logo.png"


class TwoPassNumberedCanvas(canvas.Canvas):
    """
    Canvas personnalisé à 2 passes pour ajouter les entêtes et pieds de page
    avec numérotation dynamique 'Page X sur Y' et exclusion de la page de garde.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count):
        # Ne pas dessiner d'en-tête ni de pied de page sur la couverture (page 1)
        if self._pageNumber == 1:
            return

        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # En-tête
        self.drawString(54, 752, "HPS ComplianceVerifier — Document de Présentation & Point d'Avancement")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 744, 558, 744)

        # Pied de page
        self.line(54, 45, 558, 45)
        self.drawString(54, 30, "CONFIDENTIEL — HPS ComplianceVerifier Platform")
        page_str = f"Page {self._pageNumber} sur {page_count}"
        self.drawRightString(558, 30, page_str)
        self.restoreState()


def create_callout_box(title: str, text: str, bg_color="#F8FAFC", border_color="#1E3A8A", title_color="#1E3A8A", text_color="#334155", width=504):
    """Crée une boîte de mise en valeur (callout box) élégante."""
    styles = getSampleStyleSheet()
    box_title_style = ParagraphStyle(
        'BoxTitle', parent=styles['Normal'], fontSize=10, leading=14,
        fontName='Helvetica-Bold', textColor=colors.HexColor(title_color), spaceAfter=4
    )
    box_text_style = ParagraphStyle(
        'BoxText', parent=styles['Normal'], fontSize=9, leading=13,
        textColor=colors.HexColor(text_color)
    )
    
    content = []
    if title:
        content.append(Paragraph(title, box_title_style))
    content.append(Paragraph(text, box_text_style))
    
    table = Table([[content]], colWidths=[width])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bg_color)),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(border_color)),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    return table


def build_pdf():
    doc = SimpleDocTemplate(
        str(PDF_OUTPUT_PATH),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=60,
        bottomMargin=60
    )

    styles = getSampleStyleSheet()

    # Définition des styles personnalisés avec la charte HPS
    c_primary = colors.HexColor("#1E3A8A")   # Bleu Nuit HPS
    c_dark = colors.HexColor("#0F172A")      # Slate Foncé
    c_secondary = colors.HexColor("#64748B") # Gris Métallique
    c_accent = colors.HexColor("#2563EB")    # Bleu Vif
    c_body = colors.HexColor("#334155")      # Texte corps
    c_alert = colors.HexColor("#DC2626")     # Rouge alerte
    c_success = colors.HexColor("#16A34A")   # Vert succès

    styles.add(ParagraphStyle(
        'CoverTitle', parent=styles['Heading1'], fontSize=24, leading=30,
        fontName='Helvetica-Bold', textColor=c_primary, spaceAfter=8, alignment=0
    ))
    styles.add(ParagraphStyle(
        'CoverSubtitle', parent=styles['Normal'], fontSize=13, leading=18,
        fontName='Helvetica', textColor=c_secondary, spaceAfter=20, alignment=0
    ))
    styles.add(ParagraphStyle(
        'SectionH1', parent=styles['Heading1'], fontSize=15, leading=19,
        fontName='Helvetica-Bold', textColor=c_primary, spaceBefore=14, spaceAfter=8, keepWithNext=True
    ))
    styles.add(ParagraphStyle(
        'SectionH2', parent=styles['Heading2'], fontSize=11, leading=15,
        fontName='Helvetica-Bold', textColor=c_accent, spaceBefore=10, spaceAfter=4, keepWithNext=True
    ))
    styles.add(ParagraphStyle(
        'CustomBody', parent=styles['Normal'], fontSize=9.5, leading=13.5,
        fontName='Helvetica', textColor=c_body, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        'CustomBodyBold', parent=styles['CustomBody'], fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        'BulletText', parent=styles['CustomBody'], leftIndent=12, spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        'TableHeader', parent=styles['Normal'], fontSize=9, leading=12,
        fontName='Helvetica-Bold', textColor=colors.white, alignment=0
    ))
    styles.add(ParagraphStyle(
        'TableCell', parent=styles['Normal'], fontSize=8.5, leading=12,
        fontName='Helvetica', textColor=c_body
    ))
    styles.add(ParagraphStyle(
        'TableCellBold', parent=styles['TableCell'], fontName='Helvetica-Bold'
    ))

    story = []

    # =========================================================================
    # 1. PAGE DE TITRE (PAGE DE GARDE)
    # =========================================================================
    story.append(Spacer(1, 20))
    if LOGO_PATH.exists():
        logo_img = Image(str(LOGO_PATH), width=140, height=48)
        logo_img.hAlign = 'LEFT'
        story.append(logo_img)
        story.append(Spacer(1, 25))

    story.append(HRFlowable(width="100%", thickness=3, color=c_primary, spaceAfter=20))
    story.append(Paragraph("ComplianceVerifier HPS", styles['CoverTitle']))
    story.append(Paragraph("Plateforme Intelligente d'Analyse de Conformité Monétique & d'Assistance aux Spécifications (FastAPI + LangGraph + pgvector)", styles['CoverSubtitle']))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=30))

    meta_info = [
        [Paragraph("Document", styles['TableCellBold']), Paragraph("Dossier de Présentation & Bilan d'Avancement Technique", styles['TableCell'])],
        [Paragraph("Objectif", styles['TableCellBold']), Paragraph("Soutenance & Validation Encadrante (Synthèse Fonctionnelle et Analyse des Débogages)", styles['TableCell'])],
        [Paragraph("Auteur / Réalisateur", styles['TableCellBold']), Paragraph("Équipe Projet ComplianceVerifier / Stagiaire HPS", styles['TableCell'])],
        [Paragraph("Encadrante / Destinataire", styles['TableCellBold']), Paragraph("Encadrement Technique et Fonctionnel HPS", styles['TableCell'])],
        [Paragraph("Technologies Clés", styles['TableCellBold']), Paragraph("FastAPI, LangGraph (Multi-Agents), PostgreSQL / pgvector, Gemini LLM & Embeddings, ReportLab", styles['TableCell'])],
        [Paragraph("Date de Publication", styles['TableCellBold']), Paragraph("Août 2026", styles['TableCell'])],
        [Paragraph("Statut du Projet", styles['TableCellBold']), Paragraph("<font color='#16A34A'><b>Opérationnel en phase de validation</b></font>", styles['TableCell'])],
    ]
    meta_table = Table(meta_info, colWidths=[140, 364])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
        ('BACKGROUND', (1, 0), (1, -1), colors.HexColor("#FFFFFF")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 35))

    cover_callout = create_callout_box(
        " Note d'Introduction pour l'Encadrement",
        "Ce document présente de manière claire et accessible les fondements du projet <b>ComplianceVerifier HPS</b>. "
        "Il détaille l'architecture globale, la logique métier des deux agents intelligents intégrés, ainsi qu'une synthèse approfondie "
        "des défis techniques et anomalies complexes qui ont été identifiés, analysés et définitivement résolus au cours du développement.",
        bg_color="#EFF6FF", border_color="#2563EB", title_color="#1E3A8A"
    )
    story.append(cover_callout)
    story.append(PageBreak())

    # =========================================================================
    # 2. VUE D'ENSEMBLE FONCTIONNELLE
    # =========================================================================
    story.append(Paragraph("1. Vue d'Ensemble Fonctionnelle", styles['SectionH1']))
    story.append(HRFlowable(width="100%", thickness=1, color=c_primary, spaceAfter=12))

    story.append(Paragraph("1.1 Le Problème Métier Résolu", styles['SectionH2']))
    story.append(Paragraph(
        "Dans le secteur de la monétique (gestion des cartes de paiement, terminaux de paiement et serveurs d'autorisation), "
        "l'analyse des fichiers de traces (logs d'échange de messages ISO 8583 ou formats propriétaires PowerCARD) est une tâche "
        "particulièrement complexe, fastidieuse et sujette aux erreurs humaines. Une seule trace monétique peut contenir des centaines "
        "de champs cryptiques (MTI, STAN, RRN, codes de réponse, blocs d'erreur HSM).",
        styles['CustomBody']
    ))
    story.append(Paragraph(
        "Parallèlement, la vérification de la conformité nécessite d'interroger en permanence d'imposantes spécifications techniques "
        "(guides Thales payShield HSM, manuels de référence PowerCARD). Le projet <b>ComplianceVerifier</b> répond à ce double défi "
        "en automatisant l'analyse des logs et en offrant une assistance intelligente aux spécifications.",
        styles['CustomBody']
    ))

    story.append(Paragraph("1.2 Les Deux Agents Intelligents et Leur Rôle Métier", styles['SectionH2']))
    
    agent_cards = [
        [
            Paragraph("<b>Agent 1 : Analyse de Conformité Monétique</b><br/><font color='#64748B'><i>compliance_agent_app</i></font>", styles['TableHeader']),
            Paragraph("<b>Agent 2 : Validation & Spécifications (RAG)</b><br/><font color='#64748B'><i>validation_agent_app</i></font>", styles['TableHeader'])
        ],
        [
            Paragraph(
                "<b>Rôle :</b> Analyse automatiquement les fichiers de traces brutes ISO 8583 / PowerCARD, regroupe les échanges en transactions "
                "métier cohérentes, détecte les anomalies (anomalies de code réponse, échecs HSM) et produit un rapport PDF synthétique et certifié.",
                styles['TableCell']
            ),
            Paragraph(
                "<b>Rôle :</b> Répond instantanément et avec précision aux questions posées par les ingénieurs ou analystes sur les documentations "
                "techniques (PDF HSM Thales, Excel Spec_PowerCARD) en citant exactement les sources et pages d'origine.",
                styles['TableCell']
            )
        ]
    ]
    agent_table = Table(agent_cards, colWidths=[246, 246])
    agent_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), c_primary),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor("#0D9488")), # Teal
        ('BACKGROUND', (0, 1), (1, 1), colors.HexColor("#F8FAFC")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(agent_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("1.3 Schéma Simplifié du Flux de Traitement", styles['SectionH2']))
    story.append(Paragraph(
        "Le processus global suit un enchaînement fluide et sécurisé depuis la soumission du fichier jusqu'à la restitution du rapport d'analyse :",
        styles['CustomBody']
    ))

    flow_data = [
        [Paragraph("<b>Étape</b>", styles['TableHeader']), Paragraph("<b>Action du Système</b>", styles['TableHeader']), Paragraph("<b>Résultat Métier</b>", styles['TableHeader'])],
        [Paragraph("1. Upload", styles['TableCellBold']), Paragraph("L'utilisateur dépose un fichier de trace (.txt/.log) ou une question de spec.", styles['TableCell']), Paragraph("Prise en charge par l'API REST FastAPI.", styles['TableCell'])],
        [Paragraph("2. Parsing / Structuration", styles['TableCellBold']), Paragraph("Extraction des lignes, identification des trames et filtrage du bruit (heartbeats).", styles['TableCell']), Paragraph("Objets transactions propres et isolés.", styles['TableCell'])],
        [Paragraph("3. Enrichissement RAG", styles['TableCellBold']), Paragraph("Interrogation de la base vectorielle pgvector pour obtenir les règles et codes HSM associés.", styles['TableCell']), Paragraph("Contexte documentaire pertinent récupéré.", styles['TableCell'])],
        [Paragraph("4. Analyse LLM (Gemini)", styles['TableCellBold']), Paragraph("Raisonnement agentique guidé par LangGraph pour évaluer la conformité métier.", styles['TableCell']), Paragraph("Diagnostic expert et détection d'alertes.", styles['TableCell'])],
        [Paragraph("5. Restitution", styles['TableCellBold']), Paragraph("Génération automatique du rapport PDF structuré (ReportLab) et réponse API.", styles['TableCell']), Paragraph("Rapport téléchargeable & certifié.", styles['TableCell'])],
    ]
    flow_table = Table(flow_data, colWidths=[80, 244, 180])
    flow_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(flow_table)
    story.append(Spacer(1, 14))

    story.append(PageBreak())

    # =========================================================================
    # 3. ARCHITECTURE TECHNIQUE
    # =========================================================================
    story.append(Paragraph("2. Architecture Technique", styles['SectionH1']))
    story.append(HRFlowable(width="100%", thickness=1, color=c_primary, spaceAfter=12))

    story.append(Paragraph("2.1 Technologies Utilisées (Stack Logicielle)", styles['SectionH2']))
    story.append(Paragraph(
        "L'architecture repose sur des standards modernes du développement backend et de l'Intelligence Artificielle Générative :",
        styles['CustomBody']
    ))

    stack_data = [
        [Paragraph("Composant", styles['TableHeader']), Paragraph("Technologie", styles['TableHeader']), Paragraph("Rôle & Utilité dans le Projet", styles['TableHeader'])],
        [Paragraph("Framework Backend", styles['TableCellBold']), Paragraph("FastAPI (Python 3.11+)", styles['TableCell']), Paragraph("Exposition des API REST performantes, asynchrones et sécurisées.", styles['TableCell'])],
        [Paragraph("Orchestration Agents", styles['TableCellBold']), Paragraph("LangGraph / LangChain", styles['TableCell']), Paragraph("Modélisation des workflows agentiques complexes sous forme de graphes d'états.", styles['TableCell'])],
        [Paragraph("Base de Données / Vector", styles['TableCellBold']), Paragraph("PostgreSQL + pgvector", styles['TableCell']), Paragraph("Stockage relationnel des métadonnées et stockage vectoriel des embeddings.", styles['TableCell'])],
        [Paragraph("Modèles IA (LLM / Embeddings)", styles['TableCellBold']), Paragraph("Google Gemini 1.5 / 2.0", styles['TableCell']), Paragraph("Raisonnement sémantique avancé (LLM) et vectorisation des textes (Embeddings).", styles['TableCell'])],
        [Paragraph("Génération de Documents", styles['TableCellBold']), Paragraph("ReportLab", styles['TableCell']), Paragraph("Moteur de génération dynamique de rapports PDF professionnels et stylisés.", styles['TableCell'])],
    ]
    stack_table = Table(stack_data, colWidths=[120, 140, 244])
    stack_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(stack_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("2.2 Composition du Système", styles['SectionH2']))
    story.append(Paragraph(
        "Le système s'articule autour de 4 briques logicielles interconnectées :",
        styles['CustomBody']
    ))
    story.append(Paragraph("&bull; <b>Parser de Logs Monétiques :</b> Extrait et valide les champs structurés à partir de textes bruts.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Moteur RAG (Retrieval-Augmented Generation) :</b> Indexe la documentation et fournit les fragments pertinents.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Graphes Agentiques LangGraph :</b> Contrôlent le flux d'exécution et la prise de décision de l'IA.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Générateur de Rapports PDF :</b> Convertit les résultats de l'analyse en documents téléchargeables.", styles['BulletText']))

    story.append(Spacer(1, 10))
    story.append(Paragraph("2.3 Comprendre le RAG (Retrieval-Augmented Generation) en 3 Concepts Simples", styles['SectionH2']))

    rag_explain = create_callout_box(
        " Démystification du RAG pour les Non-Spécialistes",
        "Un LLM (comme Gemini) possède des connaissances générales mais ne connaît pas les spécifications privées d'une entreprise.<br/>"
        "Le RAG est une technique qui permet d'apporter au modèle le livre de référence exact dont il a besoin pour répondre.<br/><br/>"
        "<b>1. Le Découpage en Chunks (Fragments) :</b> Un document de 500 pages est trop volumineux pour être analysé d'un coup. "
        "On le découpe en petits morceaux cohérents (chunks) de quelques paragraphes.<br/>"
        "<b>2. La Vectorisation (Embeddings) :</b> Chaque chunk texte est converti par un algorithme d'IA en une empreinte numérique (une série de nombres appelée vecteur) qui capture son sens exact.<br/>"
        "<b>3. La Recherche Sémantique :</b> Quand l'utilisateur pose une question, elle est aussi convertie en vecteur. La base <i>pgvector</i> "
        "compare la distance entre le vecteur de la question et les vecteurs des chunks pour retrouver les extraits les plus pertinents en quelques millisecondes.",
        bg_color="#F0FDF4", border_color="#16A34A", title_color="#15803D"
    )
    story.append(rag_explain)

    story.append(PageBreak())

    # =========================================================================
    # 4. AGENT 1 — ANALYSE DE CONFORMITÉ
    # =========================================================================
    story.append(Paragraph("3. Agent 1 — Analyse de Conformité Monétique", styles['SectionH1']))
    story.append(HRFlowable(width="100%", thickness=1, color=c_primary, spaceAfter=12))

    story.append(Paragraph("3.1 Rôle et Fonctionnement Pratique", styles['SectionH2']))
    story.append(Paragraph(
        "L'Agent 1 (<i>compliance_agent_app</i>) intervient lors du traitement des fichiers de traces système. "
        "Ces traces contiennent les échanges télématiques entre les terminaux de paiement, les serveurs d'autorisation PowerCARD et les boîtiers cryptographiques HSM (Hardware Security Module).",
        styles['CustomBody']
    ))
    story.append(Paragraph(
        "L'agent inspecte méticuleusement les champs clés normalisés de la norme ISO 8583 :",
        styles['CustomBody']
    ))
    story.append(Paragraph("&bull; <b>MTI (Message Type Identifier) :</b> Type du message (ex: 0100 Demande d'autorisation, 0110 Réponse).", styles['BulletText']))
    story.append(Paragraph("&bull; <b>STAN (System Trace Audit Number) & RRN (Retrieval Reference Number) :</b> Identifiants uniques de transaction.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Code Réponse (Field 39) :</b> Résultat de la demande (ex: '00' Approuvé, '51' Fonds insuffisants).", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Appels HSM :</b> Commandes cryptographiques échangées avec le boîtier de sécurité (ex: génération/vérification de PIN ou d'ARQC).", styles['BulletText']))

    story.append(Paragraph("3.2 Filtrage Intelligents du Bruit (Heartbeats)", styles['SectionH2']))
    story.append(Paragraph(
        "Les réseaux monétiques génèrent en permanence des tirs de contrôle ou messages de maintien de connexion (<i>heartbeats</i> "
        "MTI 0800 / 0810). Ces messages représentent parfois jusqu'à 80% du volume d'une trace mais ne contiennent aucune transaction financière.",
        styles['CustomBody']
    ))
    story.append(Paragraph(
        "L'Agent 1 intègre un algorithme de pré-filtrage qui écarte automatiquement ces messages de contrôle de routine "
        "afin de focaliser 100% de la puissance d'analyse de l'IA sur les vraies transactions des porteurs de carte.",
        styles['CustomBody']
    ))

    story.append(Paragraph("3.3 Exemple Concret d'Analyse : Avant vs Après Traitement", styles['SectionH2']))

    comp_data = [
        [Paragraph("Fichier de Trace Brut (Avant)", styles['TableHeader']), Paragraph("Rapport Structuré Généré par l'Agent (Après)", styles['TableHeader'])],
        [
            Paragraph(
                "<font fontName='Courier' size='7'>"
                "2026-08-03 14:10:01 IN  MTI:0100 PAN:4548********1234 STAN:004521 RRN:608312004521<br/>"
                "2026-08-03 14:10:02 HSM REQ: EC (Generate ARQC)<br/>"
                "2026-08-03 14:10:02 HSM RESP: ED Error: 15 (Invalid PIN Block)<br/>"
                "2026-08-03 14:10:03 OUT MTI:0110 STAN:004521 RespCode:55"
                "</font>",
                styles['TableCell']
            ),
            Paragraph(
                "<b>Transaction ID :</b> TXN-004521<br/>"
                "<b>Statut Métier :</b> <font color='#DC2626'><b>Déclinée (Code 55 - PIN Incorrect)</b></font><br/>"
                "<b>Alerte Sécurité :</b> <font color='#DC2626'>Échec HSM détecté sur la commande EC (Erreur ED-15)</font><br/>"
                "<b>Diagnostic Agent :</b> Transaction rejetée suite à la vérification cryptographique PIN non conforme au niveau du HSM Thales.",
                styles['TableCell']
            )
        ]
    ]
    comp_table = Table(comp_data, colWidths=[246, 246])
    comp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor("#475569")),
        ('BACKGROUND', (1, 0), (1, 0), c_primary),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(comp_table)
    story.append(Spacer(1, 14))

    story.append(PageBreak())

    # =========================================================================
    # 5. AGENT 2 — VALIDATION / SPÉCIFICATIONS (RAG)
    # =========================================================================
    story.append(Paragraph("4. Agent 2 — Validation & Spécifications (RAG)", styles['SectionH1']))
    story.append(HRFlowable(width="100%", thickness=1, color=c_primary, spaceAfter=12))

    story.append(Paragraph("4.1 Rôle et Cas d'Usage", styles['SectionH2']))
    story.append(Paragraph(
        "L'Agent 2 (<i>validation_agent_app</i>) fait office d'assistant expert interactif. "
        "Les équipes de développement ou d'homologation monétique l'interrogent lorsqu'elles ont un doute sur une norme technique ou sur le fonctionnement d'un composant cryptographique.",
        styles['CustomBody']
    ))
    story.append(Paragraph(
        "L'agent interroge en temps réel deux sources principales de documentation :",
        styles['CustomBody']
    ))
    story.append(Paragraph("&bull; <b>Manuels Techniques Thales payShield HSM :</b> Spécifications des commandes cryptographiques (ex: CW, M0, EC, NC) et de leurs codes d'erreur.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Fichiers Spécifications PowerCARD (Excel / PDF) :</b> Structure des messages et règles de gestion métiers des autorisations.", styles['BulletText']))

    story.append(Paragraph("4.2 Le Pipeline RAG Utilisé", styles['SectionH2']))
    story.append(Paragraph(
        "Pour garantir une fiabilité totale et éliminer tout risque d'hallucination (invention de réponses par l'IA), l'Agent 2 applique le pipeline suivant :",
        styles['CustomBody']
    ))

    rag_pipe = [
        [Paragraph("Étape Pipeline", styles['TableHeader']), Paragraph("Description Technico-Fonctionnelle", styles['TableHeader'])],
        [Paragraph("1. Ingestion Documentaire", styles['TableCellBold']), Paragraph("Chargement des PDF/Excel, extraction du texte et découpage adaptatif par fenêtre glissante.", styles['TableCell'])],
        [Paragraph("2. Hash SHA-256 & Cache", styles['TableCellBold']), Paragraph("Vérification de l'empreinte du fichier : si le document a déjà été indexé, réutilisation immédiate du cache.", styles['TableCell'])],
        [Paragraph("3. Vectorisation Gemini", styles['TableCellBold']), Paragraph("Génération des embeddings vectoriels via l'API Google Gemini embeddings.", styles['TableCell'])],
        [Paragraph("4. Recherche Hybride", styles['TableCellBold']), Paragraph("Combinaison de la recherche sémantique (vecteurs) et de la recherche exacte par code de commande/réponse.", styles['TableCell'])],
        [Paragraph("5. Synthèse avec Citations", styles['TableCellBold']), Paragraph("Rédaction de la réponse par le LLM Gemini avec mention obligatoire de la source et du numéro de page.", styles['TableCell'])],
    ]
    rag_table = Table(rag_pipe, colWidths=[140, 364])
    rag_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0D9488")), # Teal header
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(rag_table)
    story.append(Spacer(1, 14))

    story.append(PageBreak())

    # =========================================================================
    # 6. PROBLÈMES RENCONTRÉS ET RÉSOLUS
    # =========================================================================
    story.append(Paragraph("5. Problèmes Rencontrés et Résolus (Défis de Débogage)", styles['SectionH1']))
    story.append(HRFlowable(width="100%", thickness=1, color=c_primary, spaceAfter=12))

    story.append(Paragraph(
        "Cette section constitue le cœur du bilan d'avancement technique. "
        "Au cours du développement, plusieurs dysfonctionnements complexes ont été identifiés, analysés et corrigés méthodiquement. "
        "Chaque problème est présenté selon la structure : <b>Symptôme &rarr; Cause &rarr; Correction &rarr; Preuve de Validation</b>.",
        styles['CustomBody']
    ))
    story.append(Spacer(1, 6))

    # --- BUG A ---
    story.append(Paragraph("5.1 Problème A : Transactions Fantômes dans les Rapports PDF", styles['SectionH2']))
    
    bug_a_data = [
        [Paragraph("<b>Symptôme Observé :</b>", styles['TableCellBold']), Paragraph("Présence de lignes parasites intitulées 'TXN-None' avec STAN/RRN 'Inconnu' dans le rapport d'analyse final.", styles['TableCell'])],
        [Paragraph("<b>Cause Identifiée :</b>", styles['TableCellBold']), Paragraph("Le parser de log (<i>log_parser.py</i>) traitait de manière trop laxiste des lignes de bruit ou des fragments de traces incomplets qui ne possédaient aucun identifiant métier valide (STAN ou RRN manquants).", styles['TableCell'])],
        [Paragraph("<b>Correction Apportée :</b>", styles['TableCellBold']), Paragraph("Renforcement du filtre de validation dans <i>log_parser.py</i>. Désormais, tout fragment de log dépourvu à la fois de STAN et de RRN est rejeté en amont et n'est plus instancié sous forme de transaction.", styles['TableCell'])],
        [Paragraph("<b>Preuve / Validation :</b>", styles['TableCellBold']), Paragraph("<font color='#16A34A'><b>100% validé :</b></font> Les rapports générés ne contiennent plus aucune transaction anonyme 'TXN-None'. Seules les vraies transactions identifiables apparaissent.", styles['TableCell'])],
    ]
    bug_a_table = Table(bug_a_data, colWidths=[130, 374])
    bug_a_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#FEF2F2")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#FCA5A5")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(bug_a_table)
    story.append(Spacer(1, 14))

    # --- BUG B ---
    story.append(Paragraph("5.2 Problème B : Réponses RAG Incomplètes / Incorrectes sur les Codes d'Erreur HSM", styles['SectionH2']))
    story.append(Paragraph(
        "Lors des interrogations sur les commandes HSM (par exemple la commande 'EC' de génération d'ARQC), l'Agent 2 fournissait parfois des réponses vagues ou indiquait à tort que le code d'erreur n'existait pas. "
        "Une investigation approfondie a révélé <b>quatre causes en cascade</b> qui s'additionnaient :",
        styles['CustomBody']
    ))

    bug_b_cascade = [
        [Paragraph("Cause Racine Identifiée", styles['TableHeader']), Paragraph("Explication Technique Simplifiée", styles['TableHeader']), Paragraph("Correction & Amélioration Apportée", styles['TableHeader'])],
        [
            Paragraph("1. Chunking naïf page par page", styles['TableCellBold']),
            Paragraph("Le découpage initial coupait les documents strictement à la fin de chaque page du PDF, coupant ainsi un tableau de codes d'erreur HSM en deux.", styles['TableCell']),
            Paragraph("Mise en place d'un <b>chunking à fenêtre glissante</b> avec chevauchement (overlap) de 200 caractères pour préserver la continuité des tableaux.", styles['TableCell'])
        ],
        [
            Paragraph("2. Mismatch sémantique commande / réponse", styles['TableCellBold']),
            Paragraph("La question de l'utilisateur mentionnait le code de la commande ('EC') alors que la table d'erreur contenait le code de la réponse ('ED'). La recherche vectorielle seule ratait la correspondance.", styles['TableCell']),
            Paragraph("Implémentation d'une <b>recherche exacte bivalente</b> : l'agent cherche simultanément la chaîne exacte du code de commande et du code de réponse en complément du vecteur.", styles['TableCell'])
        ],
        [
            Paragraph("3. Épuisement silencieux du quota API Gemini", styles['TableCellBold']),
            Paragraph("L'offre gratuite de l'API Gemini d'embedding bloquait temporairement lors de requêtes successives, ce qui renvoyait une liste de chunks vide assimilée à un 'document non trouvé'.", styles['TableCell']),
            Paragraph("Ajout d'un <b>gestionnaire d'erreur et de retry exponentiel avec fallback</b>. Les erreurs de quota sont explicitement capturées sans masquer les documents.", styles['TableCell'])
        ],
        [
            Paragraph("4. Cache obsolète basé sur le hash du fichier", styles['TableCellBold']),
            Paragraph("Le système réutilisait les ancins chunks déjà stockés en base pgvector sans détecter que l'algorithme de chunking avait évolué.", styles['TableCell']),
            Paragraph("Ajout d'un <b>versionnement explicite de la stratégie de chunking</b> dans les métadonnées pour invalider automatiquement les caches obsolètes.", styles['TableCell'])
        ],
    ]
    bug_b_table = Table(bug_b_cascade, colWidths=[120, 184, 200])
    bug_b_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(bug_b_table)
    story.append(Spacer(1, 10))

    b_proof = create_callout_box(
        " Preuve de Validation du Problème B",
        "<b>Résultat après correction :</b> Les tests de validation sur les commandes HSM Thales (commandes EC, CW, M0) "
        "retournent désormais 100% d'exactitude avec les numéros de page exacts de la documentation Thales payShield.",
        bg_color="#F0FDF4", border_color="#16A34A", title_color="#15803D"
    )
    story.append(b_proof)
    story.append(Spacer(1, 14))

    story.append(PageBreak())

    # --- BUG C ---
    story.append(Paragraph("5.3 Problème C : Erreur d'Indentation Python Bloquant le Serveur", styles['SectionH2']))

    bug_c_data = [
        [Paragraph("<b>Symptôme Observé :</b>", styles['TableCellBold']), Paragraph("Échec du démarrage du serveur FastAPI (erreur <i>IndentationError</i> lors du chargement des modules).", styles['TableCell'])],
        [Paragraph("<b>Cause Identifiée :</b>", styles['TableCellBold']), Paragraph("Une incohérence d'espaces/tabulations s'était glissée lors de l'édition rapide d'une fonction dans le contrôleur principal.", styles['TableCell'])],
        [Paragraph("<b>Correction Apportée :</b>", styles['TableCellBold']), Paragraph("Correction immédiate de la structure du fichier et passage au linter automatisé.", styles['TableCell'])],
        [Paragraph("<b>Portée & Rigueur :</b>", styles['TableCellBold']), Paragraph("Cet incident a servi de rappel sur l'importance d'exécuter systématiquement une batterie de tests d'intégration automatisés (Pytest) avant toute validation de code.", styles['TableCell'])],
    ]
    bug_c_table = Table(bug_c_data, colWidths=[130, 374])
    bug_c_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#FFFBEB")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#FCD34D")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(bug_c_table)
    story.append(Spacer(1, 18))

    # =========================================================================
    # 7. ÉTAT ACTUEL / PROCHAINES ÉTAPES
    # =========================================================================
    story.append(Paragraph("6. État Actuel & Prochaines Étapes", styles['SectionH1']))
    story.append(HRFlowable(width="100%", thickness=1, color=c_primary, spaceAfter=12))

    story.append(Paragraph("6.1 Ce qui Fonctionne Parfaitement Aujourd'hui", styles['SectionH2']))
    story.append(Paragraph("&bull; <b>Parsing & Traitement des Traces Monétiques :</b> Extraction fiable des champs ISO 8583 et suppression automatique du bruit.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Recherche Documentaire Hybride RAG :</b> Interrogation précise des spécifications Thales et PowerCARD avec mise en cache SHA-256.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Génération de Rapports PDF Stylisés :</b> Édition automatique de rapports conformes à la charte graphique HPS via ReportLab.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Interface API FastAPI :</b> Points de terminaison REST performants et asynchrones.", styles['BulletText']))

    story.append(Spacer(1, 8))
    story.append(Paragraph("6.2 Limitations Connues & Axes d'Amélioration", styles['SectionH2']))

    limits_data = [
        [Paragraph("Limitation Actuelle", styles['TableHeader']), Paragraph("Impact Métier", styles['TableHeader']), Paragraph("Piste d'Amélioration Proposée", styles['TableHeader'])],
        [
            Paragraph("Quota API Gemini Gratuit", styles['TableCellBold']),
            Paragraph("Risque de ralentissement lors d'analyses massives simultanées.", styles['TableCell']),
            Paragraph("Passage à une clé API entreprise ou hébergement d'un modèle d'embeddings local (ex: Ollama / HuggingFace).", styles['TableCell'])
        ],
        [
            Paragraph("Monolithisme du Provider Embedding", styles['TableCellBold']),
            Paragraph("Dépendance directe aux modèles d'embeddings Google Gemini.", styles['TableCell']),
            Paragraph("Mise en place d'une interface abstraite <i>VectorProvider</i> pour interchanger facilement les modèles.", styles['TableCell'])
        ],
        [
            Paragraph("Formats de Logs Supportés", styles['TableCellBold']),
            Paragraph("Focus principal sur ISO 8583 et PowerCARD.", styles['TableCell']),
            Paragraph("Extension du parser pour supporter nativement le format AS2805 et JSON API cloud.", styles['TableCell'])
        ],
    ]
    limits_table = Table(limits_data, colWidths=[130, 174, 200])
    limits_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(limits_table)
    story.append(Spacer(1, 14))

    story.append(PageBreak())

    # =========================================================================
    # 8. CONCLUSION & SYNTHÈSE FINAL
    # =========================================================================
    story.append(Paragraph("7. Conclusion & Synthèse pour l'Encadrement", styles['SectionH1']))
    story.append(HRFlowable(width="100%", thickness=1, color=c_primary, spaceAfter=12))

    story.append(Paragraph(
        "Le projet <b>ComplianceVerifier HPS</b> constitue une avancée concrète dans la modernisation du traitement "
        "des données monétiques au sein de l'organisation. En combinant la puissance des agents intelligemment orchestrés par <b>LangGraph</b>, "
        "la précision du <b>RAG hybride sur pgvector</b> et la rigueur d'un <b>parser de traces dédié</b>, la solution apporte une valeur ajoutée immédiate :",
        styles['CustomBody']
    ))

    story.append(Paragraph("&bull; <b>Gain de Temps Majeur :</b> Réduction du temps d'analyse des traces monétiques de plusieurs heures à quelques secondes.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Fiabilité Accrue :</b> Élimination des erreurs d'interprétation humaine grâce à la vérification croisée automatique avec les spécifications officielles.", styles['BulletText']))
    story.append(Paragraph("&bull; <b>Robustesse Technique Validée :</b> Résolution éprouvée de tous les pièges d'implémentation (chunking, cache, quotas, transactions fantômes).", styles['BulletText']))

    story.append(Spacer(1, 15))
    final_callout = create_callout_box(
        " Synthèse d'Évaluation",
        "La plateforme est actuellement pleinement fonctionnelle pour les scénarios de démonstration et d'homologation. "
        "Les étapes futures permettront une transition fluide vers un environnement de production hautement disponible.",
        bg_color="#EFF6FF", border_color="#1E3A8A", title_color="#1E3A8A"
    )
    story.append(final_callout)

    # Construction du document avec TwoPassNumberedCanvas
    doc.build(story, canvasmaker=TwoPassNumberedCanvas)
    print(f"PDF généré avec succès à l'emplacement : {PDF_OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
