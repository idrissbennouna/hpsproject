import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Nettoie le Markdown LLM pour un rendu plus professionnel. */
function prepareAssistantMarkdown(raw) {
  if (!raw) return "";
  let text = String(raw);

  // Retire les emojis décoratifs en tête de ligne / titre
  text = text.replace(
    /^(\s*#{1,4}\s*)(?:[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]+\s*)+/gmu,
    "$1"
  );
  text = text.replace(
    /^(\s*[-*]\s*)(?:[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]+\s*)+/gmu,
    "$1"
  );
  text = text.replace(
    /^(?:\s*)(?:[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]+\s*)+(?=\*\*|#{1,4}|[A-Za-zÀ-ÿ])/gmu,
    ""
  );

  // Corrige les séparateurs de tableaux LLM cassés (||)
  text = text.replace(/\|\|/g, "|");

  // Assure une ligne vide avant un tableau markdown
  text = text.replace(/([^\n])\n(\|[-:| ]+\|)/g, "$1\n\n$2");
  text = text.replace(/([^\n|])\n(\|[^\n]+\|)/g, "$1\n\n$2");

  return text.trim();
}

function AssistantMarkdown({ content }) {
  return (
    <div className="spec-doc-body">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="spec-table-wrap">
              <table className="spec-doc-table">{children}</table>
            </div>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {prepareAssistantMarkdown(content)}
      </Markdown>
    </div>
  );
}

function ValidationAgentPanel({ onAnswerSuccess, initialConversation, onConversationSaved }) {
  const [sessionId, setSessionId] = useState("");
  const [convId, setConvId] = useState(initialConversation?.id || null);

  const [messages, setMessages] = useState(() => {
    if (initialConversation && Array.isArray(initialConversation.messages) && initialConversation.messages.length > 0) {
      return initialConversation.messages;
    }
    return [
      {
        role: "assistant",
        content:
          "Bienvenue dans l’espace **Spécifications PowerCARD**.\n\n" +
          "Interrogez le référentiel sur le dictionnaire de données, les codes retour (ex. Field 39), " +
          "ou le comportement fonctionnel. Vous pouvez aussi joindre un PDF, TXT ou XLSX pour une analyse ciblée.",
      },
    ];
  });

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [error, setError] = useState("");
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    const uuid =
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    setSessionId(uuid);
  }, []);

  useEffect(() => {
    if (initialConversation) {
      setMessages([]);
      setError("");
      setConvId(initialConversation.id);
      axios
        .get(`http://127.0.0.1:8000/api/v1/conversations/${initialConversation.id}`)
        .then((res) => {
          const conv = res.data;
          if (conv && Array.isArray(conv.messages) && conv.messages.length > 0) {
            setMessages(conv.messages);
          }
        })
        .catch((err) => {
          const status = err.response?.status;
          const detail = err.response?.data?.detail;
          if (status === 404) {
            setError(`Conversation introuvable (id: ${initialConversation.id}). Elle a peut-être été supprimée.`);
          } else {
            setError(detail || "Erreur lors du chargement de la conversation depuis l'historique.");
          }
        });
    }
  }, [initialConversation]);

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
        conv_id: convId,
      });

      const data = response.data;

      if (data.conv_id) {
        setConvId(data.conv_id);
        if (onConversationSaved) onConversationSaved(data.conv_id);
      }

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

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setError("");
    setUploading(true);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId);

    try {
      await axios.post("http://127.0.0.1:8000/api/v1/validation/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setUploadedFiles((prev) => [...prev, file.name]);

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Document joint : **${file.name}**.\n\nVous pouvez maintenant poser des questions sur son contenu.`,
        },
      ]);
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.detail || "Échec de l'importation du fichier temporaire.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
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
          <h2 className="section-title">Spécifications &amp; Documentation</h2>
          <p className="section-desc">
            Consultez le référentiel PowerCARD / ISO 8583 ou joignez un document de session (PDF, TXT, XLSX).
          </p>
        </div>

        <div className="agent-badge">
          <span className="badge-label">Session</span>
          <span className="badge-value" style={{ fontFamily: "monospace", fontSize: "11px", fontWeight: "normal" }}>
            {sessionId.substring(0, 8)}…
          </span>
        </div>
      </div>

      <div className="card chat-card spec-workspace">
        <div className="chat-messages-container spec-feed">
          {messages.map((msg, index) =>
            msg.role === "user" ? (
              <div key={index} className="chat-message-row user">
                <div className="chat-bubble user spec-query-bubble">
                  <div className="chat-bubble-author">Votre question</div>
                  <div className="markdown-render">
                    <Markdown>{msg.content}</Markdown>
                  </div>
                </div>
              </div>
            ) : (
              <article key={index} className="spec-answer-card">
                <header className="spec-answer-header">
                  <div className="spec-answer-brand">
                    <span className="spec-answer-mark" aria-hidden="true" />
                    <div>
                      <div className="spec-answer-title">Réponse documentation</div>
                      <div className="spec-answer-subtitle">Référentiel PowerCARD · ISO 8583</div>
                    </div>
                  </div>
                </header>

                <AssistantMarkdown content={msg.content} />

                {msg.sources && msg.sources.length > 0 && (
                  <footer className="spec-answer-sources">
                    <span className="sources-title">Sources</span>
                    <div className="sources-tags">
                      {msg.sources.map((src, idx) => (
                        <span key={idx} className="source-tag">
                          {src}
                        </span>
                      ))}
                    </div>
                  </footer>
                )}
              </article>
            )
          )}

          {loading && (
            <div className="spec-answer-card spec-answer-loading">
              <div className="spec-loading-row">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
                <span className="spec-loading-label">Recherche dans les spécifications…</span>
              </div>
            </div>
          )}

          {uploading && (
            <div className="spec-answer-card spec-answer-loading">
              <span className="spec-loading-label">Indexation du document en cours…</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {uploadedFiles.length > 0 && (
          <div className="attached-files-row">
            <span className="attached-files-label">Documents de session</span>
            {uploadedFiles.map((fname, idx) => (
              <span key={idx} className="attached-file-chip">
                {fname}
              </span>
            ))}
          </div>
        )}

        {error && <div className="error-box chat-error">{error}</div>}

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
            className="spec-attach-btn"
            onClick={triggerFileSelect}
            disabled={loading || uploading}
            title="Joindre un document"
            aria-label="Joindre un document"
          >
            +
          </button>
          <input
            type="text"
            className="input chat-input-text"
            placeholder={
              uploadedFiles.length > 0
                ? "Question sur le(s) document(s) joint(s) ou les spécifications…"
                : "Ex. : Quels sont les codes Field 39 pour un refus émetteur ?"
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
