import React, { useState } from 'react';
import axios from 'axios';
import Markdown from 'react-markdown';

function App() {
  const [file, setFile] = useState(null);
  const [prompt, setPrompt] = useState("Génère-moi la story complète de mon fichier de traces et vérifie s'il y a des alertes de non-conformité.");
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState("");
  const [error, setError] = useState("");

  const handleFileChange = (e) => {
    if (e.target.files[0]) {
      setFile(e.target.files[0]);
      setError("");
    }
  };

  const handleAnalyze = async (e) => {
    e.preventDefault();
    if (!file) {
      setError("Veuillez sélectionner un fichier de traces (.TXT) avant de lancer l'analyse.");
      return;
    }

    setLoading(true);
    setError("");
    setReport("");

    // Préparation des données multipart pour FastAPI
    const formData = new FormData();
    formData.append("file", file);
    formData.append("user_prompt", prompt);

    try {
      const response = await axios.post("http://127.0.0.1:8000/api/v1/logs/analyze", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      if (response.data.success) {
        setReport(response.data.analysis_report);
      } else {
        setError("L'analyse a échoué sans retour d'erreur précis.");
      }
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.detail || "Impossible de joindre le serveur backend FastAPI. Vérifiez qu'il est bien lancé.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ fontFamily: 'Segoe UI, Tahoma, Geneva, Verdana, sans-serif', backgroundColor: '#f4f6f9', minHeight: '100vh', padding: '40px 20px' }}>
      
      {/* Header Plateforme */}
      <header style={{ maxWidth: '1000px', margin: '0 auto 30px auto', textAlign: 'center' }}>
        <h1 style={{ color: '#0f2c59', marginBottom: '10px', fontSize: '2.5rem', fontWeight: '700' }}>ComplianceVerifier</h1>
        <p style={{ color: '#6c757d', fontSize: '1.1rem' }}>Plateforme Agentique IA pour la Validation des Traces Monétiques — HPS</p>
      </header>

      <main style={{ maxWidth: '1000px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '30px' }}>
        
        {/* Formulaire de configuration */}
        <section style={{ backgroundColor: '#ffffff', padding: '30px', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.05)' }}>
          <h2 style={{ color: '#1d3557', marginTop: '0', marginBottom: '20px', fontSize: '1.4rem' }}>⚙️ Paramètres d'analyse de l'Agent de Logs</h2>
          
          <form onSubmit={handleAnalyze} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            
            {/* Zone d'upload de fichier */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ fontWeight: '600', color: '#495057' }}>Fichier de traces monétiques (.TXT) :</label>
              <div style={{ border: '2px dashed #ced4da', padding: '20px', borderRadius: '8px', textAlign: 'center', backgroundColor: '#fafafa', cursor: 'pointer' }}>
                <input 
                  type="file" 
                  accept=".TXT,.txt" 
                  onChange={handleFileChange} 
                  style={{ cursor: 'pointer' }}
                />
                {file && <p style={{ color: '#2a9d8f', marginTop: '10px', fontWeight: '500' }}>✔️ Fichier sélectionné : {file.name}</p>}
              </div>
            </div>

            {/* Instruction pour l'agent */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ fontWeight: '600', color: '#495057' }}>Consigne ou question pour l'Agent :</label>
              <textarea 
                rows="3"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid #ced4da', fontSize: '1rem', resize: 'vertical', fontFamily: 'inherit' }}
              />
            </div>

            {/* Bouton d'action */}
            <button 
              type="submit" 
              disabled={loading}
              style={{ backgroundColor: loading ? '#a8dadc' : '#0f2c59', color: '#ffffff', border: 'none', padding: '14px', borderRadius: '8px', fontSize: '1.1rem', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', transition: 'background-color 0.2s' }}
            >
              {loading ? "🤖 L'Agent analyse le fichier de logs..." : "🚀 Lancer l'Analyse Agentique"}
            </button>
          </form>

          {error && (
            <div style={{ marginTop: '20px', padding: '15px', backgroundColor: '#ffe3e3', borderLeft: '5px solid #e63946', borderRadius: '4px', color: '#d00000', fontWeight: '500' }}>
              ⚠️ {error}
            </div>
          )}
        </section>

        {/* Section d'affichage des résultats */}
        {report && (
          <section style={{ backgroundColor: '#ffffff', padding: '40px', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.05)', borderTop: '6px solid #0f2c59' }}>
            <h2 style={{ color: '#0f2c59', marginTop: '0', marginBottom: '20px', borderBottom: '2px solid #f1f3f5', paddingBottom: '10px' }}>📋 Rapport d'Analyse IA Émis</h2>
            
            <div style={{ color: '#2b2d42', lineHeight: '1.7', fontSize: '1.05rem' }}>
              <Markdown>{report}</Markdown>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default App;