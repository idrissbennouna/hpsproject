import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import Markdown from "react-markdown";

function ValidationAgentPanel({ onAnswerSuccess }) {
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Bonjour ! Je suis votre **Agent Expert en Spécifications PowerCARD**. Posez-moi vos questions sur le dictionnaire de données, les codes retours ou le comportement fonctionnel de l'application. Vous pouvez également m'envoyer un fichier PDF, TXT ou XLSX éphémère pour poser des questions directement dessus.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [error, setError] = useState("");
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  // Génération de l'UUID de session au montage
  useEffect(() => {
    const uuid = typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    setSessionId(uuid);
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, uploading]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const cleanInput = input.trim();
    if (!cleanInput || loading) return;

    setError("");
    setInput("");

    const newMessages = [...messages, { role: "user", content: cleanInput }];
    setMessages(newMessages);
    setLoading(true);

    const apiHistory = newMessages.map((msg) => ({
      role: msg.role,
      content: msg.content,
    }));

    try {
      const response = await axios.post("http://127.0.0.1:8000/api/v1/validation/ask", {
        question: cleanInput,
        chat_history: apiHistory.slice(0, -1),
        session_id: sessionId,
      });

      const data = response.data;
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.response,
          sources: data.sources || [],
        },
      ]);
      if (onAnswerSuccess) {
        onAnswerSuccess();
      }
    } catch (err) {
      console.error(err);
      setError(
        err.response?.data?.detail || "Une erreur est survenue lors de l'appel à l'agent de validation."
      );
    } finally {
      setLoading(false);
    }
  };

  // Gestion de l'upload de fichier éphémère
  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setError("");
    setUploading(true);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId);

    try {
      const response = await axios.post("http://127.0.0.1:8000/api/v1/validation/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setUploadedFiles((prev) => [...prev, file.name]);
      
      // Ajouter un message système dans le chat indiquant l'upload réussi
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `📎 *Fichier joint avec succès* : **${file.name}**. Vous pouvez maintenant poser vos questions sur son contenu !`,
        },
      ]);
    } catch (err) {
      console.error(err);
      setError(
        err.response?.data?.detail || "Échec de l'importation du fichier temporaire."
      );
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = ""; // reset file input
      }
    }
  };

  const triggerFileSelect = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="validation-panel animate-slide-in">
      <div className="header-row">
        <div>
          <h2 className="section-title">Validation & Spécifications HPS</h2>
          <p className="section-desc">
            Interrogez l'Agent AI sur les spécifications ou joignez un document éphémère de validation (PDF, TXT, XLSX).
          </p>
        </div>

        <div className="agent-badge">
          <span className="badge-label">Session ID :</span>
          <span className="badge-value" style={{ fontFamily: "monospace", fontSize: "11px", fontWeight: "normal" }}>
            {sessionId.substring(0, 8)}...
          </span>
        </div>
      </div>

      <div className="card chat-card">
        {/* Chat message display area */}
        <div className="chat-messages-container">
          {messages.map((msg, index) => (
            <div key={index} className={`chat-message-row ${msg.role}`}>
              <div className={`chat-bubble ${msg.role}`}>
                <div className="chat-bubble-author">
                  {msg.role === "user" ? "Vous" : "Agent Spécifications HPS"}
                </div>
                <div className="markdown-render">
                  <Markdown>{msg.content}</Markdown>
                </div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="chat-bubble-sources">
                    <span className="sources-title">Sources consultées :</span>
                    <div className="sources-tags">
                      {msg.sources.map((src, idx) => (
                        <span key={idx} className="source-tag">
                          {src}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="chat-message-row assistant">
              <div className="chat-bubble assistant typing">
                <span className="dot"></span>
                <span className="dot"></span>
                <span className="dot"></span>
              </div>
            </div>
          )}
          {uploading && (
            <div className="chat-message-row assistant">
              <div className="chat-bubble assistant" style={{ background: "rgba(5, 150, 105, 0.05)", border: "1px dashed rgba(5, 150, 105, 0.3)" }}>
                <span style={{ fontSize: "12px", color: "#059669" }}>⏳ Analyse et extraction du fichier en cours...</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Fichiers attachés à la session */}
        {uploadedFiles.length > 0 && (
          <div className="attached-files-row" style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "12px" }}>
            <span style={{ fontSize: "12px", fontWeight: "bold", color: "#475569" }}>Fichiers de session :</span>
            {uploadedFiles.map((fname, idx) => (
              <span key={idx} style={{ fontSize: "11px", background: "#e2e8f0", color: "#334155", padding: "2px 8px", borderRadius: "20px", display: "inline-flex", alignItems: "center", gap: "4px" }}>
                📎 {fname}
              </span>
            ))}
          </div>
        )}

        {error && <div className="error-box chat-error">{error}</div>}

        {/* Formulaire de saisie avec bouton attacher */}
        <form onSubmit={handleSubmit} className="chat-input-form">
          <input
            type="file"
            accept=".txt,.pdf,.xlsx"
            ref={fileInputRef}
            onChange={handleFileUpload}
            style={{ display: "none" }}
          />
          <button
            type="button"
            className="action-btn"
            style={{ padding: "14px 20px", background: "#f1f5f9", color: "#475569", border: "1px solid #cbd5e1", display: "flex", alignItems: "center", gap: "6px", boxShadow: "none" }}
            onClick={triggerFileSelect}
            disabled={loading || uploading}
          >
            📎
          </button>
          <input
            type="text"
            className="input chat-input-text"
            placeholder={
              uploadedFiles.length > 0 
                ? "Posez des questions sur le(s) fichier(s) joint(s) ou sur les spécifications..." 
                : "Posez votre question ou joignez un fichier..."
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading || uploading}
          />
          <button
            type="submit"
            className={`action-btn chat-send-btn ${loading || uploading || !input.trim() ? "action-btn-disabled" : ""}`}
            disabled={loading || uploading || !input.trim()}
          >
            Envoyer
          </button>
        </form>
      </div>
    </div>
  );
}

export default ValidationAgentPanel;
