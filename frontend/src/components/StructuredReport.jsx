import React, { useState, useRef, useEffect } from "react";
import Markdown from "react-markdown";
import axios from "axios";

// ─── Modale d'aide contextuelle pour une fonction en échec ──────────────────
function FunctionDocModal({ functionName, sessionId, onClose }) {
  const [loading, setLoading] = useState(true);
  const [docData, setDocData] = useState(null);
  const [error, setError] = useState("");
  const modalRef = useRef(null);

  useEffect(() => {
    const url = sessionId
      ? `http://127.0.0.1:8000/api/v1/functions/${encodeURIComponent(functionName)}/doc?session_id=${encodeURIComponent(sessionId)}`
      : `http://127.0.0.1:8000/api/v1/functions/${encodeURIComponent(functionName)}/doc`;

    axios
      .get(url)
      .then((res) => setDocData(res.data))
      .catch((err) => {
        const detail = err.response?.data?.detail || "Impossible de charger la documentation pour cette fonction.";
        setError(detail);
      })
      .finally(() => setLoading(false));
  }, [functionName, sessionId]);

  // Fermeture avec Escape
  useEffect(() => {
    const handleKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // Fermeture en cliquant à l'extérieur
  const handleBackdropClick = (e) => {
    if (modalRef.current && !modalRef.current.contains(e.target)) onClose();
  };

  return (
    <div className="func-modal-backdrop" onClick={handleBackdropClick} role="dialog" aria-modal="true">
      <div className="func-modal" ref={modalRef}>
        <div className="func-modal-header" style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "4px", width: "100%", position: "relative", padding: "18px 22px" }}>
          <h4 className="func-modal-title" style={{ margin: 0, fontSize: "17px", fontWeight: "700", color: "#1e293b" }}>
            {functionName}
          </h4>
          {docData && docData.found && (docData.excel_source || docData.excel_path) && (
            <div className="func-modal-subtitle" style={{ fontSize: "12px", color: "#64748b", fontWeight: "500" }}>
              {docData.excel_source}{docData.excel_path ? ` / ${docData.excel_path}` : ""}
            </div>
          )}
          <button className="func-modal-close" style={{ position: "absolute", right: "22px", top: "18px" }} onClick={onClose} aria-label="Fermer">✕</button>
        </div>
        <div className="func-modal-body" style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: "16px" }}>
          {loading && <p className="func-modal-loading">🔄 Recherche dans la documentation…</p>}
          {error && <p className="func-modal-error">⚠️ {error}</p>}

          {/* Cas : fonction introuvable */}
          {!loading && !error && docData && !docData.found && (
            <div className="func-modal-not-found" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px", textAlign: "center", padding: "20px 0" }}>
              <span className="func-modal-not-found-icon" style={{ fontSize: "32px" }}>📪</span>
              <p style={{ margin: 0, fontSize: "14px", color: "#475569", fontWeight: "500", lineHeight: "1.5" }}>
                {docData.message || "Cette fonction n'est pas documentée dans Spec_PowerCARD.xlsx. Aucune information sur ses conditions d'échec n'est disponible."}
              </p>
            </div>
          )}

          {/* Cas : fonction documentée */}
          {!loading && !error && docData && docData.found && (
            <>
              {/* Section Description */}
              <div className="func-desc-section" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <h5 style={{ margin: 0, fontSize: "12px", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.5px", color: "#64748b" }}>
                  Description
                </h5>
                <p style={{ margin: 0, fontSize: "13.5px", color: "#334155", lineHeight: "1.55" }}>
                  {docData.excel_description || "Aucune description disponible dans la spécification."}
                </p>
              </div>

              {/* Section Conditions d'échec mise en évidence (fond orange/rouge clair avec icône d'alerte) */}
              <div className="func-exception-box" style={{
                border: "2px solid #f97316",
                borderRadius: "10px",
                background: "linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%)",
                boxShadow: "0 4px 14px rgba(249, 115, 22, 0.12)",
                overflow: "hidden",
                margin: "8px 0 4px 0",
                animation: "exception-pulse 0.35s ease"
              }}>
                <div className="func-exception-header" style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "10px 14px",
                  background: "rgba(249, 115, 22, 0.08)",
                  borderBottom: "1px solid rgba(249, 115, 22, 0.15)"
                }}>
                  <span className="func-exception-icon" style={{ fontSize: "16px" }}>⚠️</span>
                  <span className="func-exception-title" style={{ fontSize: "12px", fontWeight: "800", color: "#c2410c", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Conditions d'échec
                  </span>
                  <span className="func-exception-badge" style={{
                    marginLeft: "auto",
                    fontSize: "10px",
                    fontWeight: "700",
                    color: "#c2410c",
                    background: "rgba(249, 115, 22, 0.12)",
                    border: "1px solid rgba(249, 115, 22, 0.25)",
                    borderRadius: "20px",
                    padding: "2px 8px"
                  }}>
                    Spec_PowerCARD.xlsx — Exception
                  </span>
                </div>
                <p className="func-exception-text" style={{
                  margin: 0,
                  padding: "12px 14px",
                  fontSize: "14px",
                  fontWeight: "600",
                  color: "#9a3412",
                  lineHeight: "1.6",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word"
                }}>
                  {docData.excel_exception || "Aucune condition d'échec documentée pour cette fonction."}
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Étape de chronologie avec détection de fonction en échec ────────────────
function ChronologyStep({ step, failedFunctions, sessionId }) {
  const [showDoc, setShowDoc] = useState(false);
  const [matchedFunc, setMatchedFunc] = useState(null);

  // Détecte si cette étape mentionne une fonction en échec
  useEffect(() => {
    if (!failedFunctions || failedFunctions.length === 0) return;
    for (const fn of failedFunctions) {
      if (step && step.includes(fn)) {
        setMatchedFunc(fn);
        return;
      }
    }
    setMatchedFunc(null);
  }, [step, failedFunctions]);

  return (
    <li className="chronology-step">
      <span className="chronology-text">{step}</span>
      {matchedFunc && (
        <>
          <button
            className="chrono-help-btn"
            title={`Documentation de ${matchedFunc}`}
            onClick={() => setShowDoc(true)}
            aria-label={`Voir la documentation de ${matchedFunc}`}
          >
            ?
          </button>
          {showDoc && (
            <FunctionDocModal
              functionName={matchedFunc}
              sessionId={sessionId}
              onClose={() => setShowDoc(false)}
            />
          )}
        </>
      )}
    </li>
  );
}

// ─── Carte de transaction ────────────────────────────────────────────────────
function TransactionCard({ transaction, index, sessionId }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedDocFunc, setSelectedDocFunc] = useState(null);

  const isApproved =
    transaction.approval_status === "approved" ||
    (transaction.response_code_label &&
      transaction.response_code_label.toLowerCase().includes("approuv"));

  const alertCount = transaction.alerts?.length || 0;
  const failedFunctions = Array.isArray(transaction.failed_functions)
    ? transaction.failed_functions
    : [];

  // Titre principal : RRN (ou fallback STAN → index)
  const titleRRN = transaction.rrn
    ? `RRN : ${transaction.rrn}`
    : transaction.stan
    ? `STAN : ${transaction.stan}`
    : `Transaction #${index + 1}`;

  return (
    <div className={`transaction-card ${transaction.is_suspicious ? "tx-suspicious" : ""}`}>
      {/* ── Header ── */}
      <div className="tx-card-header">
        <div className="tx-header-left">
          {/* RRN en titre principal (pas de transaction_id) */}
          <span className="tx-rrn-title">{titleRRN}</span>

          <span className={`status-badge ${isApproved ? "badge-approved" : "badge-declined"}`}>
            {isApproved ? "Approuvée" : transaction.response_code_label || "Refusée"}
          </span>

          {alertCount > 0 && (
            <span className="alert-count-badge">
              {alertCount} alerte{alertCount > 1 ? "s" : ""} détectée{alertCount > 1 ? "s" : ""}
            </span>
          )}

          {transaction.is_suspicious && alertCount === 0 && (
            <span className="badge-suspicious-chip">Alerte Détectée</span>
          )}
        </div>

        {transaction.chronology && transaction.chronology.length > 0 && (
          <button
            className="toggle-chronology-btn"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded
              ? "Masquer la Chronologie ▲"
              : `Afficher Chronologie (${transaction.chronology.length} étapes) ▼`}
          </button>
        )}
      </div>

      {/* ── Identifiants ISO 8583 ── */}
      <div className="tx-identifiers-row">
        {transaction.pan_masked && (
          <div className="id-item">
            <span className="id-label">PAN :</span>
            <code className="id-code">{transaction.pan_masked}</code>
          </div>
        )}
        {transaction.stan && (
          <div className="id-item">
            <span className="id-label">STAN :</span>
            <code className="id-code">{transaction.stan}</code>
          </div>
        )}
        {transaction.rrn && (
          <div className="id-item">
            <span className="id-label">RRN :</span>
            <code className="id-code">{transaction.rrn}</code>
          </div>
        )}
        {transaction.processing_code && (
          <div className="id-item">
            <span className="id-label">Processing Code :</span>
            <code className="id-code id-processing-code">{transaction.processing_code}</code>
          </div>
        )}
        {transaction.response_code && (
          <div className="id-item">
            <span className="id-label">Code Rép. :</span>
            <code className="id-code">{transaction.response_code}</code>
          </div>
        )}
      </div>

      {/* ── Fonctions en échec (section dédiée avec bouton ? pour documentation) ── */}
      {failedFunctions.length > 0 && (
        <div className="tx-failed-functions-row">
          <span className="tx-section-label">Fonctions en échec :</span>
          <div className="failed-funcs-chips">
            {failedFunctions.map((fn, fIdx) => (
              <span key={fIdx} className="failed-func-chip" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                <span>✕ {fn}</span>
                <button
                  className="chrono-help-btn"
                  style={{ width: "18px", height: "18px", fontSize: "10px", padding: 0 }}
                  title={`Documentation de ${fn}`}
                  onClick={() => setSelectedDocFunc(fn)}
                  aria-label={`Voir la documentation de ${fn}`}
                >
                  ?
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Alertes ── */}
      {alertCount > 0 && (
        <div className="tx-alerts-row">
          <span className="tx-alerts-title">Alertes :</span>
          <div className="alerts-chips-container">
            {transaction.alerts.map((alert, aIdx) => (
              <span key={aIdx} className="alert-chip">
                {alert}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Pistes diagnostiques ── */}
      {transaction.pistes_diagnostiques && (
        <div className="tx-diagnostic-row">
          <span className="tx-section-label">Diagnostic :</span>
          <span className="tx-diagnostic-text">{transaction.pistes_diagnostiques}</span>
        </div>
      )}

      {/* ── Chronologie dépliable ── */}
      {expanded && transaction.chronology && (
        <div className="chronology-accordion">
          <h5 className="chronology-title">Chronologie d'Exécution :</h5>
          <ol className="chronology-list">
            {transaction.chronology.map((step, sIdx) => (
              <ChronologyStep
                key={sIdx}
                step={step}
                failedFunctions={failedFunctions}
                sessionId={sessionId}
              />
            ))}
          </ol>
        </div>
      )}

      {/* Modale de documentation pour la puce de fonction sélectionnée */}
      {selectedDocFunc && (
        <FunctionDocModal
          functionName={selectedDocFunc}
          sessionId={sessionId}
          onClose={() => setSelectedDocFunc(null)}
        />
      )}
    </div>
  );
}

// ─── Composant principal du rapport ─────────────────────────────────────────
export default function StructuredReport({ report, sessionId }) {
  // Fallback : texte brut ou raw_fallback
  if (typeof report === "string") {
    return (
      <div className="markdown-render">
        <Markdown>{report}</Markdown>
      </div>
    );
  }
  if (report && report.raw_fallback) {
    return (
      <div className="markdown-render">
        <Markdown>{report.raw_fallback}</Markdown>
      </div>
    );
  }

  const { summary = {}, transactions = [], field_analysis = [] } = report || {};

  return (
    <div className="structured-report">
      {/* 1. STATS GLOBALES */}
      <div className="summary-stats-grid">
        <div className="stat-card">
          <span className="stat-label">Total Transactions</span>
          <span className="stat-value stat-total">
            {summary.total_transactions ?? transactions.length}
          </span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Alertes / Suspectes</span>
          <span
            className={`stat-value ${
              (summary.suspicious_count ?? 0) > 0 ? "stat-danger" : "stat-neutral"
            }`}
          >
            {summary.suspicious_count ?? 0}
          </span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Approuvées</span>
          <span className="stat-value stat-success">{summary.approved_count ?? 0}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Déclinées</span>
          <span className="stat-value stat-danger">{summary.declined_count ?? 0}</span>
        </div>
      </div>

      {/* 2. TRANSACTIONS */}
      {transactions.length > 0 && (
        <div className="report-section">
          <h4 className="section-subtitle">
            Transactions Analysées ({transactions.length})
          </h4>
          <div className="transactions-list">
            {transactions.map((tx, idx) => (
              <TransactionCard
                key={tx.rrn || tx.transaction_id || idx}
                transaction={tx}
                index={idx}
                sessionId={sessionId}
              />
            ))}
          </div>
        </div>
      )}

      {/* 3. ANALYSE DE CONFORMITÉ DES CHAMPS (Part D) */}
      {(() => {
        const noViolations = report?.no_field_violations || !field_analysis || field_analysis.length === 0;
        return (
          <div className="report-section">
            <h4 className="section-subtitle">Analyse de Conformité des Champs</h4>
            {noViolations ? (
              <div className="field-no-violations">
                <span className="field-no-violations-icon">✅</span>
                <span>Aucune non-conformité de format détectée pour cette analyse.</span>
              </div>
            ) : (
              <div className="field-analysis-table-wrapper">
                <table className="field-analysis-table">
                  <thead>
                    <tr>
                      <th>Champ ISO</th>
                      <th>Type Attendu (source)</th>
                      <th>Valeur Observée</th>
                      <th>Nature de la Non-Conformité</th>
                    </tr>
                  </thead>
                  <tbody>
                    {field_analysis.map((field, idx) => (
                      <tr key={idx} className="row-warning">
                        <td className="field-id-cell">
                          <span className="field-badge">{field.field_number}</span>
                          <div className="field-name">{field.field_name}</div>
                        </td>
                        <td>
                          <span className="spec-type-label">{field.expected_type}</span>
                          {field.source && (
                            <div className="spec-source-sub">{field.source}</div>
                          )}
                        </td>
                        <td>
                          <code className="obs-value obs-value-danger">
                            {field.observed_value ?? field.value ?? "(vide)"}
                          </code>
                        </td>
                        <td>
                          <span className="non-conformity-tag">
                            {field.non_conformity_type || field.message || "Non-conformité détectée"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
