import React from "react";
import type { Gap } from "../api/types";

type Props = {
  lastTs?: string;
  gapCount: number;
  gaps: Gap[];
};

export default function DataHealthPanel({ lastTs, gapCount, gaps }: Props) {
  return (
    <div style={{ borderTop: "1px solid #22262f", padding: 10, fontSize: 12 }}>
      <strong>Data Health</strong>
      <div>Last update: {lastTs ? new Date(lastTs).toLocaleString() : "-"}</div>
      <div>Unresolved gaps: {gapCount}</div>
      {gaps.slice(0, 3).map((g) => (
        <div key={`${g.start_ts}-${g.end_ts}`} style={{ color: "#fca5a5" }}>
          {new Date(g.start_ts).toLocaleString()} → {new Date(g.end_ts).toLocaleString()}
        </div>
      ))}
    </div>
  );
}
