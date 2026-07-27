import React, { useState } from "react";
import Markdown from "react-markdown";

export default function StructuredReport({ report }) {
  // If report is raw string or contains raw_fallback, fallback to markdown render
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
      {/* 1. SUMMARY STATS BAR */}
      <div className="summary-stats-grid">
        <div className="stat-card">
          <span className="stat-label">Total Transactions</span>
          <span className="stat-value stat-total">{summary.total_transactions ?? transactions.length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Alertes / Suspectes</span>
          <span className={`stat-value ${summary.suspicious_count > 0 ? "stat-danger" : "stat-neutral"}`}>
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

      {/* 2. TRANSACTIONS CARDS */}
      {transactions.length > 0 && (
        <div className="report-section">
          <h4 className="section-subtitle">Transactions Analysées ({transactions.length})</h4>
          <div className="transactions-list">
            {transactions.map((tx, idx) => (
              <TransactionCard key={tx.transaction_id || idx} transaction={tx} index={idx} />
            ))}
          </div>
        </div>
      )}

      {/* 3. FIELD ANALYSIS TABLE / CARDS */}
      {field_analysis && field_analysis.length > 0 && (
        <div className="report-section">
          <h4 className="section-subtitle">Analyse de Conformité des Champs</h4>
          <div className="field-analysis-table-wrapper">
            <table className="field-analysis-table">
              <thead>
                <tr>
                  <th>Champ ISO</th>
                  <th>Spécification & Règles</th>
                  <th>Valeurs Observées</th>
                  <th>Diagnostic & Conformité</th>
                </tr>
              </thead>
              <tbody>
                {field_analysis.map((field, idx) => {
                  const isNonCompliant = field.compliance_note && (
                    field.compliance_note.toLowerCase().includes("absent") ||
                    field.compliance_note.toLowerCase().includes("non-conforme") ||
                    field.compliance_note.toLowerCase().includes("erreur") ||
                    field.compliance_note.toLowerCase().includes("anomalie")
                  );

                  return (
                    <tr key={idx} className={isNonCompliant ? "row-warning" : "row-compliant"}>
                      <td className="field-id-cell">
                        <span className="field-badge">{field.field_number}</span>
                        <div className="field-name">{field.field_name}</div>
                      </td>
                      <td>
                        <p className="spec-desc">{field.spec_description}</p>
                        {field.spec_rules && field.spec_rules.length > 0 && (
                          <ul className="spec-rules-list">
                            {field.spec_rules.map((rule, rIdx) => (
                              <li key={rIdx}>{rule}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td>
                        {field.observed_examples && field.observed_examples.length > 0 ? (
                          field.observed_examples.map((ex, exIdx) => (
                            <div key={exIdx} className="observed-item">
                              <div className="obs-meta">
                                <span className="obs-tx-ids">
                                  {Array.isArray(ex.transaction_ids) ? ex.transaction_ids.join(", ") : ex.transaction_ids}
                                </span>
                                {ex.declared_length && (
                                  <span className="obs-length">Lg: {ex.declared_length}</span>
                                )}
                              </div>
                              <code className="obs-value">{ex.value || "(Vide)"}</code>
                              {ex.note && <div className="obs-note">{ex.note}</div>}
                            </div>
                          ))
                        ) : (
                          <span className="empty-val">Aucun exemple</span>
                        )}
                      </td>
                      <td>
                        <span className={`compliance-tag ${isNonCompliant ? "tag-warning" : "tag-compliant"}`}>
                          {field.compliance_note || "Conforme"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function TransactionCard({ transaction, index }) {
  const [expanded, setExpanded] = useState(false);

  const isApproved = transaction.approval_status === "approved" || 
    (transaction.response_code_label && transaction.response_code_label.toLowerCase().includes("approuv"));

  return (
    <div className={`transaction-card ${transaction.is_suspicious ? "tx-suspicious" : ""}`}>
      <div className="tx-card-header">
        <div className="tx-header-left">
          <span className="tx-id">{transaction.transaction_id || `Tx #${index + 1}`}</span>
          
          <span className={`status-badge ${isApproved ? "badge-approved" : "badge-declined"}`}>
            {isApproved ? "Approuvée" : (transaction.response_code_label || "Refusée")}
          </span>

          {transaction.is_suspicious && (
            <span className="badge-suspicious-chip">
              Alerte Détectée
            </span>
          )}
        </div>

        {transaction.chronology && transaction.chronology.length > 0 && (
          <button 
            className="toggle-chronology-btn"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Masquer la Chronologie ▲" : `Afficher Chronologie (${transaction.chronology.length} étapes) ▼`}
          </button>
        )}
      </div>

      {/* Identificateurs Monétiques */}
      <div className="tx-identifiers-row">
        {transaction.pan_masked && (
          <div className="id-item">
            <span className="id-label">PAN:</span>
            <code className="id-code">{transaction.pan_masked}</code>
          </div>
        )}
        {transaction.stan && (
          <div className="id-item">
            <span className="id-label">STAN:</span>
            <code className="id-code">{transaction.stan}</code>
          </div>
        )}
        {transaction.rrn && (
          <div className="id-item">
            <span className="id-label">RRN:</span>
            <code className="id-code">{transaction.rrn}</code>
          </div>
        )}
        {transaction.response_code && (
          <div className="id-item">
            <span className="id-label">Code Rep:</span>
            <code className="id-code">{transaction.response_code}</code>
          </div>
        )}
      </div>

      {/* Alertes / Non-conformités */}
      {transaction.alerts && transaction.alerts.length > 0 && (
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

      {/* Chronologie Dépliable */}
      {expanded && transaction.chronology && (
        <div className="chronology-accordion">
          <h5 className="chronology-title">Chronologie d'Exécution :</h5>
          <ol className="chronology-list">
            {transaction.chronology.map((step, sIdx) => (
              <li key={sIdx} className="chronology-step">
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
