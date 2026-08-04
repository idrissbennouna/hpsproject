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
      .catch(() => setError("Impossible de charger la documentation."))
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

  const LLM_SECTIONS = [
    { key: "description",     icon: "📖", label: "Description" },
    { key: "call_context",    icon: "🔄", label: "Contexte d'appel" },
    { key: "failure_meaning", icon: "⚠️", label: "Signification de l'échec" },
    { key: "diagnostic_hint", icon: "🔍", label: "Que vérifier en premier" },
  ];

  return (
    <div className="func-modal-backdrop" onClick={handleBackdropClick} role="dialog" aria-modal="true">
      <div className="func-modal" ref={modalRef}>
        <div className="func-modal-header">
          <h4 className="func-modal-title">
            Documentation — <code>{functionName}</code>
          </h4>
          <button className="func-modal-close" onClick={onClose} aria-label="Fermer">✕</button>
        </div>
        <div className="func-modal-body">
          {loading && <p className="func-modal-loading">🔄 Recherche dans la documentation…</p>}
          {error && <p className="func-modal-error">{error}</p>}

          {/* Cas : fonction introuvable */}
          {!loading && docData && !docData.found && (
            <div className="func-modal-not-found">
              <span className="func-modal-not-found-icon">📪</span>
              <p>Documentation non disponible pour <code>{functionName}</code>.</p>
              <p className="func-modal-not-found-hint">Cette fonction n'est pas répertoriée dans les sources disponibles.</p>
            </div>
          )}

          {/* Cas : 4 sections LLM structurées */}
          {!loading && docData && docData.found && docData.llm_structured && (
            <div className="func-modal-llm-sections">
              {LLM_SECTIONS.map(({ key, icon, label }) => (
                <div key={key} className="func-llm-card">
                  <div className="func-llm-card-header">
                    <span className="func-llm-icon">{icon}</span>
                    <span className="func-llm-label">{label}</span>
                  </div>
                  <p className="func-llm-content">{docData.llm_structured[key] || "Information non disponible."}</p>
                </div>
              ))}
              {docData.raw_sources_count > 0 && (
                <p className="func-modal-sources-note">📚 Sources consultées : {docData.raw_sources_count} extrait(s)</p>
              )}
            </div>
          )}

          {/* Fallback gracieux : ancien format sans llm_structured */}
          {!loading && docData && docData.found && !docData.llm_structured && (
            <div className="func-modal-docs">
              {(docData.documentation || []).map((section, idx) => (
                <div key={idx} className="func-doc-section">
                  <div className="func-doc-source-badge">{section.source}</div>
                  <pre className="func-doc-content">{section.content}</pre>
                </div>
              ))}
            </div>
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

      {/* ── Fonctions en échec (section dédiée) ── */}
      {failedFunctions.length > 0 && (
        <div className="tx-failed-functions-row">
          <span className="tx-section-label">Fonctions en échec :</span>
          <div className="failed-funcs-chips">
            {failedFunctions.map((fn, fIdx) => (
              <span key={fIdx} className="failed-func-chip">
                ✕ {fn}
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
