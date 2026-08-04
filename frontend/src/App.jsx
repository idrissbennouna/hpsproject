import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import Markdown from "react-markdown";
import ValidationAgentPanel from "./ValidationAgentPanel";
import StructuredReport from "./components/StructuredReport";
import "./App.css";

// ─── Utilitaire : timestamp relatif ──────────────────────────────────────────
function relativeTime(isoString) {
  if (!isoString) return "";
  try {
    const diff = Date.now() - new Date(isoString).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "à l'instant";
    if (mins < 60) return `il y a ${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `il y a ${hrs}h`;
    const days = Math.floor(hrs / 24);
    return `il y a ${days}j`;
  } catch {
    return "";
  }
}

// ─── Composant : Historique de conversations (sidebar) ───────────────────────
function ConversationHistory({ agentType, onSelectConversation, activeConvId, onNewConversation }) {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchConversations = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`http://127.0.0.1:8000/api/v1/conversations?agent=${agentType}&limit=10`);
      setConversations(res.data.conversations || []);
    } catch {
      setConversations([]);
    } finally {
      setLoading(false);
    }
  }, [agentType]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations, activeConvId]);

  return (
    <div className="conv-history-section">
      <div className="conv-history-header">
        <span className="conv-history-title">Historique</span>
        <button
          className="new-conv-btn"
          onClick={onNewConversation}
          title="Nouvelle analyse"
        >
          +
        </button>
      </div>
      {loading ? (
        <p className="conv-history-loading">Chargement…</p>
      ) : conversations.length === 0 ? (
        <p className="conv-history-empty">Aucune conversation enregistrée.</p>
      ) : (
        <ul className="conv-list">
          {conversations.map((conv) => (
            <li
              key={conv.id}
              className={`conv-item${activeConvId === conv.id ? " conv-item-active" : ""}`}
              onClick={() => onSelectConversation(conv)}
              title={conv.title}
            >
              <span className="conv-title">
                {conv.title.length > 30 ? conv.title.slice(0, 30) + "…" : conv.title}
              </span>
              <span className="conv-timestamp">{relativeTime(conv.last_activity)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- Composant : Sélecteur de document de spécification (Bibliothèque + Upload) ---
function SpecDocSelector({ onSpecSelected, onDocFileChange }) {
  const [mode, setMode] = useState("library"); // "library" | "upload"
  const [library, setLibrary] = useState([]);
  const [libLoading, setLibLoading] = useState(false);
  const [libError, setLibError] = useState("");
  const [selectedHash, setSelectedHash] = useState("");

  useEffect(() => {
    if (mode === "library") {
      setLibLoading(true);
      setLibError("");
      axios
        .get("http://127.0.0.1:8000/api/v1/specs/library")
        .then((res) => {
          setLibrary(res.data.documents || []);
        })
        .catch(() => {
          setLibError("Impossible de charger la bibliothèque (backend hors ligne ?).");
          setLibrary([]);
        })
        .finally(() => setLibLoading(false));
    }
  }, [mode]);

  const handleLibrarySelect = (e) => {
    const hash = e.target.value;
    setSelectedHash(hash);
    onSpecSelected(hash || null);
  };

  const handleUploadChange = (e) => {
    onDocFileChange(e.target.files[0] || null);
  };

  const formatDate = (iso) => {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleDateString("fr-FR", {
        day: "2-digit", month: "short", year: "numeric"
      });
    } catch {
      return iso.slice(0, 10);
    }
  };

  return (
    <div className="spec-selector-container">
      {/* Toggle mode */}
      <div className="spec-mode-toggle">
        <button
          id="spec-mode-library-btn"
          className={`spec-mode-btn ${mode === "library" ? "spec-mode-active" : ""}`}
          onClick={() => { setMode("library"); onDocFileChange(null); }}
          type="button"
        >
           Bibliothèque
        </button>
        <button
          id="spec-mode-upload-btn"
          className={`spec-mode-btn ${mode === "upload" ? "spec-mode-active" : ""}`}
          onClick={() => { setMode("upload"); setSelectedHash(""); onSpecSelected(null); }}
          type="button"
        >
           Nouveau PDF
        </button>
      </div>

      {/* Mode : Bibliothèque */}
      {mode === "library" && (
        <div className="spec-library-panel">
          {libLoading && <p className="spec-lib-loading">Chargement de la bibliothèque…</p>}
          {libError && <p className="spec-lib-error">{libError}</p>}
          {!libLoading && !libError && library.length === 0 && (
            <p className="spec-lib-empty">Aucun document indexé. Uploadez un PDF pour commencer.</p>
          )}
          {!libLoading && library.length > 0 && (
            <select
              id="spec-library-select"
              className="spec-library-select"
              value={selectedHash}
              onChange={handleLibrarySelect}
            >
              <option value="">— Aucun document (analyse sans spec) —</option>
              {library.map((doc) => (
                <option key={doc.file_hash} value={doc.file_hash}>
                  {doc.filename}
                  {doc.created_at ? ` · indexé le ${formatDate(doc.created_at)}` : ""}
                  {` · ${doc.chunk_count} chunks`}
                </option>
              ))}
            </select>
          )}
          {selectedHash && (
            <p className="spec-reuse-notice">
              ✓ Document existant sélectionné — sera réutilisé sans ré-embedding.
            </p>
          )}
        </div>
      )}

      {/* Mode : Upload d'un nouveau PDF */}
      {mode === "upload" && (
        <div className="file-upload-box">
          <input
            type="file"
            accept=".pdf,.PDF"
            onChange={handleUploadChange}
            className="file-input"
            id="doc-file-upload"
          />
          <label htmlFor="doc-file-upload" className="file-label">
            <span></span>
            <span>Déposer un document PDF pour cette analyse</span>
          </label>
        </div>
      )}
    </div>
  );
}

// --- Composant principal ---
function App() {
  const [prompt, setPrompt] = useState("");
  const [activeTab, setActiveTab] = useState("logs");

  // États module Logs
  const [file, setFile] = useState(null);
  const [docFile, setDocFile] = useState(null);
  const [selectedSpecHash, setSelectedSpecHash] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [activeAgent, setActiveAgent] = useState("Idle");
  const [progressDetail, setProgressDetail] = useState("");
  const [pdfFilename, setPdfFilename] = useState("");
  const [pdfFailed, setPdfFailed] = useState(false);
  const [currentJobId, setCurrentJobId] = useState(null);

  // Part A: conversation history state
  const [activeConvId, setActiveConvId] = useState(null);
  // Key to force ValidationAgentPanel remount on "new conversation"
  const [docsKey, setDocsKey] = useState(0);
  const [docsInitialConv, setDocsInitialConv] = useState(null);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setError("");
  };

  const resetLogsState = () => {
    setResult(null);
    setError("");
    setPdfFailed(false);
    setPdfFilename("");
    setActiveAgent("Idle");
    setProgressDetail("");
    setCurrentJobId(null);
    setActiveConvId(null);
    setFile(null);
    setPrompt("");
  };

  const runLogAnalysis = async () => {
    if (!file) {
      setError("Veuillez sélectionner un fichier de traces (.TXT) avant de lancer l'analyse.");
      return;
    }

    setLoading(true);
    setResult(null);
    setError("");
    setPdfFailed(false);
    setPdfFilename("");
    setActiveAgent("Supervisor (Routing...)");
    setProgressDetail("Initialisation du traitement...");

    const clientJobId = `job_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
    setCurrentJobId(clientJobId);
    setActiveConvId(clientJobId);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("job_id", clientJobId);

    // Spec : soit hash d'un doc existant, soit nouveau fichier uploadé
    if (selectedSpecHash) {
      formData.append("spec_file_hash", selectedSpecHash);
    } else if (docFile) {
      formData.append("spec_file", docFile);
      formData.append("doc_file", docFile);
    }

    const cleanPrompt =
      prompt.trim() === ""
        ? "Génère-moi la story complète de mon fichier de traces et vérifie s'il y a des alertes de non-conformité."
        : prompt;

    formData.append("user_prompt", cleanPrompt);

    const pollInterval = setInterval(async () => {
      try {
        const pollRes = await axios.get(
          `http://127.0.0.1:8000/api/v1/jobs/${clientJobId}/status`
        );
        if (pollRes.data && pollRes.data.detail) {
          setProgressDetail(pollRes.data.detail);
          setActiveAgent(`LogAgent (${pollRes.data.stage})`);
        }
      } catch (_) {}
    }, 1200);

    try {
      const response = await axios.post(
        "http://127.0.0.1:8000/api/v1/logs/analyze",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );

      clearInterval(pollInterval);
      setResult(response.data.report || response.data.analysis_report || response.data);

      if (response.data.pdf_filename) setPdfFilename(response.data.pdf_filename);
      if (response.data.pdf_generation_failed) setPdfFailed(true);

      setActiveAgent("FINISH");
      setProgressDetail("Traitement terminé.");
    } catch (err) {
      clearInterval(pollInterval);
      setError(
        err.response?.data?.detail || "Une erreur est survenue lors de l'analyse agentique."
      );
      setActiveAgent("Error");
      setProgressDetail("");
    } finally {
      setLoading(false);
    }
  };

  // Part A: Load a past logs conversation from history
  const handleSelectLogsConversation = async (conv) => {
    try {
      const res = await axios.get(`http://127.0.0.1:8000/api/v1/conversations/${conv.id}`);
      const fullConv = res.data;
      if (fullConv && fullConv.result) {
        const reportData = fullConv.result;
        setResult(reportData.report || reportData.analysis_report || reportData);
        setPdfFilename(reportData.pdf_filename || "");
        setPdfFailed(reportData.pdf_generation_failed || false);
        setCurrentJobId(conv.id);
        setActiveConvId(conv.id);
        setActiveAgent("FINISH");
        setProgressDetail("Rapport restauré depuis l'historique.");
      }
    } catch {
      // silently fail
    }
  };

  // Part A: Load a past docs conversation
  const handleSelectDocsConversation = (conv) => {
    setDocsInitialConv(conv);
    setDocsKey((k) => k + 1);
    setActiveConvId(conv.id);
  };

  const handleDownloadPDF = async () => {
    if (!pdfFilename) {
      alert("Aucun fichier PDF n'a encore été généré pour cette analyse.");
      return;
    }
    if (pdfFailed) {
      alert("La génération du document PDF a échoué côté serveur. Consultez le rapport à l'écran.");
      return;
    }
    try {
      const response = await axios.get(
        `http://127.0.0.1:8000/api/v1/logs/download-pdf?filename=${encodeURIComponent(pdfFilename)}&t=${Date.now()}`,
        { responseType: "arraybuffer" }
      );
      const blob = new Blob([response.data], { type: "application/pdf" });
      const blobURL = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobURL;
      link.download = pdfFilename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(blobURL);
    } catch {
      alert("Erreur lors du téléchargement du PDF. Veuillez ré-exécuter l'analyse.");
    }
  };

  return (
    <div className="app-container">
      {/* 1. SIDEBAR */}
      <aside className="sidebar">
        <div className="logo-area">
          <img src="/HPS_logo.png" alt="HPS Logo" className="logo-img" />
          <span className="subtitle">HPS Agentic Platform</span>
        </div>

        <nav className="nav-menu">
          <button
            className={`nav-btn ${activeTab === "logs" ? "nav-btn-active" : ""}`}
            onClick={() => setActiveTab("logs")}
          >
             Agent d'Analyse des Logs
          </button>
          <button
            className={`nav-btn ${activeTab === "docs" ? "nav-btn-active" : ""}`}
            onClick={() => setActiveTab("docs")}
          >
             Agent Documentaire (RAG)
          </button>
        </nav>

        {/* Part A: Conversation History */}
        {activeTab === "logs" && (
          <ConversationHistory
            agentType="logs"
            activeConvId={activeConvId}
            onSelectConversation={handleSelectLogsConversation}
            onNewConversation={resetLogsState}
          />
        )}
        {activeTab === "docs" && (
          <ConversationHistory
            agentType="docs"
            activeConvId={activeConvId}
            onSelectConversation={handleSelectDocsConversation}
            onNewConversation={() => {
              setDocsInitialConv(null);
              setDocsKey((k) => k + 1);
              setActiveConvId(null);
            }}
          />
        )}

        <div className="sidebar-footer">
          <p> HPS © 2026</p>
        </div>
      </aside>

      {/* 2. CONTENU PRINCIPAL */}
      <main className="main-content">
        {activeTab === "logs" && (
          <div>
            <div className="header-row">
              <div>
                <h2 className="section-title">Analyse des Traces Monétiques</h2>
                <p className="section-desc">
                  Extraction de LogStory, détection de non-conformités et levée d'alertes.
                </p>
              </div>
              <div className="agent-badge">
                <span className="badge-label">Agent Actif :</span>
                <span className={`badge-value ${loading ? "badge-active" : ""}`}>
                  {activeAgent}
                </span>
              </div>
            </div>

            <div className="dashboard-grid">
              {/* Panneau configuration */}
              <div className="card">
                <h3 className="card-title"> Configuration de l'Analyse</h3>

                <div className="form-group">
                  <label className="label">Fichier de traces réelles (.TXT) :</label>
                  <div className="file-upload-box">
                    <input
                      type="file"
                      accept=".TXT,.txt"
                      onChange={handleFileChange}
                      className="file-input"
                      id="file-upload"
                    />
                    <label htmlFor="file-upload" className="file-label">
                      <span></span>
                      <span>
                        {file ? ` ${file.name}` : "Glisser ou charger un fichier de logs"}
                      </span>
                    </label>
                  </div>
                </div>

                <div className="form-group">
                  <label className="label">Document de spécification (optionnel) :</label>
                  <SpecDocSelector
                    onSpecSelected={(hash) => setSelectedSpecHash(hash)}
                    onDocFileChange={(f) => setDocFile(f)}
                  />
                </div>

                <div className="form-group">
                  <label className="label">Consigne ou question pour l'Agent AI :</label>
                  <textarea
                    className="textarea"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Ex: Analyse ce fichier de traces et donne-moi la story ainsi que les erreurs..."
                    rows={4}
                  />
                </div>

                <button
                  id="run-analysis-btn"
                  className={`action-btn ${loading ? "action-btn-disabled" : ""}`}
                  onClick={runLogAnalysis}
                  disabled={loading}
                >
                  {loading
                    ? progressDetail || "Calcul du Graphe Multi-Agents..."
                    : "Exécuter l'Analyse Spécifique"}
                </button>

                {error && <div className="error-box">{error}</div>}
              </div>

              {/* Rapport */}
              <div className="card result-card">
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    borderBottom: "1px solid rgba(0,0,0,0.05)",
                    paddingBottom: "14px",
                    marginBottom: "20px",
                  }}
                >
                  <h3
                    className="card-title"
                    style={{ margin: 0, border: "none", padding: 0 }}
                  >
                    Rapport d'Analyse Métier
                  </h3>
                  {result && (
                    <button
                      onClick={handleDownloadPDF}
                      className={`action-btn ${pdfFailed ? "action-btn-disabled" : ""}`}
                      style={{
                        padding: "8px 16px",
                        fontSize: "13px",
                        borderRadius: "8px",
                        marginTop: 0,
                        background: pdfFailed ? "#ef4444" : undefined,
                      }}
                    >
                      {pdfFailed ? "PDF Échoué" : "Télécharger PDF"}
                    </button>
                  )}
                </div>
                {result ? (
                  <StructuredReport report={result} sessionId={currentJobId} />
                ) : (
                  <div className="empty-state">
                    {loading ? (
                      <div style={{ textAlign: "center", padding: "20px" }}>
                        <div className="loader" style={{ margin: "0 auto 16px" }}></div>
                        <p style={{ fontWeight: "600", color: "#1e3a8a", margin: "8px 0" }}>
                          {progressDetail || "Analyse agentique en cours..."}
                        </p>
                        <span style={{ fontSize: "12px", color: "#64748b" }}>
                          Veuillez patienter pendant l'exécution des nœuds du graphe...
                        </span>
                      </div>
                    ) : (
                      <p>
                        En attente du traitement du fichier de traces... Le rapport interactif
                        s'affichera sous forme de tableau de bord.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "docs" && (
          <ValidationAgentPanel
            key={docsKey}
            initialConversation={docsInitialConv}
            onConversationSaved={(convId) => setActiveConvId(convId)}
          />
        )}
      </main>
    </div>
  );
}

export default App;