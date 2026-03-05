import React, { useMemo, useState } from "react";
import type { CatchupStatusRow } from "../api/types";

type Props = {
  rows: CatchupStatusRow[];
  error?: string | null;
  updatedAt?: Date | null;
};

function fmt(ts?: string | null): string {
  if (!ts) return "-";
  return new Date(ts).toLocaleString();
}

export default function IngestionStatusPage({ rows, error, updatedAt }: Props) {
  const [symbolFilter, setSymbolFilter] = useState("all");
  const [timeframeFilter, setTimeframeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<"all" | "caught_up" | "catching_up">("all");

  const uniqueSymbols = useMemo(() => ["all", ...Array.from(new Set(rows.map((row) => row.symbol))).sort()], [rows]);
  const uniqueTimeframes = useMemo(() => ["all", ...Array.from(new Set(rows.map((row) => row.timeframe))).sort()], [rows]);

  const filteredRows = useMemo(
    () => rows.filter((row) => {
      const passSymbol = symbolFilter === "all" || row.symbol === symbolFilter;
      const passTimeframe = timeframeFilter === "all" || row.timeframe === timeframeFilter;
      const passStatus = statusFilter === "all"
        || (statusFilter === "caught_up" && row.is_caught_up)
        || (statusFilter === "catching_up" && !row.is_caught_up);
      return passSymbol && passTimeframe && passStatus;
    }),
    [rows, symbolFilter, timeframeFilter, statusFilter]
  );

  const sorted = useMemo(
    () => [...filteredRows].sort((a, b) => {
      if (a.is_caught_up !== b.is_caught_up) return a.is_caught_up ? 1 : -1;
      if (a.remaining_after_attempt_bars !== b.remaining_after_attempt_bars) {
        return b.remaining_after_attempt_bars - a.remaining_after_attempt_bars;
      }
      if (a.symbol === b.symbol) return a.timeframe.localeCompare(b.timeframe);
      return a.symbol.localeCompare(b.symbol);
    }),
    [filteredRows]
  );

  const summary = useMemo(() => {
    const totalPairs = rows.length;
    const caughtUpPairs = rows.filter((row) => row.is_caught_up).length;
    const laggingPairs = totalPairs - caughtUpPairs;
    const totalBehindBars = rows.reduce((acc, row) => acc + row.bars_behind_before_jump, 0);
    const totalMissingGapWindows = rows.reduce((acc, row) => acc + row.unresolved_gap_count, 0);
    const totalMissingGapBars = rows.reduce((acc, row) => acc + row.unresolved_gap_bars_estimate, 0);
    return {
      totalPairs,
      caughtUpPairs,
      laggingPairs,
      totalBehindBars,
      totalMissingGapWindows,
      totalMissingGapBars,
    };
  }, [rows]);

  const progressColor = (pct: number) => {
    if (pct >= 99.9) return "#22c55e";
    if (pct >= 70) return "#facc15";
    return "#f97316";
  };

  return (
    <div style={{ padding: 12 }}>
      <div style={{ marginBottom: 10, fontSize: 12, color: "#b4bccf" }}>
        Last refresh: {updatedAt ? updatedAt.toLocaleTimeString() : "-"}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: 8, marginBottom: 10 }}>
        <div style={{ border: "1px solid #22262f", borderRadius: 6, padding: 8 }}><div style={{ fontSize: 11, color: "#9ba7bf" }}>Pairs</div><div style={{ fontSize: 16 }}>{summary.totalPairs}</div></div>
        <div style={{ border: "1px solid #22262f", borderRadius: 6, padding: 8 }}><div style={{ fontSize: 11, color: "#9ba7bf" }}>Caught Up</div><div style={{ fontSize: 16, color: "#86efac" }}>{summary.caughtUpPairs}</div></div>
        <div style={{ border: "1px solid #22262f", borderRadius: 6, padding: 8 }}><div style={{ fontSize: 11, color: "#9ba7bf" }}>Lagging</div><div style={{ fontSize: 16, color: "#facc15" }}>{summary.laggingPairs}</div></div>
        <div style={{ border: "1px solid #22262f", borderRadius: 6, padding: 8 }}><div style={{ fontSize: 11, color: "#9ba7bf" }}>Behind Bars</div><div style={{ fontSize: 16 }}>{summary.totalBehindBars}</div></div>
        <div style={{ border: "1px solid #22262f", borderRadius: 6, padding: 8 }}><div style={{ fontSize: 11, color: "#9ba7bf" }}>Missing Gaps</div><div style={{ fontSize: 16 }}>{summary.totalMissingGapWindows}</div></div>
        <div style={{ border: "1px solid #22262f", borderRadius: 6, padding: 8 }}><div style={{ fontSize: 11, color: "#9ba7bf" }}>Missing Gap Bars (est)</div><div style={{ fontSize: 16 }}>{summary.totalMissingGapBars}</div></div>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10, fontSize: 12 }}>
        <label>
          Symbol:{" "}
          <select value={symbolFilter} onChange={(event) => setSymbolFilter(event.target.value)}>
            {uniqueSymbols.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Timeframe:{" "}
          <select value={timeframeFilter} onChange={(event) => setTimeframeFilter(event.target.value)}>
            {uniqueTimeframes.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Status:{" "}
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | "caught_up" | "catching_up")}>
            <option value="all">all</option>
            <option value="catching_up">catching up</option>
            <option value="caught_up">caught up</option>
          </select>
        </label>
      </div>

      {error ? (
        <div style={{ marginBottom: 12, padding: "8px 10px", borderRadius: 6, border: "1px solid #5b1f1f", background: "#2b1111", color: "#f2b8b5", fontSize: 12 }}>
          {error}
        </div>
      ) : null}

      <div style={{ overflowX: "auto", border: "1px solid #22262f", borderRadius: 6 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#131722", textAlign: "left" }}>
              <th style={{ padding: 8 }}>Asset</th>
              <th style={{ padding: 8 }}>TF</th>
              <th style={{ padding: 8 }}>Latest Bar</th>
              <th style={{ padding: 8 }}>Target End</th>
              <th style={{ padding: 8 }}>Attempted Catchup Range</th>
              <th style={{ padding: 8 }}>Behind Bars</th>
              <th style={{ padding: 8 }}>Attempted</th>
              <th style={{ padding: 8 }}>Remaining</th>
              <th style={{ padding: 8 }}>Progress %</th>
              <th style={{ padding: 8 }}>Missing Gaps</th>
              <th style={{ padding: 8 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const range = row.attempted_start_ts && row.attempted_end_ts
                ? `${fmt(row.attempted_start_ts)} → ${fmt(row.attempted_end_ts)}`
                : "-";

              return (
                <tr key={`${row.symbol}-${row.timeframe}`} style={{ borderTop: "1px solid #1f2430", background: row.is_caught_up ? "transparent" : "#1a1f2a" }}>
                  <td style={{ padding: 8 }}>{row.symbol}</td>
                  <td style={{ padding: 8 }}>{row.timeframe}</td>
                  <td style={{ padding: 8 }}>{fmt(row.latest_ts)}</td>
                  <td style={{ padding: 8 }}>{fmt(row.target_end_ts)}</td>
                  <td style={{ padding: 8 }}>{range}</td>
                  <td style={{ padding: 8 }}>{row.bars_behind_before_jump}</td>
                  <td style={{ padding: 8 }}>{row.bars_attempted_this_cycle}</td>
                  <td style={{ padding: 8 }}>{row.remaining_after_attempt_bars}</td>
                  <td style={{ padding: 8, minWidth: 150 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ flex: 1, height: 8, borderRadius: 999, background: "#2a3140", overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${Math.max(0, Math.min(100, row.catchup_progress_pct))}%`,
                            height: "100%",
                            background: progressColor(row.catchup_progress_pct),
                          }}
                        />
                      </div>
                      <span>{row.catchup_progress_pct.toFixed(2)}%</span>
                    </div>
                  </td>
                  <td style={{ padding: 8 }}>
                    {row.unresolved_gap_count} window(s)
                    <div style={{ fontSize: 11, color: "#9ba7bf" }}>
                      est bars: {row.unresolved_gap_bars_estimate}
                    </div>
                    <div style={{ fontSize: 11, color: "#9ba7bf" }}>
                      scan: {fmt(row.last_gap_scan_ts)}
                    </div>
                  </td>
                  <td style={{ padding: 8, color: row.is_caught_up ? "#86efac" : "#facc15" }}>
                    {row.is_caught_up ? "Caught up" : "Catching up"}
                  </td>
                </tr>
              );
            })}
            {sorted.length === 0 ? (
              <tr>
                <td style={{ padding: 10 }} colSpan={11}>No rows match the current filter.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
