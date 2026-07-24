import React, { useState, useEffect } from "react";
import axios from "axios";
import Markdown from "react-markdown";
import ValidationAgentPanel from "./ValidationAgentPanel";
import TokenUsageWidget from "./components/TokenUsageWidget";
import "./App.css";

function App() {
  // Navigation tabs state
  const [prompt, setPrompt] = useState("");
  const [activeTab, setActiveTab] = useState("logs");
  
  // States for Logs Analysis module
  const [file, setFile] = useState(null);
  const [docFile, setDocFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [activeAgent, setActiveAgent] = useState("Idle");

  // States for Documentation RAG module
  const [docQuery, setDocQuery] = useState("");
  const [docResult, setDocResult] = useState("");

  const [tokenUsage, setTokenUsage] = useState({ used: 0, budget: 1000000, remaining: 1000000, percentage: 0 });

  const fetchTokenUsage = async () => {
    try {
      const response = await axios.get("http://127.0.0.1:8000/api/v1/usage/summary");
      setTokenUsage(response.data);
    } catch (err) {
      console.error("Erreur lors de la récupération de la consommation de tokens :", err);
    }
  };

  useEffect(() => {
    fetchTokenUsage();
  }, []);

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
    setResult("");
    setError("");
    setActiveAgent("Supervisor (Routing...)");

    const formData = new FormData();
    formData.append("file", file);
    
    if (docFile) {
      formData.append("doc_file", docFile);
    }

    const cleanPrompt = prompt.trim() === "" 
      ? "Génère-moi la story complète de mon fichier de traces et vérifie s'il y a des alertes de non-conformité." 
      : prompt;

    formData.append("user_prompt", cleanPrompt);

    try {
      // Dynamic visualization simulation steps for agent states
      setTimeout(() => setActiveAgent("LogAgent (Analyse & Diagnostic...)"), 1200);

      const response = await axios.post("http://127.0.0.1:8000/api/v1/logs/analyze", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setResult(response.data.analysis_report || response.data);
      setActiveAgent("FINISH");
      fetchTokenUsage();
    } catch (err) {
      setError(err.response?.data?.detail || "Une erreur est survenue lors de l'analyse agentique.");
      setActiveAgent("Error");
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadPDF = async () => {
    try {
      const response = await axios.get(`http://127.0.0.1:8000/api/v1/logs/download-pdf?t=${Date.now()}`, {
        responseType: 'arraybuffer'
      });

      const blob = new Blob([response.data], { type: 'application/pdf' });
      const blobURL = window.URL.createObjectURL(blob);
      
      const downloadLink = document.createElement('a');
      downloadLink.href = blobURL;
      downloadLink.download = 'Rapport_Compliance_HPS.pdf';
      
      document.body.appendChild(downloadLink);
      downloadLink.click();
      
      document.body.removeChild(downloadLink);
      window.URL.revokeObjectURL(blobURL);
    } catch (err) {
      console.error("Erreur d'extraction du document PDF :", err);
      alert("Erreur lors du téléchargement du PDF. Veuillez vous assurer que l'analyse a été complétée avec succès.");
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
          <TokenUsageWidget usage={tokenUsage} />
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
                
                {tokenUsage.remaining === 0 && (
                  <div className="warning-box" style={{ marginBottom: "18px", background: "rgba(220, 38, 38, 0.08)", color: "#b91c1c", border: "1px solid rgba(220, 38, 38, 0.2)", padding: "12px", borderRadius: "10px", fontSize: "13px", display: "flex", gap: "8px", alignItems: "center" }}>
                    <span>⚠️</span>
                    <span><strong>Budget de tokens dépassé !</strong> Les requêtes continuent de fonctionner mais le quota virtuel défini est épuisé.</span>
                  </div>
                )}
                
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
                  {loading ? "Calcul du Graphe Multi-Agents..." : "Exécuter l'Analyse Spécifique"}
                </button>

                {error && <div className="error-box">{error}</div>}
              </div>

              {/* Écran d'affichage du rapport à droite */}
              <div className="card result-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid rgba(0, 0, 0, 0.05)", paddingBottom: "14px", marginBottom: "20px" }}>
                  <h3 className="card-title" style={{ margin: 0, border: "none", padding: 0 }}>Rapport d'Analyse Métier</h3>
                  {result && (
                    <button onClick={handleDownloadPDF} className="action-btn" style={{ padding: "8px 16px", fontSize: "13px", borderRadius: "8px", marginTop: 0 }}>
                       Télécharger PDF
                    </button>
                  )}
                </div>
                {result ? (
                  <div className="markdown-render">
                    <Markdown>{result}</Markdown>
                  </div>
                ) : (
                  <div className="empty-state">
                    {loading ? (
                      <div className="loader"></div>
                    ) : (
                      <p>En attente du traitement du fichier de traces... Le rapport final s'affichera sous forme de listes à puces.</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ONGLET 2 : AGENT DE DOCUMENTATION (RAG) */}
        {activeTab === "docs" && (
          <ValidationAgentPanel onAnswerSuccess={fetchTokenUsage} isBudgetExceeded={tokenUsage.remaining === 0} />
        )}

      </main>
    </div>
  );
}

export default App;