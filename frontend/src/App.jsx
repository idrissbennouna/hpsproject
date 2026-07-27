import React, { useState } from "react";
import axios from "axios";
import Markdown from "react-markdown";
import ValidationAgentPanel from "./ValidationAgentPanel";
import StructuredReport from "./components/StructuredReport";
import "./App.css";

function App() {
  // Navigation tabs state
  const [prompt, setPrompt] = useState("");
  const [activeTab, setActiveTab] = useState("logs");
  
  // States for Logs Analysis module
  const [file, setFile] = useState(null);
  const [docFile, setDocFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [activeAgent, setActiveAgent] = useState("Idle");
  const [progressDetail, setProgressDetail] = useState("");
  const [pdfFilename, setPdfFilename] = useState("");
  const [pdfFailed, setPdfFailed] = useState(false);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setError("");
  };

  const handleDocFileChange = (e) => {
    setDocFile(e.target.files[0]);
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

    const formData = new FormData();
    formData.append("file", file);
    formData.append("job_id", clientJobId);
    
    if (docFile) {
      formData.append("spec_file", docFile);
      formData.append("doc_file", docFile);
    }

    const cleanPrompt = prompt.trim() === "" 
      ? "Génère-moi la story complète de mon fichier de traces et vérifie s'il y a des alertes de non-conformité." 
      : prompt;

    formData.append("user_prompt", cleanPrompt);

    // Polling d'avancement toutes les 1.2 secondes
    const pollInterval = setInterval(async () => {
      try {
        const pollRes = await axios.get(`http://127.0.0.1:8000/api/v1/jobs/${clientJobId}/status`);
        if (pollRes.data) {
          if (pollRes.data.detail) {
            setProgressDetail(pollRes.data.detail);
            setActiveAgent(`LogAgent (${pollRes.data.stage})`);
          }
        }
      } catch (pollErr) {
        // Silently ignore 404 while job initializes
      }
    }, 1200);

    try {
      const response = await axios.post("http://127.0.0.1:8000/api/v1/logs/analyze", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      clearInterval(pollInterval);
      setResult(response.data.report || response.data.analysis_report || response.data);
      
      if (response.data.pdf_filename) {
        setPdfFilename(response.data.pdf_filename);
      }

      if (response.data.pdf_generation_failed) {
        setPdfFailed(true);
      }

      setActiveAgent("FINISH");
      setProgressDetail("Traitement terminé.");
    } catch (err) {
      clearInterval(pollInterval);
      setError(err.response?.data?.detail || "Une erreur est survenue lors de l'analyse agentique.");
      setActiveAgent("Error");
      setProgressDetail("");
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadPDF = async () => {
    if (!pdfFilename) {
      alert("Aucun fichier PDF n'a encore été généré pour cette analyse.");
      return;
    }

    if (pdfFailed) {
      alert("La génération du document PDF a échoué côté serveur. Vous pouvez consulter le rapport directement à l'écran.");
      return;
    }

    try {
      const response = await axios.get(`http://127.0.0.1:8000/api/v1/logs/download-pdf?filename=${encodeURIComponent(pdfFilename)}&t=${Date.now()}`, {
        responseType: 'arraybuffer'
      });

      const blob = new Blob([response.data], { type: 'application/pdf' });
      const blobURL = window.URL.createObjectURL(blob);
      
      const downloadLink = document.createElement('a');
      downloadLink.href = blobURL;
      downloadLink.download = pdfFilename;
      
      document.body.appendChild(downloadLink);
      downloadLink.click();
      
      document.body.removeChild(downloadLink);
      window.URL.revokeObjectURL(blobURL);
    } catch (err) {
      console.error("Erreur d'extraction du document PDF :", err);
      alert("Erreur lors du téléchargement du PDF. Veuillez ré-exécuter l'analyse.");
    }
  };

  const runDocQuery = () => {
    if (!docQuery) return;
    setDocResult(` **Réponse simulée de l'Agent Documentaire :**\n\nL'analyse des spécifications associées à votre question est en cours de développement.\n\n*Prochaine étape : Interconnexion de la base de données PostgreSQL + pgvector pour parser les fichiers Excel, Word et PDF.*`);
  };

  return (
    <div className="app-container">
      {/* 1. SIDEBAR LATÉRALE */}
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

        <div className="sidebar-footer">
          <p> HPS © 2026</p>
        </div>
      </aside>

      {/* 2. CONTENU PRINCIPAL DYNAMIQUE */}
      <main className="main-content">
        
        {/* ONGLET 1 : AGENT DES LOGS */}
        {activeTab === "logs" && (
          <div>
            <div className="header-row">
              <div>
                <h2 className="section-title">Analyse des Traces Monétiques</h2>
                <p className="section-desc">Extraction de LogStory, détection de non-conformités et levée d'alertes.</p>
              </div>
              
              {/* Indicateur d'Agent en Direct */}
              <div className="agent-badge">
                <span className="badge-label">Agent Actif :</span>
                <span className={`badge-value ${loading ? "badge-active" : ""}`}>{activeAgent}</span>
              </div>
            </div>

            <div className="dashboard-grid">
              {/* Panneau de configuration à gauche */}
              <div className="card">
                <h3 className="card-title"> Configuration de l'Analyse</h3>
                
                <div className="form-group">
                  <label className="label">Fichier de traces réelles (.TXT) :</label>
                  <div className="file-upload-box">
                    <input type="file" accept=".TXT,.txt" onChange={handleFileChange} className="file-input" id="file-upload" />
                    <label htmlFor="file-upload" className="file-label">
                      <span></span>
                      <span>{file ? ` ${file.name}` : "Glisser ou charger un fichier de logs"}</span>
                    </label>
                  </div>
                </div>

                <div className="form-group">
                  <label className="label">Document de spécification (optionnel) :</label>
                  <div className="file-upload-box">
                    <input
                      type="file"
                      accept=".pdf,.PDF"
                      onChange={handleDocFileChange}
                      className="file-input"
                      id="doc-file-upload"
                    />
                    <label htmlFor="doc-file-upload" className="file-label">
                      <span></span>
                      <span>{docFile ? ` ${docFile.name}` : "Déposer un document (PDF) pour cette analyse"}</span>
                    </label>
                  </div>
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
                  className={`action-btn ${loading ? "action-btn-disabled" : ""}`} 
                  onClick={runLogAnalysis}
                  disabled={loading}
                >
                  {loading ? (progressDetail || "Calcul du Graphe Multi-Agents...") : "Exécuter l'Analyse Spécifique"}
                </button>

                {error && <div className="error-box">{error}</div>}
              </div>

              {/* Écran d'affichage du rapport à droite */}
              <div className="card result-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid rgba(0, 0, 0, 0.05)", paddingBottom: "14px", marginBottom: "20px" }}>
                  <h3 className="card-title" style={{ margin: 0, border: "none", padding: 0 }}>Rapport d'Analyse Métier</h3>
                  {result && (
                    <button 
                      onClick={handleDownloadPDF} 
                      className={`action-btn ${pdfFailed ? "action-btn-disabled" : ""}`} 
                      style={{ padding: "8px 16px", fontSize: "13px", borderRadius: "8px", marginTop: 0, background: pdfFailed ? "#ef4444" : undefined }}
                    >
                      {pdfFailed ? "PDF Échoué" : "Télécharger PDF"}
                    </button>
                  )}
                </div>
                {result ? (
                  <StructuredReport report={result} />
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
                      <p>En attente du traitement du fichier de traces... Le rapport interactif s'affichera sous forme de tableau de bord.</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ONGLET 2 : AGENT DE DOCUMENTATION (RAG) */}
        {activeTab === "docs" && (
          <ValidationAgentPanel />
        )}

      </main>
    </div>
  );
}

export default App;