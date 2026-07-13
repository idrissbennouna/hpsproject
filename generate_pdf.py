# generate_pdf.py
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
    Two-pass canvas to calculate total page count dynamically
    and add beautiful professional headers/footers to all pages except the cover.
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
        self.drawString(54, 745, "HPS COMPLIANCEVERIFIER SYSTEM")
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#475569'))
        self.drawRightString(558, 745, "TECHNICAL ARCHITECTURE & DOCUMENTATION")
        
        # Header Rule
        self.setStrokeColor(colors.HexColor('#E2E8F0'))
        self.setLineWidth(0.75)
        self.line(54, 738, 558, 738)
        
        # Footer Rule
        self.line(54, 55, 558, 55)
        
        # Footer
        self.drawString(54, 40, "CONFIDENTIAL - HPS AI Engineering Team Onboarding")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 40, page_text)
        self.restoreState()


def build_pdf(filename="Technical_Documentation.pdf"):
    # Target path
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
    c_primary = colors.HexColor('#1E3A8A')    # Corporate Deep Blue
    c_secondary = colors.HexColor('#0F172A')  # Slate Black
    c_accent = colors.HexColor('#2563EB')     # Electric Blue
    c_body = colors.HexColor('#334155')       # Slate Body Text
    c_code_bg = colors.HexColor('#F8FAFC')    # Light grey background
    c_border = colors.HexColor('#E2E8F0')     # Border grey
    
    # Custom styles
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=32,
        leading=38,
        textColor=c_primary,
        spaceAfter=15
    )
    
    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=14,
        leading=20,
        textColor=c_body,
        spaceAfter=150
    )
    
    meta_style = ParagraphStyle(
        'CoverMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=16,
        textColor=c_body
    )
    
    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=c_primary,
        spaceBefore=22,
        spaceAfter=10,
        keepWithNext=True
    )
    
    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=c_secondary,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14.5,
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
    
    code_style = ParagraphStyle(
        'CodeStyleCustom',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=0
    )
    
    story = []
    
    # ==================== COVER PAGE ====================
    story.append(Spacer(1, 100))
    story.append(Paragraph("HPS ComplianceVerifier", title_style))
    story.append(Paragraph("Automated Monetic Log Verification & Agentic RAG Platform<br/>"
                           "<b>Comprehensive Technical Onboarding Documentation</b>", subtitle_style))
    
    story.append(Paragraph(
        "<b>Document Specifications:</b><br/>"
        "• Target Audience: Newly Joined AI & QA Engineers<br/>"
        "• Author: Senior Software Architect & Technical Writer<br/>"
        "• Scope: Frontend, Backend, Parsing Pipeline, RAG/LLM, Infrastructure, Error Handling<br/>"
        "• Reference Version: 1.0.0 (Corporate HPS Edition)<br/>"
        "• Date: July 2026",
        meta_style
    ))
    story.append(PageBreak())
    
    # ==================== TABLE OF CONTENTS PLACEHOLDER ====================
    story.append(Paragraph("Table of Contents", h1_style))
    story.append(Spacer(1, 10))
    
    toc_data = [
        [Paragraph("<b>Section</b>", body_style), Paragraph("<b>Description</b>", body_style)],
        [Paragraph("1. Project Overview", body_style), Paragraph("High-level system objectives and folder structures", body_style)],
        [Paragraph("2. Complete Request Flow", body_style), Paragraph("Trace file ingestion to PDF report generation workflow", body_style)],
        [Paragraph("3. Frontend Architecture (React)", body_style), Paragraph("User interface modules, routes, and state visualization", body_style)],
        [Paragraph("4. Backend Architecture", body_style), Paragraph("FastAPI core, endpoints structure, and request lifecycles", body_style)],
        [Paragraph("5. Parsing Pipeline", body_style), Paragraph("Log demultiplexing, STAN correlation, and dynamic pattern matching", body_style)],
        [Paragraph("6. AI / LLM Pipeline", body_style), Paragraph("Multi-agent flow orchestration using LangGraph workflow state", body_style)],
        [Paragraph("7. Embeddings", body_style), Paragraph("Embedding models, vector representations, and semantic matching", body_style)],
        [Paragraph("8. Vector Database", body_style), Paragraph("PostgreSQL and pgvector schema configuration", body_style)],
        [Paragraph("9. Prompt Engineering", body_style), Paragraph("System instructions, context injection, and hallucination containment", body_style)],
        [Paragraph("10. Retrieval Process", body_style), Paragraph("RAG queries, similarity metrics, and local fallback mechanics", body_style)],
        [Paragraph("11. LLM Response Generation", body_style), Paragraph("Generative flow, markdown translation, and compliance formatting", body_style)],
        [Paragraph("12. Error Invalidation & Handling", body_style), Paragraph("System exceptions, trace failures, and API fallback recovery", body_style)],
        [Paragraph("13. Configuration Reference", body_style), Paragraph("Configuration variables, docker setups, and environmental values", body_style)],
        [Paragraph("14. Project Architecture Diagrams", body_style), Paragraph("Visualizing data flow, pipelines, and modular topologies", body_style)],
        [Paragraph("15. Sequence Diagram", body_style), Paragraph("Synchronous interaction log between components", body_style)],
        [Paragraph("16. Component Code Walkthrough", body_style), Paragraph("Source file analysis (main.py, log_parser.py, agent_graph.py...)", body_style)],
        [Paragraph("17. Glossary of Terms", body_style), Paragraph("Monetic and AI/RAG terms defined", body_style)],
        [Paragraph("18. Technical Suggestions", body_style), Paragraph("Architectural recommendations, security checks, and upgrades", body_style)],
        [Paragraph("19. Architectural Conclusion", body_style), Paragraph("Final system wrap-up and evolutionary path forward", body_style)],
    ]
    
    t_toc = Table(toc_data, colWidths=[150, 350])
    t_toc.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, c_border),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_toc)
    story.append(PageBreak())
    
    # Helper to add section headers
    def add_section(title, num_str):
        story.append(Paragraph(f"{num_str}. {title}", h1_style))
        story.append(Spacer(1, 5))
        
    def add_subsection(title):
        story.append(Paragraph(title, h2_style))
        story.append(Spacer(1, 3))
        
    def add_p(text):
        story.append(Paragraph(text, body_style))
        
    def add_bullet(text):
        story.append(Paragraph(f"&bull; {text}", bullet_style))
        
    def add_code(code_lines):
        code_text = "<br/>".join(code_lines)
        t_code = Table([[Paragraph(code_text, code_style)]], colWidths=[500])
        t_code.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), c_code_bg),
            ('BOX', (0, 0), (-1, -1), 0.5, c_border),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(Spacer(1, 5))
        story.append(t_code)
        story.append(Spacer(1, 5))

    # ==================== SECTION 1 ====================
    add_section("Project Overview", "1")
    add_p("The <b>HPS ComplianceVerifier</b> is an enterprise-grade agentic QA platform developed specifically for the monetic test engineers at HPS. In the electronic payment domain, verifying that transaction processing flows adhere strictly to business specifications is critical. Normally, QA testers manually read dense, raw monetic trace log files of authorization switches (such as PowerCARD). These logs multiplex transactions running concurrently, making manual parsing highly prone to error and time-consuming.")
    
    add_p("<b>What Problem it Solves:</b>")
    add_bullet("<b>Log Multiplexing De-entanglement:</b> Log entries from separate concurrent threads are interleaved. The tool automatically maps each entry to its correct transaction sequence using Session ID grouping.")
    add_bullet("<b>Automated Exception Mapping:</b> Instead of manually tracing exceptions, the tool automatically matches internal function return codes (like CardInSaf returning NOK) against technical business specifications.")
    add_bullet("<b>Dynamic Audit Generation:</b> It creates a high-quality audit report in PDF with Corporate HPS layouts, describing step-by-step transaction chronologies, highlighted alert rules, and concrete SQL debugging paths.")
    
    add_p("<b>High-Level Architecture:</b>")
    add_p("The system is divided into a <b>React Single Page Application</b> for user interaction, a <b>FastAPI</b> backend, a local <b>Regex-driven Log Parser</b>, and a <b>Multi-Agent LangGraph Workflow</b>. In addition, the platform features a document ingestion subsystem that parses Excel functional spec sheets (Spec_PowerCARD.xlsx) and registers them into a PostgreSQL vector database equipped with the <i>pgvector</i> extension for semantic searching.")
    
    add_p("<b>Folder Structure:</b>")
    add_code([
        "hpsproject/",
        "├── backend/                  # FastAPI & Agentic Subsystem",
        "│   ├── app/                  # Main Application Modules",
        "│   │   ├── core/             # Agent definitions & graph logic (agent_graph.py)",
        "│   │   ├── services/         # Domain services (log_parser.py, spec_loader.py, etc.)",
        "│   │   └── storage/          # Local file uploads, specifications, and reports",
        "│   ├── requirements.txt      # Python dependencies",
        "│   ├── ingest_docs.py        # Vector Database RAG Ingestion utility",
        "│   └── .env                  # API Key & environment configs",
        "├── frontend/                 # React UI Subsystem",
        "│   ├── src/                  # React source (App.jsx, App.css, main.jsx)",
        "│   ├── package.json          # Node dependencies",
        "│   └── vite.config.js        # Vite compilation configuration",
        "└── docker-compose.yml        # Orchestration for PostgreSQL + pgvector DB"
    ])
    story.append(PageBreak())

    # ==================== SECTION 2 ====================
    add_section("Complete Request Flow", "2")
    add_p("The lifecyle of a compliance request spans frontend execution, backend receipt, log parsing, RAG query extraction, agent reasoning, and PDF generation. Below is the step-by-step processing flow:")
    
    add_subsection("Stage 1: Trace Log Upload and Prompt Submission")
    add_bullet("<b>Involved Files:</b> frontend/src/App.jsx")
    add_bullet("<b>Functions/Components:</b> App() component, runLogAnalysis() handler.")
    add_bullet("<b>Inputs:</b> A raw monetic trace file (.TXT) and an optional user prompt.")
    add_bullet("<b>Outputs:</b> A multipart/form-data POST request.")
    add_bullet("<b>Purpose:</b> Acquires the user's focus criteria (e.g. general audit vs. specific story extraction) and the raw logs.")
    
    add_subsection("Stage 2: API Ingestion and Local Storage")
    add_bullet("<b>Involved Files:</b> backend/app/main.py")
    add_bullet("<b>Functions/Components:</b> analyze_logs() route handler.")
    add_bullet("<b>Inputs:</b> Form inputs (file: UploadFile, user_prompt: str).")
    add_bullet("<b>Outputs:</b> File written to local disk (e.g. backend/app/storage/BASE1_LCH_2.TRC019.TXT) and initialized AgentState.")
    add_bullet("<b>Purpose:</b> Persists the file for parsing and initializes the LangGraph graph context.")
    
    add_subsection("Stage 3: Demultiplexed Parsing (ParserStoryBuilder)")
    add_bullet("<b>Involved Files:</b> backend/app/core/agent_graph.py, backend/app/services/log_parser.py")
    add_bullet("<b>Functions/Components:</b> parser_story_node(), parse_trace_file_for_story().")
    add_bullet("<b>Inputs:</b> state[\"file_name\"]")
    add_bullet("<b>Outputs:</b> state[\"log_data_json\"] (serialized suspicious transactions chronology).")
    add_bullet("<b>Purpose:</b> Scans the log file, demultiplexes interleaved sessions, extracts metadata, correlates outgoing response codes with requests using STAN, and tracks function failures.")
    
    add_subsection("Stage 4: Specification Retrieval (RAG Retriever)")
    add_bullet("<b>Involved Files:</b> backend/app/core/agent_graph.py, backend/app/services/spec_loader.py")
    add_bullet("<b>Functions/Components:</b> rag_spec_retriever_node(), get_spec_context_for_functions().")
    add_bullet("<b>Inputs:</b> state[\"log_data_json\"] (extracts failed function names).")
    add_bullet("<b>Outputs:</b> state[\"rag_context\"] (markdown listing matching rules).")
    add_bullet("<b>Purpose:</b> Queries the functional specification database to provide context to the LLM regarding what the failed functions were supposed to do under spec rules.")
    
    add_subsection("Stage 5: Multi-Agent Reasoning (Compliance Auditor)")
    add_bullet("<b>Involved Files:</b> backend/app/core/agent_graph.py")
    add_bullet("<b>Functions/Components:</b> compliance_auditor_node(), ChatGoogleGenerativeAI.")
    add_bullet("<b>Inputs:</b> state[\"user_prompt\"], state[\"log_data_json\"], state[\"rag_context\"].")
    add_bullet("<b>Outputs:</b> state[\"final_response\"] (formatted Markdown audit text).")
    add_bullet("<b>Purpose:</b> Integrates the chronological log facts and the functional specification rules to compile a cohesive audit report targeting the user prompt.")
    
    add_subsection("Stage 6: PDF Report Building")
    add_bullet("<b>Involved Files:</b> backend/app/main.py")
    add_bullet("<b>Functions/Components:</b> reportlab.platypus.SimpleDocTemplate, build().")
    add_bullet("<b>Inputs:</b> state[\"final_response\"].")
    add_bullet("<b>Outputs:</b> File written to backend/app/storage/Rapport_Compliance_HPS.pdf.")
    add_bullet("<b>Purpose:</b> Converts the LLM markdown response into a formatted, print-ready PDF matching HPS corporate branding.")
    story.append(PageBreak())

    # ==================== SECTION 3 ====================
    add_section("Frontend Architecture (React)", "3")
    add_p("The frontend dashboard is designed as a single-page React application configured with Vite. Key architectural characteristics include:")
    
    add_bullet("<b>Component Structure:</b> Located inside frontend/src/App.jsx. It is a single component structure split logically into a navigation sidebar (aside) and a main content viewport (main) that displays panels dynamically based on activeTab.")
    add_bullet("<b>State Management:</b> Uses React's useState hooks to handle file attachments, loader state, API response content, local diagnostic message buffers, and activeAgent state indicators.")
    add_bullet("<b>Upload Ingestion:</b> Supports .txt/.TXT files via an HTML file input, converting files to a FormData object before executing POST queries.")
    add_bullet("<b>Active Agent HUD:</b> To enhance UX, the frontend maps backend agent progression using state variable activeAgent, showing live feedback ('Supervisor', 'LogAgent', 'FINISH') to visualize backend graph progression.")
    add_bullet("<b>Response Rendering:</b> The AI markdown report is rendered natively in the browser using the react-markdown component, allowing rich text, bullet points, and code block formatting.")
    add_bullet("<b>Error Boundaries & State UI:</b> Catches axios failures, reading custom error details passed by the FastAPI validation schema and formatting them in a red-tinted alert UI box.")
    story.append(PageBreak())

    # ==================== SECTION 4 ====================
    add_section("Backend Architecture", "4")
    add_p("The backend is built as an asynchronous FastAPI application, serving as the central controller orchestrating file management, database queries, and agentic workflows.")
    
    add_subsection("1. API Endpoint Layout")
    add_bullet("<b>GET /:</b> Basic status check ensuring connectivity.")
    add_bullet("<b>POST /api/v1/logs/analyze:</b> Main endpoint. Ingests user_prompt and trace files. Triggers LangGraph, builds PDF, and returns transaction chronology data and report markdown text.")
    add_bullet("<b>GET /api/v1/logs/download-pdf:</b> Downloads the built PDF Rapport_Compliance_HPS.pdf if it exists and exceeds minimum file-size validation.")
    
    add_subsection("2. Request Lifecycle")
    add_p("FastAPI processes incoming requests in the following sequence:")
    add_bullet("<b>CORS Validation:</b> Intercepts query, verifying origin policies to permit react integrations (ports 5173, etc.).")
    add_bullet("<b>Payload Validation:</b> Form data parameters are validated (user_prompt cannot be empty, files must have a .TXT suffix).")
    add_bullet("<b>Storage Action:</b> Ingested logs are stored under backend/app/storage/.")
    add_bullet("<b>Graph Invocation:</b> Executes the LangGraph state machine synchronously.")
    add_bullet("<b>Document Builder:</b> ReportLab compiles the final response into PDF.")
    add_bullet("<b>Response Marshalling:</b> The API returns JSON metadata to the frontend. The PDF remains on local storage, ready for download requests.")
    story.append(PageBreak())

    # ==================== SECTION 5 ====================
    add_section("Parsing Pipeline", "5")
    add_p("The parsing pipeline in <b>log_parser.py</b> is the core technical component of the application. It translates raw, interleaved ASCII log dumps into clean transaction histories without using an LLM, saving hundreds of thousands of context window tokens.")
    
    add_subsection("1. Multi-Thread Demultiplexing by Session ID")
    add_p("PowerCARD processes transactions concurrently. As a result, trace lines belonging to separate requests are interleaved in a single log file. Simple line-by-line reading would corrupt the flow representation (cross-transaction contamination).")
    add_p("To solve this, the parser extracts the unique session ID of every log line using the pattern:")
    add_code(["RE_SESSION = re.compile(r'^\\S+\\s+\\S+\\s+\\S+\\s+(\\S+?)\\|')"])
    add_p("Every line matching a session ID is collected in a session-specific state map: <i>sessions[session_id]</i>. A transaction sequence is initialized when 'Start DumpVisa()' is matched and concluded when another 'Start DumpVisa()' appears on the same session or the file ends.")
    
    add_subsection("2. Network Response Code Cross-Correlation via STAN")
    add_p("In PowerCARD, the incoming request (MTI 1100) and outgoing response (MTI 1110) are handled on different network sockets, and thus are printed under different Session IDs. The only shared identifier is the <b>STAN (System Trace Audit Number - FLD 011)</b>.")
    add_p("To correlate response codes back to request sessions, the parser executes a <b>Pre-Pass Scan</b> (<i>_build_response_code_map</i>):")
    add_bullet("Scans the log file for lines containing MTI 1110.")
    add_bullet("Matches the STAN (<i>FLD (011)</i>) and the Response Code (<i>FLD (039)</i>).")
    add_bullet("Saves a mapping { stan_number: response_code }.")
    add_bullet("During the main demultiplexing loop, when concluding a transaction, the parser looks up the transaction's STAN in the mapping and appends the response code to the story chronologically.")
    
    add_subsection("3. Dynamic Rule Generation from Excel Specifications")
    add_p("Instead of hardcoding function names like CardInSaf or CheckLimits, the parser calls <i>get_monitored_function_names()</i>. It dynamically generates regex search patterns for every function listed in the spreadsheet:")
    add_code(["rf'{re.escape(func)}\\s*\\(?\\s*(NOK|-1|-2|!=\\s*OK)'"])
    add_p("This means that if a new function is added to <i>Spec_PowerCARD.xlsx</i>, the parser will automatically detect its failures in the logs without code changes.")
    story.append(PageBreak())

    # ==================== SECTION 6 ====================
    add_section("AI / LLM Pipeline", "6")
    add_p("The AI orchestration pipeline is built on <b>LangGraph</b>, allowing developers to model agent behavior as a state machine. The workflow consists of three consecutive nodes:")
    
    add_code([
        "       [Start]",
        "          │",
        "          ▼",
        "  ┌──────────────────────┐",
        "  │  ParserStoryBuilder  │ (Demultiplexes logs, extracts failed functions)",
        "  └──────────┬───────────┘",
        "             │",
        "             ▼",
        "  ┌──────────────────────┐",
        "  │     RagRetriever     │ (Loads spec definitions for failures from Excel)",
        "  └──────────┬───────────┘",
        "             │",
        "             ▼",
        "  ┌──────────────────────┐",
        "  │  ComplianceAuditor   │ (Reasoning & report generation via Gemini-2.5-flash)",
        "  └──────────┬───────────┘",
        "             │",
        "             ▼",
        "        [Graph End]"
    ])
    
    add_p("<b>Node 1: ParserStoryBuilder</b><br/>"
          "Calls the Python parser to extract the chronologies. To avoid overwhelming the LLM's context window, it filters out healthy transactions and keeps only transactions containing alerts. It serializes this structure to JSON.")
    
    add_p("<b>Node 2: RagRetriever</b><br/>"
          "Identifies the set of unique failed functions from the log JSON. It queries the local Excel sheet metadata to build a markdown block of specifications describing what those functions are supposed to do under business rules.")
    
    add_p("<b>Node 3: ComplianceAuditor</b><br/>"
          "Combines the user's specific request prompt, the transaction JSON logs, and the RAG specification context. It compiles the prompt and executes a call to Gemini, which returns the audit report.")
    story.append(PageBreak())

    # ==================== SECTION 7 ====================
    add_section("Embeddings", "7")
    add_p("Embeddings convert textual specifications into high-dimensional numerical vectors. This mathematical representation enables the system to perform semantic searching, mapping natural language questions to concrete function requirements.")
    
    add_bullet("<b>Embedding Model:</b> The system uses <i>models/gemini-embedding-001</i> from Google via LangChain's GoogleGenerativeAIEmbeddings.")
    add_bullet("<b>Vector Dimensions:</b> The model generates dense vectors with <b>768 dimensions</b>.")
    add_bullet("<b>Semantic Metric:</b> Embeddings are matched using <b>Cosine Similarity</b> (which measures the cosine of the angle between two vectors, ranging from -1 to 1) or L2 distance.")
    add_bullet("<b>Why Embeddings are Necessary:</b> In monetics, QA engineers rarely search for exact code symbols. They ask questions like: 'How does the system handle credit card limits when offline?' By comparing the embedding of this question with the embeddings of the Excel spec sheet, the retriever locates functions like <i>CheckLimits</i> or <i>CardInSaf</i>, even if the user's question didn't use those terms.")
    
    # ==================== SECTION 8 ====================
    add_section("Vector Database", "8")
    add_p("The application uses <b>PostgreSQL</b> with the <b>pgvector</b> extension as its vector database. Below are the design specifications of the storage engine:")
    
    add_bullet("<b>Container Configuration:</b> Defined in docker-compose.yml as a service named 'db' running the <i>pgvector/pgvector:pg16</i> image.")
    add_bullet("<b>Schema Design:</b> Under the hood, pgvector stores embeddings in a table associated with the LangChain collection name: <i>hps_specifications</i>. The schema consists of columns for the document content string, the 768-dimensional embedding vector, and metadata JSON.")
    add_bullet("<b>Metadata Attributes:</b> Stores the origin filename ('Spec_PowerCARD.xlsx') and the target function name (e.g. 'CardInSaf') to allow filtering and exact matches.")
    add_bullet("<b>Indexing:</b> Re-indexes the database during document ingestion (using <i>pre_delete_collection=True</i>) to keep vectors aligned with the source Excel file.")
    add_bullet("<b>Retrieval Process:</b> Queries execute via LangChain's PGVector similarity search, computing vector distance over the database tables and returning the top-k document chunks.")
    story.append(PageBreak())

    # ==================== SECTION 9 ====================
    add_section("Prompt Engineering", "9")
    add_p("Prompt engineering controls the behavior and output formatting of the LLM. The prompt layout in `agent_graph.py` is designed to prevent hallucinations and enforce strict business formatting:")
    
    add_subsection("1. System Prompt Constraints")
    add_bullet("Forces the model to adopt the persona of an 'Agent Expert en Audit et Conformité Monétique pour les testeurs d'HPS'.")
    add_bullet("Restricts output strictly to what the user asks (e.g. if the user only asks for the story, the LLM must suppress alerts and debugging paths). This reduces token usage and prevents cluttering the UI.")
    
    add_subsection("2. Context Injection Schema")
    add_p("The prompt template injects context dynamically using three key variables:")
    add_bullet("<b>user_prompt:</b> The user's query.")
    add_bullet("<b>log_data_json:</b> The filtered transaction JSON (containing chronological facts and trace lines).")
    add_bullet("<b>rag_context:</b> The real specification requirements matching the failed functions.")
    
    add_subsection("3. Hallucination Suppression")
    add_bullet("The model is instructed to make direct references to the provided RAG context.")
    add_bullet("If a function is not present in the RAG context, the model is forbidden from inventing specifications for it.")
    story.append(PageBreak())

    # ==================== SECTION 10 ====================
    add_section("Retrieval Process", "10")
    add_p("The retrieval process locates relevant functional rules when an exception occurs. The system supports two modes of retrieval:")
    
    add_subsection("1. Static Functional Mapping (Active)")
    add_p("Currently active in `agent_graph.py`. When the log parser identifies function names returning NOK (e.g. CardInSaf), the retriever node fetches their exact metadata from the Excel sheet via <i>get_spec_context_for_functions()</i>. This acts as a direct, deterministic lookup database.")
    
    add_subsection("2. Semantic RAG Search (Target Integration)")
    add_p("Implemented in <i>ingest_docs.py</i> and mapped in the frontend. When a QA engineer queries the knowledge base directly, the system uses semantic retrieval:")
    add_bullet("The user's query is converted to a vector using the Google Generative AI Embeddings model.")
    add_bullet("A similarity search is executed against the <i>hps_specifications</i> collection in the pgvector database.")
    add_bullet("The top-k (closest vector distance) documents are retrieved and returned as the context.")
    story.append(PageBreak())

    # ==================== SECTION 11 ====================
    add_section("LLM Response Generation", "11")
    add_p("Once the prompt is constructed, it is sent to the LLM (Gemini-2.5-flash) to generate the final response. The model processes the input and formats its output as follows:")
    
    add_bullet("<b>Generative Reasoning:</b> The model matches the chronological logs against the specification context to determine compliance. For example, if the logs show that <i>CardInSaf</i> returned NOK and the specs indicate that this means a card is blacklisted, the model explains that the transaction was declined due to card status.")
    add_bullet("<b>Actionable Diagnostics:</b> The model suggests debugging steps, such as verifying specific database tables (e.g., the blacklist table) or checking routing configurations.")
    add_bullet("<b>Output Formatting:</b> The response is structured in clean Markdown, using bold text, bullet points, and code blocks for readability.")
    story.append(PageBreak())

    # ==================== SECTION 12 ====================
    add_section("Error Invalidation & Handling", "12")
    add_p("Robust error handling is implemented across all layers of the application to prevent failures and ensure system stability:")
    
    add_bullet("<b>Invalid/Missing File Upload:</b> Checked at the FastAPI entry point. If the uploaded file is empty or does not end in .txt/.TXT, the API returns a 400 Bad Request error.")
    add_bullet("<b>Empty Log Handling:</b> If the log parser finds no transactions, it returns an empty list, and the retriever node bypasses RAG lookup.")
    add_bullet("<b>API Key Validation:</b> Checked during backend startup. If no Google API key is found in the environment variables, the system raises a RuntimeError to prevent startup failures during API calls.")
    add_bullet("<b>ReportLab PDF Rendering Safeguard:</b> ReportLab fails if it encounters invalid HTML tags. The PDF builder escapes the text using `html.escape` and uses regex to convert Markdown markers (like bold or lists) into ReportLab-safe tags. If rendering still fails, a fallback routine generates a plain text PDF to ensure the user always receives a readable file.")
    add_bullet("<b>Database Connection Failures:</b> Ingest scripts are wrapped in try-except blocks to catch connection errors and output helpful troubleshooting instructions.")
    story.append(PageBreak())

    # ==================== SECTION 13 ====================
    add_section("Configuration Reference", "13")
    add_p("Key configuration parameters are managed using environment variables and standard config files:")
    
    add_subsection("1. Environment Variables (.env)")
    add_bullet("<b>GOOGLE_API_KEY / GEMINI_API_KEY:</b> Credentials for Google Generative AI.")
    add_bullet("<b>LOG_STORAGE_DIR:</b> Directory where uploaded log files are stored.")
    add_bullet("<b>GEMINI_MODEL_NAME:</b> LLM model name (defaults to gemini-2.5-flash).")
    add_bullet("<b>POWERCARD_SPEC_PATH:</b> Path to the Spec_PowerCARD.xlsx spreadsheet.")
    
    add_subsection("2. Container Setup (docker-compose.yml)")
    add_p("Configures the PostgreSQL vector database database:")
    add_bullet("Image: pgvector/pgvector:pg16")
    add_bullet("Port: 5432:5432")
    add_bullet("DB name: hps_docs_db")
    add_bullet("Credentials: postgres / password")
    
    add_subsection("3. Python Dependencies (requirements.txt)")
    add_bullet("<b>fastapi / uvicorn:</b> Web framework and server.")
    add_bullet("<b>langgraph:</b> Multi-agent orchestration framework.")
    add_bullet("<b>langchain-google-genai / google-generativeai:</b> Google Gemini API bindings.")
    add_bullet("<b>reportlab:</b> Dynamic PDF generation library.")
    add_bullet("<b>pgvector / psycopg2-binary:</b> PostgreSQL driver and vector extension.")
    add_bullet("<b>openpyxl:</b> Excel file parsing library.")
    story.append(PageBreak())

    # ==================== SECTION 14 ====================
    add_section("Project Architecture Diagrams", "14")
    add_p("Below are text-based representations of the system architecture diagrams, formatted using standard Mermaid syntax:")
    
    add_subsection("1. High-Level Architecture Diagram")
    add_code([
        "graph TD",
        "  User([User / Tester]) <-->|Uploads log / Prompt| React[React Frontend]",
        "  React <-->|REST API / JSON| FastAPI[FastAPI Backend]",
        "  subgraph FastAPI Services",
        "    LogParser[Log Parser] <-- Reads specs --> Excel[Spec_PowerCARD.xlsx]",
        "    LangGraph[LangGraph Agents] <-- Invokes --> Gemini[Gemini LLM]",
        "    ReportLab[ReportLab Builder] --> PDF[Rapport_Compliance_HPS.pdf]",
        "  end",
        "  FastAPI -->|Query / Embeddings| DB[(PostgreSQL + pgvector)]"
    ])
    
    add_subsection("2. Parsing Pipeline Diagram")
    add_code([
        "graph LR",
        "  RawLog[Raw Log File] --> Split[Split by Session ID]",
        "  Split --> Parse[Parse PAN, STAN, TX_ID]",
        "  Parse --> Match[Match NOK / Error Patterns]",
        "  Match --> Correlate[Correlate Response Codes via STAN]",
        "  Correlate --> Filter[Filter to Suspicious Transactions]",
        "  Filter --> JSON[Log Chronology JSON]"
    ])
    
    add_subsection("3. RAG Pipeline Diagram")
    add_code([
        "graph TD",
        "  Excel[Spec_PowerCARD.xlsx] --> Ingest[ingest_docs.py Ingestion]",
        "  Ingest --> Embed[Generate Embeddings via Gemini]",
        "  Embed --> Store[(PGVector Database)]",
        "  Query[User Query] --> MatchEmbed[Generate Query Embedding]",
        "  MatchEmbed --> Similarity[Cosine Similarity Search]",
        "  Similarity --> Context[Retrieve Context Chunks]"
    ])
    story.append(PageBreak())

    # ==================== SECTION 15 ====================
    add_section("Sequence Diagram", "15")
    add_p("The sequence diagram below shows the interaction flow between system components:")
    
    add_code([
        "sequenceDiagram",
        "  autonumber",
        "  actor User",
        "  participant React as React Frontend",
        "  participant FastAPI as FastAPI Backend",
        "  participant Parser as Log Parser Service",
        "  participant PGVector as PGVector DB / Excel",
        "  participant LLM as Gemini LLM API",
        "  ",
        "  User->>React: Upload .TXT Log & Submit Prompt",
        "  React->>FastAPI: POST /api/v1/logs/analyze",
        "  FastAPI->>FastAPI: Save raw log file",
        "  FastAPI->>Parser: parse_trace_file_for_story()",
        "  Parser->>Parser: Group log lines by Session ID",
        "  Parser->>Parser: Correlate request/response via STAN",
        "  Parser->>FastAPI: Return Log Chronology JSON",
        "  FastAPI->>PGVector: get_spec_context_for_functions(failed_funcs)",
        "  PGVector-->>FastAPI: Return Specification Context (RAG)",
        "  FastAPI->>LLM: Send Prompt + Log JSON + RAG Context",
        "  LLM-->>FastAPI: Return Markdown Audit Report",
        "  FastAPI->>FastAPI: Convert Markdown to Corporate PDF",
        "  FastAPI-->>React: Return JSON Response",
        "  React-->>User: Display On-Screen Markdown Report",
        "  User->>React: Request PDF Download",
        "  React->>FastAPI: GET /api/v1/logs/download-pdf",
        "  FastAPI-->>User: Return Rapport_Compliance_HPS.pdf"
    ])
    story.append(PageBreak())

    # ==================== SECTION 16 ====================
    add_section("Component Code Walkthrough", "16")
    add_p("Below is a walkthrough of the key files in the codebase, explaining their purpose, key functions, and dependencies:")
    
    add_subsection("1. backend/app/main.py")
    add_bullet("<b>Purpose:</b> Acts as the entry point for the FastAPI application, handling API routing, CORS configuration, and file uploads.")
    add_bullet("<b>Key Functions:</b> <i>analyze_logs()</i> coordinates the execution of the parsing pipeline, LangGraph workflow, PDF generation, and API responses. <i>download_pdf()</i> handles PDF download requests.")
    
    add_subsection("2. backend/app/core/agent_graph.py")
    add_bullet("<b>Purpose:</b> Orchestrates the multi-agent LangGraph workflow.")
    add_bullet("<b>Key Functions:</b> <i>parser_story_node()</i> runs the log parser on the uploaded file and stores the transaction JSON in the agent's state. <i>rag_spec_retriever_node()</i> extracts failed functions from the logs and retrieves their specifications from the Excel sheet. <i>compliance_auditor_node()</i> constructs the final prompt and queries the LLM.")
    
    add_subsection("3. backend/app/services/log_parser.py")
    add_bullet("<b>Purpose:</b> Parses the raw log files to extract transaction stories and detect failures.")
    add_bullet("<b>Key Functions:</b> <i>parse_trace_file_for_story()</i> groups logs by session ID to demultiplex concurrent transactions, uses <i>_build_response_code_map()</i> to correlate network responses via STAN, and dynamically checks for function failures using regex.")
    
    add_subsection("4. backend/app/services/spec_loader.py")
    add_bullet("<b>Purpose:</b> Interface for reading functional specifications from Excel.")
    add_bullet("<b>Key Functions:</b> <i>load_function_specs()</i> reads row data from the 'Lib' sheet of the Excel file and caches the result. <i>get_spec_context_for_functions()</i> builds the specification context markdown block for the LLM.")
    
    add_subsection("5. backend/ingest_docs.py")
    add_bullet("<b>Purpose:</b> RAG ingestion script that loads data from Excel, generates embeddings, and saves them to pgvector.")
    add_bullet("<b>Key Functions:</b> <i>charger_documents_depuis_excel()</i> reads Excel rows and converts them to LangChain Document objects. <i>initialiser_et_ingerer()</i> generates embeddings via Google Generative AI and saves them to PostgreSQL.")
    
    add_subsection("6. frontend/src/App.jsx")
    add_bullet("<b>Purpose:</b> Frontend interface for uploading files and viewing reports.")
    add_bullet("<b>Key Functions:</b> <i>runLogAnalysis()</i> handles file uploading and sends the POST request to the API. Renders the audit report using <i>react-markdown</i>.")
    story.append(PageBreak())

    # ==================== SECTION 17 ====================
    add_section("Glossary of Terms", "17")
    add_bullet("<b>RAG (Retrieval-Augmented Generation):</b> An AI architecture that retrieves relevant documents from a database and provides them as context to the LLM to improve response accuracy.")
    add_bullet("<b>Embedding:</b> A dense, high-dimensional vector representation of text that captures semantic meaning.")
    add_bullet("<b>Vector Database:</b> A database specialized in storing and querying vector embeddings.")
    add_bullet("<b>Cosine Similarity:</b> A metric used to measure similarity between two vectors.")
    add_bullet("<b>STAN (System Trace Audit Number):</b> A unique 6-digit number assigned to every electronic payment transaction, used as a correlation key.")
    add_bullet("<b>Session ID:</b> An identifier used to group log lines belonging to the same thread in concurrent logs.")
    add_bullet("<b>Hallucination:</b> A phenomenon where an LLM generates factually incorrect or unsupported information.")
    
    # ==================== SECTION 18 ====================
    add_section("Technical Suggestions", "18")
    add_p("Below are architectural recommendations to improve system performance, security, and maintainability:")
    
    add_bullet("<b>Transition to Semantic Retrieval:</b> Fully integrate the pgvector database (currently set up in <i>ingest_docs.py</i>) into <i>agent_graph.py</i>. Replace the local Excel lookup with database similarity search queries to scale to larger documentation sets.")
    add_bullet("<b>Asynchronous Job Processing:</b> Long-running log analyses can exceed HTTP timeout limits. Offload analysis tasks to an asynchronous task runner like Celery and use WebSockets or polling to update the frontend state.")
    add_bullet("<b>Enhanced Security:</b> Implement JWT-based authentication for backend endpoints and sanitize file uploads to prevent path traversal vulnerabilities.")
    add_bullet("<b>Performance Optimization:</b> Implement streaming LLM responses to the frontend using Server-Sent Events (SSE) or WebSockets to reduce perceived latency.")
    
    # ==================== SECTION 19 ====================
    add_section("Architectural Conclusion", "19")
    add_p("The <b>HPS ComplianceVerifier</b> provides an efficient solution for analyzing complex monetic transaction logs. By combining local, regex-driven parsing with agentic workflows and semantic retrieval, the system demultiplexes raw log files and automatically verifies transaction execution against business specifications.")
    add_p("Implementing the suggestions above, such as fully integrating the pgvector database and adopting asynchronous job processing, will help scale the platform and improve performance, making it a robust tool for monetic QA teams.")
    
    # Compile PDF
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Technical Documentation compiled successfully to: {os.path.abspath(filename)}")

if __name__ == '__main__':
    build_pdf()
