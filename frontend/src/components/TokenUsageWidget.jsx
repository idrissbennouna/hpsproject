import React from "react";

function TokenUsageWidget({ usage }) {
  if (!usage) return null;

  const { used, budget, remaining, percentage } = usage;

  // Determine progress bar color based on percentage:
  // - Green: < 70%
  // - Orange: 70% - 95%
  // - Red: > 95%
  let barColor = "#059669"; // Emerald (green)
  if (percentage >= 70 && percentage <= 95) {
    barColor = "#d97706"; // Amber (orange)
  } else if (percentage > 95) {
    barColor = "#dc2626"; // Red
  }

  // Format numbers nicely with spaces
  const formatNum = (num) => {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  };

  return (
    <div className="token-usage-widget" style={{
      marginTop: "auto",
      padding: "16px 14px",
      borderRadius: "12px",
      background: "rgba(248, 250, 252, 0.6)",
      border: "1px solid rgba(0, 0, 0, 0.05)",
      fontSize: "12px",
      display: "flex",
      flexDirection: "column",
      gap: "8px",
      boxShadow: "0 2px 6px rgba(0, 0, 0, 0.02)"
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontWeight: "700", color: "#334155" }}>
        <span>Consommation LLM</span>
        <span style={{ color: barColor }}>{percentage}%</span>
      </div>

      {/* Progress Bar Container */}
      <div style={{
        height: "8px",
        width: "100%",
        backgroundColor: "#e2e8f0",
        borderRadius: "4px",
        overflow: "hidden"
      }}>
        <div style={{
          height: "100%",
          width: `${Math.min(100, percentage)}%`,
          backgroundColor: barColor,
          borderRadius: "4px",
          transition: "width 0.5s ease-in-out"
        }} />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "2px", color: "#64748b", fontSize: "11px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Utilisés :</span>
          <span style={{ fontWeight: "600", color: "#334155" }}>{formatNum(used)} / {formatNum(budget)}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Restants :</span>
          <span style={{ fontWeight: "600", color: remaining === 0 ? "#dc2626" : "#334155" }}>
            {formatNum(remaining)}
          </span>
        </div>
      </div>
      
      <p style={{
        margin: "4px 0 0 0",
        fontSize: "9px",
        color: "#94a3b8",
        lineHeight: "1.3",
        textAlign: "center",
        fontStyle: "italic"
      }}>
      </p>
    </div>
  );
}

export default TokenUsageWidget;
