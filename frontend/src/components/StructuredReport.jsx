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
        <div className="func-modal-body" style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: "16px", minHeight: 0, overflowY: "auto" }}>
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
                overflow: "visible",
                margin: "8px 0 4px 0",
                animation: "exception-pulse 0.35s ease",
                flexShrink: 0
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

// ─── Modale documentation erreur HSM (PUGD0537 / RAG / placeholder) ─────────
function extractHsmCodeFromText(text) {
  const s = String(text || "");
  const lower = s.toLowerCase();
  const looksHsm =
    /hsm|hsmresult|from hsm|to hsm|erreur hsm/.test(lower) ||
    /\b[A-Z]{2}\d{2}\b/.test(s);
  if (!looksHsm) return null;

  const patterns = [
    /Code d'erreur HSM\s+([A-Za-z0-9]+)/i,
    /HsmResultCode\s*[:=]?\s*\[?([A-Za-z0-9]+)/i,
    /Erreur HSM[^\n]*?\b([A-Za-z]{2}\d{2}|\d{2,3}|[A-Za-z]{2})\b/i,
    /\b([A-Z]{2}\d{2})\b/,
    /\bED\s*[_\-]?\s*(\d{2})\b/i,
  ];
  for (const re of patterns) {
    const m = s.match(re);
    if (m?.[1]) {
      const tok = String(m[1]).toUpperCase().replace(/[_\-\s]/g, "");
      if (/^\d{2}$/.test(tok) && /ed/i.test(s)) return `ED${tok}`;
      return tok;
    }
  }
  return null;
}

function HsmDocModal({ code, sessionId, onClose }) {
  const [loading, setLoading] = useState(true);
  const [docData, setDocData] = useState(null);
  const [error, setError] = useState("");
  const modalRef = useRef(null);

  useEffect(() => {
    const url = sessionId
      ? `http://127.0.0.1:8000/api/v1/hsm/${encodeURIComponent(code)}/doc?session_id=${encodeURIComponent(sessionId)}`
      : `http://127.0.0.1:8000/api/v1/hsm/${encodeURIComponent(code)}/doc`;

    axios
      .get(url)
      .then((res) => setDocData(res.data))
      .catch((err) => {
        const detail = err.response?.data?.detail || "Impossible de charger la documentation HSM.";
        setError(detail);
      })
      .finally(() => setLoading(false));
  }, [code, sessionId]);

  useEffect(() => {
    const handleKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const handleBackdropClick = (e) => {
    if (modalRef.current && !modalRef.current.contains(e.target)) onClose();
  };

  const title = docData?.display || code;
  const subtitleParts = [
    docData?.command_code && `Commande ${docData.command_code}`,
    docData?.response_code && `Réponse ${docData.response_code}`,
    docData?.error_number && `Erreur ${docData.error_number}`,
  ].filter(Boolean);

  return (
    <div className="func-modal-backdrop" onClick={handleBackdropClick} role="dialog" aria-modal="true">
      <div className="func-modal" ref={modalRef}>
        <div className="func-modal-header" style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "4px", width: "100%", position: "relative", padding: "18px 22px" }}>
          <h4 className="func-modal-title" style={{ margin: 0, fontSize: "17px", fontWeight: "700", color: "#1e293b" }}>
            Erreur HSM — {title}
          </h4>
          <div className="func-modal-subtitle" style={{ fontSize: "12px", color: "#64748b", fontWeight: "500" }}>
            {subtitleParts.length > 0 ? subtitleParts.join(" · ") : "payShield Core Host Commands"}
            {" · "}
            {docData?.doc_title || "PUGD0537-004 Core Host Commands V1"}
          </div>
          <button className="func-modal-close" style={{ position: "absolute", right: "22px", top: "18px" }} onClick={onClose} aria-label="Fermer">✕</button>
        </div>
        <div className="func-modal-body" style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: "16px", minHeight: 0, overflowY: "auto" }}>
          {loading && <p className="func-modal-loading">Recherche dans PUGD0537 / référentiel HSM…</p>}
          {error && <p className="func-modal-error">⚠️ {error}</p>}

          {!loading && !error && docData && !docData.found && (
            <div className="func-modal-not-found" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px", textAlign: "center", padding: "20px 0" }}>
              <span className="func-modal-not-found-icon" style={{ fontSize: "32px" }}>📪</span>
              <p style={{ margin: 0, fontSize: "14px", color: "#475569", fontWeight: "500", lineHeight: "1.5" }}>
                {docData.message || "Aucune documentation HSM disponible pour ce code."}
              </p>
            </div>
          )}

          {!loading && !error && docData && docData.found && (
            <>
              {docData.placeholder && (
                <div className="func-desc-section" style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <h5 style={{ margin: 0, fontSize: "12px", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.5px", color: "#64748b" }}>
                    {docData.placeholder.title || "Synthèse"}
                  </h5>
                  {docData.placeholder.description && (
                    <p style={{ margin: 0, fontSize: "13.5px", color: "#334155", lineHeight: "1.55" }}>
                      {docData.placeholder.description}
                    </p>
                  )}
                  {docData.placeholder.meaning && (
                    <div className="func-exception-box" style={{
                      border: "2px solid #f97316",
                      borderRadius: "10px",
                      background: "linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%)",
                      padding: "12px 14px",
                    }}>
                      <div style={{ fontSize: "11px", fontWeight: "800", color: "#c2410c", textTransform: "uppercase", marginBottom: "6px" }}>
                        Signification
                      </div>
                      <p style={{ margin: 0, fontSize: "13.5px", color: "#9a3412", fontWeight: "600", lineHeight: "1.55", whiteSpace: "pre-wrap" }}>
                        {docData.placeholder.meaning}
                      </p>
                    </div>
                  )}
                  {docData.placeholder.diagnostic_hint && (
                    <p style={{ margin: 0, fontSize: "13px", color: "#475569", lineHeight: "1.5" }}>
                      <strong>Piste :</strong> {docData.placeholder.diagnostic_hint}
                    </p>
                  )}
                </div>
              )}

              {Array.isArray(docData.excerpts) && docData.excerpts.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  <h5 style={{ margin: 0, fontSize: "12px", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.5px", color: "#64748b" }}>
                    Extraits — {docData.doc_title || "PUGD0537"}
                  </h5>
                  {docData.excerpts.map((ex, idx) => (
                    <div key={idx} style={{
                      border: "1px solid #e2e8f0",
                      borderRadius: "8px",
                      background: "#f8fafc",
                      padding: "12px 14px",
                    }}>
                      <div style={{ fontSize: "11px", fontWeight: "700", color: "#1e3a8a", marginBottom: "8px" }}>
                        {ex.source || "Source HSM"}
                        {ex.origin ? ` · ${ex.origin}` : ""}
                      </div>
                      <pre style={{
                        margin: 0,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        fontSize: "12.5px",
                        lineHeight: "1.55",
                        color: "#334155",
                        fontFamily: "Consolas, Cascadia Code, monospace",
                      }}>
                        {ex.content}
                      </pre>
                    </div>
                  ))}
                </div>
              )}

              {Array.isArray(docData.sources) && docData.sources.length > 0 && (
                <div style={{ fontSize: "11px", color: "#94a3b8" }}>
                  Sources : {docData.sources.join(" · ")}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
function isErrorLikeStep(step) {
  const s = String(step || "").toLowerCase();
  return /\b(nok|échec|echec|error|failed|échecée|refuse)\b|-\s*[1-9]\d*|r[ée]sultat\s*-/.test(s);
}

function extractFunctionNameFromStep(step) {
  const text = String(step || "");
  const patterns = [
    /\b([A-Za-z][A-Za-z0-9_]{2,})\s*\(\s*\)/, // GetOriginalAuthData() / gen_iss_script_data()
    /fonction\s+[`'"]?([A-Za-z][A-Za-z0-9_]+)/i,
    /ex[ée]cution de\s+([A-Za-z][A-Za-z0-9_]+)/i,
    /appel(?:\s+de)?\s+([A-Za-z][A-Za-z0-9_]+)/i,
    /\b([A-Za-z][A-Za-z0-9_]{2,})\s*:\s*r[ée]sultat/i,
  ];
  for (const re of patterns) {
    const m = text.match(re);
    if (m?.[1]) return m[1];
  }
  return null;
}

/** Fusionne failed_functions du rapport + fonctions en échec déduites de la chronologie. */
function mergeFailedFunctionsFromChronology(baseFailed, chronologySteps) {
  const merged = [];
  const seen = new Set();
  const push = (fn) => {
    const name = String(fn || "").trim();
    if (!name) return;
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    merged.push(name);
  };
  (baseFailed || []).forEach(push);
  (chronologySteps || []).forEach((step) => {
    if (!isErrorLikeStep(step)) return;
    push(extractFunctionNameFromStep(step));
  });
  return merged;
}

function detectFailedFuncInStep(step, failedFunctions) {
  if (!step) return null;
  const stepLower = String(step).toLowerCase();

  // Uniquement les fonctions de failed_functions (aligné avec les alertes)
  if (failedFunctions?.length) {
    for (const fn of failedFunctions) {
      if (fn && stepLower.includes(String(fn).toLowerCase())) return fn;
    }
  }
  return null;
}

function extractDocFuncFromStep(step, failedFunctions) {
  // Pour le bouton "?" : d'abord failed_functions, sinon extraction sur étape d'échec
  const fromList = detectFailedFuncInStep(step, failedFunctions);
  if (fromList) return fromList;
  if (isErrorLikeStep(step)) return extractFunctionNameFromStep(step);
  return null;
}

function getChronologyStepStatus(step, matchedFailedFunc) {
  // Statut "Échec" = fonction présente dans failed_functions (même source que les alertes)
  if (matchedFailedFunc) return "error";
  const s = String(step || "").toLowerCase();
  if (/\b(ok|succès|succes|approved|approuv|réussi|reussi)\b/.test(s)) return "success";
  return "neutral";
}

function renderChronologyStepText(step, matchedFunc) {
  const text = String(step || "").replace(/^[-•]\s*/, "");
  if (!matchedFunc) return text;
  const idx = text.toLowerCase().indexOf(String(matchedFunc).toLowerCase());
  if (idx < 0) return text;
  const before = text.slice(0, idx);
  const match = text.slice(idx, idx + matchedFunc.length);
  const after = text.slice(idx + matchedFunc.length);
  return (
    <>
      {before}
      <mark className="chrono-func-highlight">{match}</mark>
      {after}
    </>
  );
}

// ─── Étape de chronologie avec détection de fonction en échec / HSM ──────────
function ChronologyStep({ step, index, total, failedFunctions, sessionId }) {
  const [showDoc, setShowDoc] = useState(false);
  const [showHsmDoc, setShowHsmDoc] = useState(false);
  const matchedFailedFunc = detectFailedFuncInStep(step, failedFunctions);
  const docFunc = extractDocFuncFromStep(step, failedFunctions);
  const hsmCode = !docFunc ? extractHsmCodeFromText(step) : null;
  const displayStatus = matchedFailedFunc
    ? "error"
    : (hsmCode && /hsm|erreur|nok|resultcode|-\d/i.test(String(step))
        ? "error"
        : getChronologyStepStatus(step, null));
  const isLast = index === total - 1;

  return (
    <li className={`chronology-step chrono-status-${displayStatus}${(docFunc || hsmCode) ? " chrono-has-help" : ""}`}>
      <div className="chrono-rail" aria-hidden="true">
        <span className={`chrono-node chrono-node-${displayStatus}`}>
          {displayStatus === "error" ? "!" : displayStatus === "success" ? "✓" : index + 1}
        </span>
        {!isLast && <span className="chrono-connector" />}
      </div>
      <div className="chrono-step-body">
        <div className="chrono-step-meta">
          <span className="chrono-step-index">Étape {index + 1}</span>
          {displayStatus === "error" && <span className="chrono-status-pill chrono-pill-error">Échec</span>}
          {displayStatus === "success" && <span className="chrono-status-pill chrono-pill-success">OK</span>}
          {hsmCode && <span className="chrono-status-pill" style={{ background: "#eff6ff", color: "#1e40af", border: "1px solid #bfdbfe" }}>HSM</span>}
        </div>
        <div className="chrono-step-content">
          <p className="chronology-text">{renderChronologyStepText(step, docFunc)}</p>
          {docFunc && (
            <button
              className="chrono-help-btn"
              title={`Documentation de ${docFunc}`}
              onClick={() => setShowDoc(true)}
              aria-label={`Voir la documentation de ${docFunc}`}
            >
              ?
            </button>
          )}
          {!docFunc && hsmCode && (
            <button
              className="chrono-help-btn"
              title={`Documentation HSM ${hsmCode}`}
              onClick={() => setShowHsmDoc(true)}
              aria-label={`Voir la documentation HSM ${hsmCode}`}
            >
              ?
            </button>
          )}
        </div>
      </div>
      {showDoc && docFunc && (
        <FunctionDocModal
          functionName={docFunc}
          sessionId={sessionId}
          onClose={() => setShowDoc(false)}
        />
      )}
      {showHsmDoc && hsmCode && (
        <HsmDocModal
          code={hsmCode}
          sessionId={sessionId}
          onClose={() => setShowHsmDoc(false)}
        />
      )}
    </li>
  );
}

// ─── Carte de transaction ────────────────────────────────────────────────────
function TransactionCard({ transaction, index, sessionId }) {
  const [expanded, setExpanded] = useState(false);
  const [selectedDocFunc, setSelectedDocFunc] = useState(null);
  const [selectedHsmCode, setSelectedHsmCode] = useState(null);

  const isApproved =
    transaction.approval_status === "approved" ||
    (transaction.response_code_label &&
      transaction.response_code_label.toLowerCase().includes("approuv"));

  const chronologySteps = Array.isArray(transaction.chronology)
    ? transaction.chronology.filter((s) => String(s || "").trim())
    : String(transaction.chronology || "")
        .split("\n")
        .map((s) => s.replace(/^[-•]\s*/, "").trim())
        .filter(Boolean);

  // Inclut aussi les fonctions déduites de la chronologie (ex: GetOriginalAuthData() : résultat -1)
  const failedFunctions = mergeFailedFunctionsFromChronology(
    Array.isArray(transaction.failed_functions) ? transaction.failed_functions : [],
    chronologySteps
  );

  const alerts = Array.isArray(transaction.alerts) ? transaction.alerts : [];

  const alertCount = (() => {
    const fromAlerts = alerts.length;
    // Aligne le badge "X alerte(s)" sur failed_functions (source de vérité des échecs)
    return Math.max(fromAlerts, failedFunctions.length);
  })();

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

        {chronologySteps.length > 0 && (
          <button
            className={`toggle-chronology-btn${expanded ? " toggle-chrono-open" : ""}`}
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
          >
            <span className="toggle-chrono-icon" aria-hidden="true">{expanded ? "▾" : "▸"}</span>
            <span>
              {expanded
                ? "Masquer la chronologie"
                : `Chronologie d'exécution`}
            </span>
            <span className="toggle-chrono-count">{chronologySteps.length}</span>
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
            {alerts.map((alert, aIdx) => {
              const hsmCode = extractHsmCodeFromText(alert);
              return (
                <span key={aIdx} className="alert-chip" style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                  <span>{alert}</span>
                  {hsmCode && (
                    <button
                      className="chrono-help-btn"
                      style={{ width: "18px", height: "18px", fontSize: "10px", padding: 0 }}
                      title={`Documentation HSM ${hsmCode}`}
                      onClick={() => setSelectedHsmCode(hsmCode)}
                      aria-label={`Voir la documentation HSM ${hsmCode}`}
                    >
                      ?
                    </button>
                  )}
                </span>
              );
            })}
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
      {expanded && chronologySteps.length > 0 && (() => {
        // Compteur aligné sur failed_functions (= source des alertes), pas sur heuristique texte
        const errorCount = failedFunctions.length;
        return (
          <div className="chronology-accordion">
            <div className="chronology-header">
              <div className="chronology-header-left">
                <h5 className="chronology-title">Chronologie d'exécution</h5>
                <span className="chronology-subtitle">
                  Flux d'événements issu de la trace
                </span>
              </div>
              <div className="chronology-header-stats">
                <span className="chrono-stat-chip">
                  {chronologySteps.length} étape{chronologySteps.length > 1 ? "s" : ""}
                </span>
                {errorCount > 0 && (
                  <span className="chrono-stat-chip chrono-stat-error">
                    {errorCount} échec{errorCount > 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </div>
            <ol className="chronology-list">
              {chronologySteps.map((step, sIdx) => (
                <ChronologyStep
                  key={sIdx}
                  step={step}
                  index={sIdx}
                  total={chronologySteps.length}
                  failedFunctions={failedFunctions}
                  sessionId={sessionId}
                />
              ))}
            </ol>
          </div>
        );
      })()}

      {/* Modale de documentation pour la puce de fonction sélectionnée */}
      {selectedDocFunc && (
        <FunctionDocModal
          functionName={selectedDocFunc}
          sessionId={sessionId}
          onClose={() => setSelectedDocFunc(null)}
        />
      )}
      {selectedHsmCode && (
        <HsmDocModal
          code={selectedHsmCode}
          sessionId={sessionId}
          onClose={() => setSelectedHsmCode(null)}
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
