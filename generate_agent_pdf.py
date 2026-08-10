# generate_agent_pdf.py
import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to add headers, page numbering, and corporate layout
    to all pages except the cover page.
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
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        if self._pageNumber == 1:
            # Draw decorative accents on the cover page
            self.saveState()
            self.setFillColor(colors.HexColor('#1E3A8A')) # Deep blue block
            self.rect(0, 0, 18, 792, fill=True, stroke=False)
            self.setFillColor(colors.HexColor('#0F172A')) # Slate block
            self.rect(18, 0, 12, 792, fill=True, stroke=False)
            self.restoreState()
            return
            
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor('#0F172A'))
        
        # Header
        self.drawString(54, 745, "HPS COMPLIANCEVERIFIER — LOGS ANALYSIS AGENT")
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#475569'))
        self.drawRightString(558, 745, "TECHNICAL SPECS & WORKFLOWS FOR ADVISOR REVIEW")
        
        # Header Rule
        self.setStrokeColor(colors.HexColor('#E2E8F0'))
        self.setLineWidth(0.75)
        self.line(54, 738, 558, 738)
        
        # Footer Rule
        self.line(54, 55, 558, 55)
        
        # Footer
        self.drawString(54, 40, "CONFIDENTIAL - HPS Technical Advisor Presentation Document")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 40, page_text)
        self.restoreState()


