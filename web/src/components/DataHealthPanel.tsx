import React from "react";
import type { Gap } from "../api/types";
import { formatDateTimeWithZone, getClientTimeZone, getClientTimeZoneLabel } from "../utils/time";

type Props = {
  lastTs?: string;
  gapCount: number;
  gaps: Gap[];
};

export default function DataHealthPanel({ lastTs, gapCount, gaps }: Props) {
  const tz = getClientTimeZone();
  const tzLabel = getClientTimeZoneLabel();
  return (
    <div style={{ borderTop: "1px solid #22262f", padding: 10, fontSize: 12 }}>
      <strong>Data Health</strong>
      <div style={{ color: "#9ca3af" }}>Timezone: {tzLabel} ({tz})</div>
      <div>Last update: {formatDateTimeWithZone(lastTs)}</div>
      <div>Unresolved gaps: {gapCount}</div>
      {gaps.slice(0, 3).map((g) => (
        <div key={`${g.start_ts}-${g.end_ts}`} style={{ color: "#fca5a5" }}>
          {formatDateTimeWithZone(g.start_ts)} → {formatDateTimeWithZone(g.end_ts)}
        </div>
      ))}
    </div>
  );
}
