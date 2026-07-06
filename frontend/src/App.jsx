import React, { useState } from "react";
import axios from "axios";
import Markdown from "react-markdown";

function App() {
  // Gestion de la navigation dans la plateforme
  const [prompt, setPrompt] = useState("");
  const [activeTab, setActiveTab] = useState("logs");
  
  // États pour le module Logs
  const [file, setFile] = useState(null);
  
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [activeAgent, setActiveAgent] = useState("Idle"); // Statut du graphe

  // États pour le module Documentation (Futur RAG)
  const [docQuery, setDocQuery] = useState("");
  const [docResult, setDocResult] = useState("");

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setError("");
  };

  // Nouvelle fonction pour récupérer le PDF généré par le backend FastAPI
  const handleDownloadPDF = async () => {
  try {
    // On ajoute un paramètre de timestamp (?t=...) pour briser le cache du navigateur
    const response = await axios.get(`http://127.0.0.1:8000/api/v1/logs/download-pdf?t=${Date.now()}`, {
      responseType: 'arraybuffer' // Utilisation d'arraybuffer pour une capture binaire brute plus robuste
    });

    // Conversion en Blob d'application PDF
    const blob = new Blob([response.data], { type: 'application/pdf' });
    const blobURL = window.URL.createObjectURL(blob);
    
    // Création du déclencheur de téléchargement
    const downloadLink = document.createElement('a');
    downloadLink.href = blobURL;
    downloadLink.download = 'Rapport_HPS.pdf'; // Force le téléchargement plutôt que l'affichage
    
    document.body.appendChild(downloadLink);
    downloadLink.click();
    
    // Nettoyage immédiat de la mémoire
    document.body.removeChild(downloadLink);
    window.URL.revokeObjectURL(blobURL);

  } catch (err) {
    console.error("Erreur d'extraction du document PDF :", err);
    alert("Erreur lors du téléchargement direct du PDF.");
  }
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
   
    const cleanPrompt = prompt.trim() === "" 
      ? "Génère-moi la story complète de mon fichier de traces et vérifie s'il y a des alertes de non-conformité." 
      : prompt;

    formData.append("user_prompt", cleanPrompt);

    try {
      setTimeout(() => setActiveAgent("LogAgent (Analyse & Diagnostic...)"), 1200);

      const response = await axios.post("http://127.0.0.1:8000/api/v1/logs/analyze", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setResult(response.data.analysis_report || response.data);
      setActiveAgent("FINISH");
    } catch (err) {
      setError(err.response?.data?.detail || "Une erreur est survenue lors de l'analyse agentique.");
      setActiveAgent("Error");
    } finally {
      setLoading(false);
    }
  };

  const runDocQuery = () => {
    if (!docQuery) return;
    setDocResult(`📚 **Réponse simulée de l'Agent Documentaire :**\n\nL'analyse des spécifications associées à votre question est en cours de développement.\n\n*Prochaine étape : Interconnexion de la base de données PostgreSQL + pgvector pour parser les fichiers Excel, Word et PDF.*`);
  };

  return (
    <div style={styles.appContainer}>
      {/* 1. SIDEBAR LATÉRALE */}
      <aside style={styles.sidebar}>
        <div style={styles.logoArea}>
          <h1 style={styles.mainTitle}>ComplianceVerifier</h1>
          <span style={styles.subtitle}>HPS Agentic Platform</span>
        </div>
        
        <nav style={styles.navMenu}>
          <button 
            style={{...styles.navBtn, ...(activeTab === "logs" ? styles.navBtnActive : {})}}
            onClick={() => setActiveTab("logs")}
          >
            ⚙️ Agent d'Analyse des Logs
          </button>
          <button 
            style={{...styles.navBtn, ...(activeTab === "docs" ? styles.navBtnActive : {})}}
            onClick={() => setActiveTab("docs")}
          >
            📚 Agent Documentaire (RAG)
          </button>
        </nav>

        <div style={styles.sidebarFooter}>
          <p>4ème Année Ingénierie</p>
          <p>EMSI &times; HPS © 2026</p>
        </div>
      </aside>

      {/* 2. CONTENU PRINCIPAL DYNAMIQUE */}
      <main style={styles.mainContent}>
        
        {/* ONGLET 1 : AGENT DES LOGS */}
        {activeTab === "logs" && (
          <div>
            <div style={styles.headerRow}>
              <div>
                <h2 style={styles.sectionTitle}>Analyse des Traces Monétiques</h2>
                <p style={styles.sectionDesc}>Extraction de LogStory, détection de non-conformités et levée d'alertes.</p>
              </div>
              
              <div style={styles.agentBadge}>
                <span style={styles.badgeLabel}>Agent Actif :</span>
                <span style={styles.badgeValue}>{activeAgent}</span>
              </div>
            </div>

            <div style={styles.dashboardGrid}>
              {/* Panneau de configuration à gauche */}
              <div style={styles.card}>
                <h3 style={styles.cardTitle}>Configuration de l'Analyse</h3>
                
                <div style={styles.formGroup}>
                  <label style={styles.label}>Fichier de traces réelles (.TXT) :</label>
                  <div style={styles.fileUploadBox}>
                    <input type="file" accept=".TXT,.txt" onChange={handleFileChange} style={styles.fileInput} id="file-upload" />
                    <label htmlFor="file-upload" style={styles.fileLabel}>
                      {file ? `📄 ${file.name}` : "Glisser ou charger un fichier de logs"}
                    </label>
                  </div>
                </div>

                <div style={styles.formGroup}>
                  <label style={styles.label}>Consigne ou question pour l'Agent AI :</label>
                  <textarea 
                    style={styles.textarea} 
                    value={prompt} 
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Ex: Analyse ce fichier de traces et donne-moi la story ainsi que les erreurs..."
                    rows={3}
                  />
                </div>

                <button 
                  style={{...styles.actionBtn, ...(loading ? styles.actionBtnDisabled : {})}} 
                  onClick={runLogAnalysis}
                  disabled={loading}
                >
                  {loading ? "Calcul du Graphe Multi-Agents..." : "🚀 Exécuter l'Analyse Spécifique"}
                </button>

                {error && <div style={styles.errorBox}>⚠️ {error}</div>}
              </div>

              {/* Écran d'affichage du rapport à droite (STRUCTURE DASHBOARD AMÉLIORÉE) */}
              <div style={{...styles.card, ...styles.resultCard}}>
                {result ? (
                  <div style={styles.dashboardView}>
                    {/* En-tête du Dashboard */}
                    <div style={styles.dashboardHeader}>
                      <div>
                        <h3 style={styles.dashboardTitle}>Rapport d'Analyse Métier — Mode QA</h3>
                        <small style={styles.dashboardMeta}>Source de validation : Spec_PowerCARD.xlsx</small>
                      </div>
                      <button onClick={handleDownloadPDF} style={styles.pdfBtn}>
                        📄 Télécharger PDF
                      </button>
                    </div>

                    {/* Section Contexte / Identifiants */}
                    <div style={styles.dashboardSection}>
                      <h4 style={styles.sectionSubTitle}>Contexte de l'Analyse</h4>
                      <div style={styles.badgeGroup}>
                        <span style={styles.dangerBadge}>transaction_id: NULL</span>
                        <span style={styles.dangerBadge}>stan: NULL</span>
                        <span style={styles.dangerBadge}>pan: NULL</span>
                      </div>
                    </div>

                    {/* Section LogStory & Markdown Parser intégré proprement */}
                    <div style={styles.dashboardSection}>
                      <h4 style={styles.sectionSubTitle}>Déroulement Chronologique & Diagnostic</h4>
                      <div style={styles.markdownRender}>
                        <Markdown>{result}</Markdown>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div style={styles.emptyState}>
                    {loading ? (
                      <div style={styles.loader}></div>
                    ) : (
                      <p>En attente du traitement du fichier de traces... Le rapport analytique complet s'affichera ici structuré par blocs.</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ONGLET 2 : AGENT DE DOCUMENTATION */}
        {activeTab === "docs" && (
          <div>
            <h2 style={styles.sectionTitle}>Base Documentaire Intégrée</h2>
            <p style={styles.sectionDesc}>Interrogation intelligente des spécifications, guides d'implémentation et fichiers Excel de paramétrage.</p>
            
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Requête Spécifications (Module RAG)</h3>
              <div style={styles.formGroup}>
                <label style={styles.label}>Posez une question sur le dictionnaire des données ou les messages PowerCARD :</label>
                <input 
                  type="text" 
                  style={styles.input} 
                  placeholder="Ex: Quelle table gère la retransmission SAF en cas de timeout ?" 
                  value={docQuery}
                  onChange={(e) => setDocQuery(e.target.value)}
                />
              </div>
              <button style={styles.actionBtn} onClick={runDocQuery}>Interroger la documentation</button>

              {docResult && (
                <div style={{...styles.markdownRender, marginTop: "20px", borderTop: "1px solid #e2e8f0", paddingTop: "20px"}}>
                  <Markdown>{docResult}</Markdown>
                </div>
              )}
            </div>
          </div>
        )}

      </main>
    </div>
  );
}

// 🎨 DESIGN SYSTEM HPS-COMPLIANCE (Avec ajouts des styles Dashboard)
const styles = {
  appContainer: {
    display: "flex",
    height: "100vh",
    width: "100vw",
    fontFamily: "'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    backgroundColor: "#f8fafc",
    color: "#1e293b",
    overflow: "hidden",
  },
  sidebar: {
    width: "280px",
    backgroundColor: "#0f172a",
    color: "#ffffff",
    display: "flex",
    flexDirection: "column",
    padding: "24px",
    borderRight: "1px solid #1e293b",
  },
  logoArea: {
    marginBottom: "40px",
    borderBottom: "1px solid #334155",
    paddingBottom: "16px",
  },
  mainTitle: {
    fontSize: "22px",
    fontWeight: "700",
    color: "#38bdf8",
    margin: 0,
  },
  subtitle: {
    fontSize: "12px",
    color: "#94a3b8",
  },
  navMenu: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    flexGrow: 1,
  },
  navBtn: {
    width: "100%",
    padding: "14px 16px",
    backgroundColor: "transparent",
    color: "#94a3b8",
    border: "none",
    borderRadius: "8px",
    textAlign: "left",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: "600",
    transition: "all 0.2s ease",
  },
  navBtnActive: {
    backgroundColor: "#1e293b",
    color: "#ffffff",
    borderLeft: "4px solid #38bdf8",
  },
  sidebarFooter: {
    fontSize: "11px",
    color: "#64748b",
    textAlign: "center",
    borderTop: "1px solid #334155",
    paddingTop: "12px",
  },
  mainContent: {
    flexGrow: 1,
    padding: "40px",
    overflowY: "auto",
  },
  headerRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "32px",
  },
  sectionTitle: {
    fontSize: "28px",
    fontWeight: "700",
    color: "#0f172a",
    margin: "0 0 4px 0",
  },
  sectionDesc: {
    fontSize: "14px",
    color: "#64748b",
    margin: 0,
  },
  agentBadge: {
    backgroundColor: "#e2e8f0",
    padding: "10px 16px",
    borderRadius: "30px",
    fontSize: "13px",
  },
  badgeLabel: {
    color: "#64748b",
    marginRight: "6px",
  },
  badgeValue: {
    fontWeight: "700",
    color: "#0284c7",
  },
  dashboardGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1.6fr",
    gap: "24px",
  },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: "12px",
    padding: "24px",
    boxShadow: "0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03)",
    border: "1px solid #e2e8f0",
    display: "flex",
    flexDirection: "column",
  },
  resultCard: {
    minHeight: "550px",
  },
  cardTitle: {
    fontSize: "18px",
    fontWeight: "600",
    color: "#0f172a",
    margin: "0 0 20px 0",
    borderBottom: "2px solid #f1f5f9",
    paddingBottom: "10px",
  },
  formGroup: {
    marginBottom: "20px",
  },
  label: {
    display: "block",
    fontSize: "13px",
    fontWeight: "600",
    color: "#475569",
    marginBottom: "8px",
  },
  fileUploadBox: {
    border: "2px dashed #cbd5e1",
    borderRadius: "8px",
    padding: "20px",
    textAlign: "center",
    backgroundColor: "#f8fafc",
    cursor: "pointer",
  },
  fileInput: {
    display: "none",
  },
  fileLabel: {
    cursor: "pointer",
    fontSize: "14px",
    color: "#475569",
    fontWeight: "500",
  },
  textarea: {
    width: "100%",
    boxSizing: "border-box",
    padding: "14px",
    borderRadius: "10px",
    border: "1px solid #cbd5e1",
    fontSize: "14px",
    fontFamily: "inherit",
    resize: "none",
    color: "#334155",
    backgroundColor: "#ffffff",
    outline: "none",
  },
  input: {
    width: "100%",
    boxSizing: "border-box",
    padding: "12px",
    borderRadius: "8px",
    border: "1px solid #cbd5e1",
    fontSize: "14px",
  },
  actionBtn: {
    backgroundColor: "#0284c7",
    color: "#ffffff",
    padding: "14px",
    border: "none",
    borderRadius: "8px",
    fontWeight: "600",
    fontSize: "14px",
    cursor: "pointer",
    transition: "background-color 0.2s",
  },
  actionBtnDisabled: {
    backgroundColor: "#94a3b8",
    cursor: "not-allowed",
  },
  errorBox: {
    marginTop: "16px",
    backgroundColor: "#fef2f2",
    color: "#dc2626",
    padding: "12px",
    borderRadius: "6px",
    fontSize: "13px",
    border: "1px solid #fee2e2",
  },
  emptyState: {
    flexGrow: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#94a3b8",
    textAlign: "center",
    fontSize: "14px",
    padding: "20px",
  },
  loader: {
    border: "4px solid #f3f3f3",
    borderTop: "4px solid #0284c7",
    borderRadius: "50%",
    width: "30px",
    height: "30px",
    animation: "spin 1s linear infinite",
  },

  // NOUVEAUX STYLES INTERNES POUR LE RENDU DU DASHBOARD
  dashboardView: {
    display: "flex",
    flexDirection: "column",
    textAlign: "left", // Force l'alignement global à gauche
    width: "100%",
  },
  dashboardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    borderBottom: "2px solid #0284c7",
    paddingBottom: "14px",
    marginBottom: "20px",
  },
  dashboardTitle: {
    fontSize: "18px",
    fontWeight: "700",
    color: "#0284c7",
    margin: 0,
  },
  dashboardMeta: {
    fontSize: "12px",
    color: "#64748b",
  },
  pdfBtn: {
    backgroundColor: "#0284c7",
    color: "#ffffff",
    border: "none",
    padding: "8px 16px",
    borderRadius: "6px",
    fontWeight: "600",
    fontSize: "13px",
    cursor: "pointer",
  },
  dashboardSection: {
    marginBottom: "22px",
  },
  sectionSubTitle: {
    fontSize: "14px",
    fontWeight: "600",
    color: "#1e293b",
    margin: "0 0 10px 0",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
  },
  badgeGroup: {
    display: "flex",
    gap: "10px",
  },
  dangerBadge: {
    backgroundColor: "#fee2e2",
    color: "#991b1b",
    padding: "6px 12px",
    borderRadius: "6px",
    fontFamily: "monospace",
    fontSize: "12px",
    border: "1px solid #fca5a5",
  },
  markdownRender: {
    fontSize: "14px",
    lineHeight: "1.6",
    color: "#334155",
    textAlign: "left", // Élimine tout centrage Markdown résiduel
  }
};

export default App;