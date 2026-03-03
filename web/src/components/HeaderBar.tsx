import React from "react";

type Props = {
  view: "chart" | "portfolio";
  onView: (view: "chart" | "portfolio") => void;
};

export default function HeaderBar({ view, onView }: Props) {
  return (
    <div style={{ padding: "10px 14px", borderBottom: "1px solid #22262f", background: "#131722", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <strong>SEM Automated Trading System</strong>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          onClick={() => onView("chart")}
          style={{
            padding: "4px 10px",
            borderRadius: 4,
            border: "1px solid #2d3340",
            background: view === "chart" ? "#2d3340" : "transparent",
            color: "inherit",
            cursor: "pointer",
          }}
        >
          Chart
        </button>
        <button
          type="button"
          onClick={() => onView("portfolio")}
          style={{
            padding: "4px 10px",
            borderRadius: 4,
            border: "1px solid #2d3340",
            background: view === "portfolio" ? "#2d3340" : "transparent",
            color: "inherit",
            cursor: "pointer",
          }}
        >
          Portfolio
        </button>
      </div>
    </div>
  );
}