def build_agent_explanation_pdf(filename="Agent_Log_Analysis_Architecture.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=72,
        bottomMargin=72
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Palette
    c_primary = colors.HexColor('#1E3A8A')    # Deep Blue
    c_secondary = colors.HexColor('#0F172A')  # Slate Black
    c_accent = colors.HexColor('#2563EB')     # Electric Blue
    c_body = colors.HexColor('#334155')       # Slate Body
    c_bg = colors.HexColor('#F8FAFC')         # Light Grey
    c_border = colors.HexColor('#E2E8F0')     # Border
    
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=28,
        leading=34,
        textColor=c_primary,
        spaceAfter=15
    )
    
    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=13,
        leading=18,
        textColor=c_body,
        spaceAfter=120
    )
    
    meta_style = ParagraphStyle(
        'CoverMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=15,
        textColor=c_body
    )
    
    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=c_primary,
        spaceBefore=18,
        spaceAfter=10,
        keepWithNext=True
    )
    
    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11.5,
        leading=15,
        textColor=c_secondary,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=c_body,
        spaceAfter=8
    )
    
    bullet_style = ParagraphStyle(
        'BulletCustom',
        parent=body_style,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=4
    )
    
    story = []
    
    # ==================== COVER PAGE ====================
    story.append(Spacer(1, 100))
    story.append(Paragraph("Understanding the Log Analysis Agent", title_style))
    story.append(Paragraph("Under-the-Hood Ingestion, Filtering, Hybrid RAG-LLM Logic & Technical Limits<br/>"
                           "<i>Preparation Guide for Project Advisor Defenses</i>", subtitle_style))
    
    story.append(Paragraph(
        "<b>Document Specifications:</b><br/>"
        "• Target Audience: HPS Project Advisor (Encadrant)<br/>"
        "• Generated By: Antigravity AI Coding Assistant<br/>"
        "• Core Modules Covered: LangGraph Engine, Hybrid Session Ingestion, Spec-Log Correlation<br/>"
        "• Execution Scope: Trace parser limits, deterministic regex matches, LLM cognitive roles<br/>"
        "• Presentation Date: August 10, 2026",
        meta_style
    ))
    story.append(PageBreak())
    
    # ==================== SECTION 1 ====================
    story.append(Paragraph("1. System Architecture Overview", h1_style))
    story.append(Paragraph(
        "The <b>Log Analysis Agent</b> in HPS ComplianceVerifier is built as an agentic validation assistant powered by "
        "<b>LangGraph</b>. Instead of sending raw, unprocessed transaction data directly to an LLM, the system processes uploads "
        "through a multi-stage validation graph. The architecture separates raw data manipulation (deterministic parser tasks) from "
        "cognitive synthesis (done by the LLM). This hybrid approach provides 100% accuracy for statistical queries (like occurrences count) "
        "while leveraging generative AI for complex diagnostics, error explanation, and recommendations.",
        body_style
    ))
    
    # Table of files
    table_data = [
        [Paragraph("<b>Component Role</b>", body_style), Paragraph("<b>Tech Stack</b>", body_style), Paragraph("<b>Core Responsibility</b>", body_style)],
        [Paragraph("Workflow Graph", body_style), Paragraph("LangGraph StateGraph", body_style), Paragraph("Manages conversation turns, state variables, and execution routing.", body_style)],
        [Paragraph("RAG Query Router", body_style), Paragraph("PgVector / PostgreSQL", body_style), Paragraph("Indexes persistent and session specifications, querying relevant chunks.", body_style)],
        [Paragraph("Deterministic Engine", body_style), Paragraph("Python / Regex patterns", body_style), Paragraph("Performs counts, error classification, and command response map resolution.", body_style)],
        [Paragraph("Cognitive Synthesizer", body_style), Paragraph("Gemini 3.5 Flash", body_style), Paragraph("Generates user-facing diagnostic guidance, summaries, and troubleshooting steps.", body_style)]
    ]
    t = Table(table_data, colWidths=[120, 120, 260])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_bg),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))
    
    # ==================== SECTION 2 ====================
    story.append(Paragraph("2. Ingestion Pipeline: What Happens Upon Upload", h1_style))
    story.append(Paragraph(
        "When a user uploads a document to the ComplianceVerifier session, the processing path splits based on the file format:",
        body_style
    ))
    
    story.append(Paragraph("<b>A. Uploading a Trace File (.txt / monetic log):</b>", h2_style))
    story.append(Paragraph("1. <b>Session Isolation:</b> The file is written to a unique folder bound to the user's `session_id`.", bullet_style))
    story.append(Paragraph("2. <b>Transaction Chunking:</b> The system splits the trace by searching for the separator `=== Transaction `. This maps each transaction block individually.", bullet_style))
    story.append(Paragraph("3. <b>Deterministic Indexing:</b> Python counts occurrences of key transaction elements (e.g., command codes like EC, response codes like ED, STAN numbers, or error statuses like NOK/alertes) on the <i>entire raw file content</i>.", bullet_style))
    story.append(Paragraph("4. <b>RAG Spec Matching:</b> In parallel, the backend searches the global database for specifications corresponding to the detected command codes. If `EC` is found, the backend retrieves specs for `EC` and `ED` and appends them to the context to help the LLM explain logs, even if no manual was uploaded in this session.", bullet_style))
    story.append(Paragraph("5. <b>Intelligent Context Filtering:</b> To prevent token pollution, if the trace exceeds 80,000 characters, a filter extracts only transactions containing query keywords or failures/errors. It never truncates inside a transaction block.", bullet_style))
    
    story.append(Paragraph("<b>B. Uploading a Specification PDF (RAG upload):</b>", h2_style))
    story.append(Paragraph("1. <b>PDF Text Extraction:</b> The backend extracts text using ReportLab/pdfplumber wrappers.", bullet_style))
    story.append(Paragraph("2. <b>Recursive Splitting:</b> The text is divided into chunks (typically 1500 chars with 200 overlap).", bullet_style))
    story.append(Paragraph("3. <b>Metadata Enrichment:</b> Each chunk is automatically scanned for command/response pairs (e.g. EC/ED), response values (Value 'B9'), and tags like `contains_error_table`.", bullet_style))
    story.append(Paragraph("4. <b>Session Vector Embedding:</b> The chunks are embedded using Google embeddings and stored in a temporary session vector table. The RAG engine will restrict search lookups strictly to this file hash when answering session-specific queries.", bullet_style))
    story.append(Spacer(1, 10))
    story.append(PageBreak())
    
    # ==================== SECTION 3 ====================
    story.append(Paragraph("3. What Could Fail & System Limits", h1_style))
    story.append(Paragraph(
        "To ensure transparency in front of your advisor, it is critical to present what the system cannot do or where it might fail:",
        body_style
    ))
    
    story.append(Paragraph("<b>• Trace Format Violations:</b>", bullet_style))
    story.append(Paragraph("If the monetic trace is not formatted with standard transaction headers (e.g., missing `=== Transaction `), the split algorithm cannot segment it. The system falls back to simple character truncation at the character limit, which can cut transactions in half and degrade the LLM's understanding.", bullet_style))
    
    story.append(Paragraph("<b>• Extreme Token Saturation:</b>", bullet_style))
    story.append(Paragraph("If the log file has hundreds of distinct transactions, all containing errors, the filtering logic might still exceed the 80,000 characters limit. In this case, some transactions are omitted from the LLM context (though a clear warning is printed to the user, and the global counts computed deterministically remain 100% accurate).", bullet_style))
    
    story.append(Paragraph("<b>• RAG Segmented Tables:</b>", bullet_style))
    story.append(Paragraph("If a critical error code table is split exactly across two PDF pages, the RAG chunker might split the table. The LLM might only receive half of the table, leading to omissions unless semantic overlap parameters capture both chunks.", bullet_style))
    
    story.append(Paragraph("<b>• Bilingual Ambiguities:</b>", bullet_style))
    story.append(Paragraph("If the uploaded PDF specifications are in English, but the user queries in French with non-standard monetic translations, pure semantic search might yield low-relevance results. Exact keyword matching rules are deployed to mitigate this by searching for standard code tokens first.", bullet_style))
    story.append(Spacer(1, 10))

    # ==================== SECTION 4 ====================
    story.append(Paragraph("4. Division of Labor: Hardcoded Logic vs. LLM Cognitive Tasks", h1_style))
    story.append(Paragraph(
        "One of the biggest strengths of this project is that it does not treat the LLM as a database. "
        "Here is the strict division of labor:",
        body_style
    ))
    
    division_data = [
        [Paragraph("<b>Deterministic / Hardcoded Logic (Python)</b>", body_style), Paragraph("<b>Cognitive / Generative Logic (LLM)</b>", body_style)],
        [Paragraph("<b>Sub-string Counting:</b> Executing exact `.count(token)` searches on the raw text. The LLM is NEVER asked to count occurrences since LLMs are poor at counting tokens in long windows.", body_style),
         Paragraph("<b>Synthesis & Diagnostics:</b> Taking the exact count of errors, reading the relevant RAG spec chunks, and explaining <i>why</i> the error happened.", body_style)],
        
        [Paragraph("<b>HSM Code Mapping:</b> Translating response codes to command codes via a static dictionary mapping (`command_response_map.json` linking EC ↔ ED).", body_style),
         Paragraph("<b>Error Code Translation:</b> Reading a chunk showing code `15` and translating it into domain-specific guidance (e.g., 'Check key parity or DUKPT LMK parity').", body_style)],
        
        [Paragraph("<b>Token & Metadata Filtering:</b> Pre-filtering the raw content blocks using exact regex keywords (alert, nok, error, -1) to fit constraints.", body_style),
         Paragraph("<b>Context Integration:</b> Reading user chat history, maintaining session tone, and generating coherent explanations in the requested language (French/English).", body_style)]
    ]
    t_div = Table(division_data, colWidths=[250, 250])
    t_div.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F8FAFC')),
        ('BACKGROUND', (1,0), (1,-1), colors.HexColor('#F0FDF4')),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_div)
    story.append(PageBreak())

    # ==================== SECTION 5 ====================
    story.append(Paragraph("5. Advisor Presentation Cheat Sheet (Talking Points)", h1_style))
    story.append(Paragraph(
        "Use these talking points to defend your project design during tomorrow's review:",
        body_style
    ))
    
    story.append(Paragraph("<b>1. How does the system handle very large trace files?</b>", h2_style))
    story.append(Paragraph(
        "<i>Answer:</i> We use a hybrid approach. The backend extracts statistics and executes substring counts deterministically "
        "on the entire log stream using Python. Then, to stay within token windows and prevent LLM hallucination, we apply a "
        "filtering algorithm that extracts only transactions with errors, alerts, or queries. This filters a 2MB log down to "
        "relevant transaction packets before passing it to the LLM.",
        body_style
    ))
    
    story.append(Paragraph("<b>2. Why is pgVector utilized instead of querying the LLM directly on the PDF?</b>", h2_style))
    story.append(Paragraph(
        "<i>Answer:</i> PDFs are too large (e.g., 746 pages) to pass as direct prompts. We split the PDFs into chunks, index them "
        "into a Postgres database using pgvector, and execute similarity searches. For session uploads, we isolate vector store "
        "queries to the specific file hash, ensuring users only retrieve information from their uploaded files.",
        body_style
    ))

    story.append(Paragraph("<b>3. What happens if a session terminates or a new user logs in?</b>", h2_style))
    story.append(Paragraph(
        "<i>Answer:</i> The database stores session chunks mapped to a unique `session_id`. Files are held in temporary storage. "
        "Upon session deletion or timeout, the temporary files are cleared and the database rows matching the `session_id` are purged, "
        "preserving security and isolation.",
        body_style
    ))
    
    story.append(Spacer(1, 15))
    story.append(Paragraph("<i>End of presentation guide. ComplianceVerifier System Engineering. Confidential.</i>", body_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"[PDF_GENERATOR] Document built successfully: {filename}")


if __name__ == "__main__":
    build_agent_explanation_pdf()
