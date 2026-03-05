import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchAssetLogs } from "../api/client";
import type { AssetControl, AssetEngineLog, ClosedTrade, OpenPosition, RiskPolicySettings } from "../api/types";
import { num } from "../utils/formatting";

type Props = {
  openPositions: OpenPosition[];
  closedTrades: ClosedTrade[];
  totalNetPnl: number;
  assetControls: AssetControl[];
  riskPolicy: RiskPolicySettings;
  pnlMode: "sim" | "live";
  onPnlMode: (mode: "sim" | "live") => void;
  onSaveAssetControl: (payload: {
    symbol: string;
    enabled?: boolean;
    execution_mode?: "sim" | "live";
    trade_side?: "long_only" | "long_short" | "short_only";
    soft_risk_limit_usd?: number;
  }) => Promise<void>;
  onSaveRiskPolicy: (payload: {
    risk_budget_policy?: "per_symbol" | "portfolio";
    portfolio_soft_risk_limit_usd?: number;
  }) => Promise<void>;
};

function toPoints(values: number[], width: number, height: number): string {
  if (values.length === 0) return "";
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const span = Math.max(maxV - minV, 1e-9);
  return values
    .map((v, i) => {
      const x = values.length === 1 ? width / 2 : (i / (values.length - 1)) * width;
      const y = height - ((v - minV) / span) * height;
      return `${x},${y}`;
    })
    .join(" ");
}

export default function PortfolioPage({ openPositions, closedTrades, totalNetPnl, assetControls, riskPolicy, pnlMode, onPnlMode, onSaveAssetControl, onSaveRiskPolicy }: Props) {
  const [draftLimits, setDraftLimits] = useState<Record<string, string>>({});
  const [draftPortfolioLimit, setDraftPortfolioLimit] = useState<string>(String(riskPolicy.portfolio_soft_risk_limit_usd));
  const [saving, setSaving] = useState(false);
  const [logSymbol, setLogSymbol] = useState<string | null>(null);
  const [logRows, setLogRows] = useState<AssetEngineLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [flashUntil, setFlashUntil] = useState<Record<string, number>>({});
  const prevSignalsRef = useRef<Record<string, { lastRun: string; nextRun: string; risk: number }>>({});

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const row of assetControls) {
      next[row.symbol] = String(row.soft_risk_limit_usd);
    }
    setDraftLimits(next);
  }, [assetControls]);

  useEffect(() => {
    setDraftPortfolioLimit(String(riskPolicy.portfolio_soft_risk_limit_usd));
  }, [riskPolicy.portfolio_soft_risk_limit_usd]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const now = Date.now();
    const nextSignals: Record<string, { lastRun: string; nextRun: string; risk: number }> = {};
    const flashUpdates: Record<string, number> = {};

    for (const row of assetControls) {
      const signal = {
        lastRun: row.last_run_ts ?? "",
        nextRun: row.next_run_ts ?? "",
        risk: row.current_risk_usd,
      };
      const prev = prevSignalsRef.current[row.symbol];
      if (prev) {
        if (prev.lastRun !== signal.lastRun) flashUpdates[`${row.symbol}:last`] = now + 900;
        if (prev.nextRun !== signal.nextRun) flashUpdates[`${row.symbol}:next`] = now + 900;
        if (prev.risk !== signal.risk) flashUpdates[`${row.symbol}:risk`] = now + 900;
      }
      nextSignals[row.symbol] = signal;
    }

    prevSignalsRef.current = nextSignals;

    if (Object.keys(flashUpdates).length > 0) {
      setFlashUntil((prev) => ({ ...prev, ...flashUpdates }));
    }
  }, [assetControls]);

  const cellPulseStyle = (key: string): React.CSSProperties => ({
    display: "inline-block",
    opacity: flashUntil[key] && flashUntil[key] > nowMs ? 0.45 : 1,
    transition: "opacity 650ms ease",
  });

  const parseApiTimestamp = (value: string | null | undefined): Date | null => {
    if (!value) return null;
    const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  };

  const formatCountdown = (nextRunTs: string | null | undefined): string => {
    const target = parseApiTimestamp(nextRunTs);
    if (!target) return "-";
    const targetMs = target.getTime();
    const remaining = Math.ceil((targetMs - nowMs) / 1000);
    if (!Number.isFinite(remaining)) return "-";
    return remaining > 0 ? `${remaining}s` : "due";
  };

  const formatAssetState = (state: string | null | undefined, note: string | null | undefined): string => {
    if (!state) return "";
    if (state === "insufficient_bars" && note) {
      return `${state}: ${note}`;
    }
    return state;
  };

  const cumulative = useMemo(() => {
    const ordered = [...closedTrades].reverse();
    let running = 0;
    return ordered.map((trade) => {
      running += trade.net_pnl;
      return running;
    });
  }, [closedTrades]);

  const pnlPoints = useMemo(() => toPoints(cumulative, 860, 160), [cumulative]);
  const singlePnlPoint = useMemo(() => {
    if (cumulative.length !== 1) return null;
    const [xRaw, yRaw] = pnlPoints.split(",");
    const x = Number(xRaw);
    const y = Number(yRaw);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return { x, y };
  }, [cumulative.length, pnlPoints]);

  return (
    <div style={{ padding: 12, display: "grid", gap: 14 }}>
      <div style={{ display: "flex", gap: 12, fontSize: 13 }}>
        <strong>Open Positions: {openPositions.length}</strong>
        <strong>Closed Trades: {closedTrades.length}</strong>
        <strong>Total Net P&amp;L: {num(totalNetPnl, 4)}</strong>
      </div>

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }}>Portfolio Risk Policy</div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", padding: 10, fontSize: 12 }}>
          <span>Policy</span>
          <div style={{ display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }}>
            <button
              type="button"
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                try {
                  await onSaveRiskPolicy({ risk_budget_policy: "per_symbol" });
                } finally {
                  setSaving(false);
                }
              }}
              style={{
                padding: "3px 8px",
                border: "none",
                borderRight: "1px solid #2d3340",
                background: riskPolicy.risk_budget_policy === "per_symbol" ? "#2d3340" : "transparent",
                color: "inherit",
                cursor: "pointer",
              }}
            >
              Per Symbol
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                try {
                  await onSaveRiskPolicy({ risk_budget_policy: "portfolio" });
                } finally {
                  setSaving(false);
                }
              }}
              style={{
                padding: "3px 8px",
                border: "none",
                background: riskPolicy.risk_budget_policy === "portfolio" ? "#2d3340" : "transparent",
                color: "inherit",
                cursor: "pointer",
              }}
            >
              Portfolio
            </button>
          </div>

          <span>Portfolio Soft Limit</span>
          <input
            type="number"
            min={0}
            step={1}
            value={draftPortfolioLimit}
            onChange={(e) => setDraftPortfolioLimit(e.target.value)}
            style={{ width: 110, padding: "3px 6px", background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4 }}
          />
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              const parsed = Number(draftPortfolioLimit);
              if (!Number.isFinite(parsed) || parsed < 0) return;
              setSaving(true);
              try {
                await onSaveRiskPolicy({ portfolio_soft_risk_limit_usd: parsed });
              } finally {
                setSaving(false);
              }
            }}
            style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "#2d3340", color: "inherit", cursor: "pointer" }}
          >
            Set
          </button>
          <span style={{ color: "#9ca3af" }}>0 disables global cap</span>
        </div>
      </section>

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }}>Control Plane</div>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #1b1f29", fontSize: 12, color: "#c7ced8" }}>
          Active Global Policy: <strong>{riskPolicy.risk_budget_policy === "portfolio" ? "Portfolio" : "Per Symbol"}</strong>
          <span style={{ marginLeft: 10 }}>
            Global Soft Limit: <strong>{num(riskPolicy.portfolio_soft_risk_limit_usd, 2)}</strong>
          </span>
          {riskPolicy.portfolio_soft_risk_limit_usd <= 0 ? <span style={{ marginLeft: 10, color: "#9ca3af" }}>(disabled)</span> : null}
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 8 }}>Asset</th>
                <th style={{ textAlign: "left", padding: 8 }}>Run/Pause</th>
                <th style={{ textAlign: "left", padding: 8 }}>Mode</th>
                <th style={{ textAlign: "left", padding: 8 }}>Side</th>
                <th style={{ textAlign: "right", padding: 8 }}>Soft Risk</th>
                <th style={{ textAlign: "right", padding: 8 }}>Current Risk</th>
                <th style={{ textAlign: "left", padding: 8 }}>Last Run</th>
                <th style={{ textAlign: "left", padding: 8 }}>Next Run</th>
                <th style={{ textAlign: "left", padding: 8 }}>Tuning Params</th>
                <th style={{ textAlign: "left", padding: 8 }}>Logs</th>
              </tr>
            </thead>
            <tbody>
              {assetControls.map((row) => (
                <tr key={row.symbol} style={{ borderTop: "1px solid #1b1f29" }}>
                  <td style={{ padding: 8 }}>{row.symbol}</td>
                  <td style={{ padding: 8 }}>
                    <div style={{ display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }}>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, enabled: true });
                          } finally {
                            setSaving(false);
                          }
                        }}
                        style={{
                          padding: "3px 8px",
                          border: "none",
                          borderRight: "1px solid #2d3340",
                          background: row.enabled ? "#2f5f3a" : "transparent",
                          color: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        Run
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, enabled: false });
                          } finally {
                            setSaving(false);
                          }
                        }}
                        style={{
                          padding: "3px 8px",
                          border: "none",
                          background: !row.enabled ? "#5f2f2f" : "transparent",
                          color: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        Pause
                      </button>
                    </div>
                  </td>
                  <td style={{ padding: 8 }}>
                    <div style={{ display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }}>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, trade_side: "long_only" });
                          } finally {
                            setSaving(false);
                          }
                        }}
                        style={{
                          padding: "3px 8px",
                          border: "none",
                          borderRight: "1px solid #2d3340",
                          background: row.trade_side === "long_only" ? "#2d3340" : "transparent",
                          color: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        Long
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, trade_side: "long_short" });
                          } finally {
                            setSaving(false);
                          }
                        }}
                        style={{
                          padding: "3px 8px",
                          border: "none",
                          borderRight: "1px solid #2d3340",
                          background: row.trade_side === "long_short" ? "#2d3340" : "transparent",
                          color: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        Both
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, trade_side: "short_only" });
                          } finally {
                            setSaving(false);
                          }
                        }}
                        style={{
                          padding: "3px 8px",
                          border: "none",
                          background: row.trade_side === "short_only" ? "#2d3340" : "transparent",
                          color: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        Short
                      </button>
                    </div>
                  </td>
                  <td style={{ padding: 8 }}>
                    <div style={{ display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }}>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, execution_mode: "sim" });
                          } finally {
                            setSaving(false);
                          }
                        }}
                        style={{
                          padding: "3px 8px",
                          border: "none",
                          borderRight: "1px solid #2d3340",
                          background: row.execution_mode === "sim" ? "#2d3340" : "transparent",
                          color: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        Sim
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, execution_mode: "live" });
                          } finally {
                            setSaving(false);
                          }
                        }}
                        style={{
                          padding: "3px 8px",
                          border: "none",
                          background: row.execution_mode === "live" ? "#2d3340" : "transparent",
                          color: "inherit",
                          cursor: "pointer",
                        }}
                      >
                        Active
                      </button>
                    </div>
                  </td>
                  <td style={{ textAlign: "right", padding: 8 }}>
                    <input
                      type="number"
                      min={0}
                      step={1}
                      value={draftLimits[row.symbol] ?? String(row.soft_risk_limit_usd)}
                      onChange={(e) => setDraftLimits((prev) => ({ ...prev, [row.symbol]: e.target.value }))}
                      style={{ width: 90, padding: "3px 6px", background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4 }}
                    />
                    <button
                      type="button"
                      disabled={saving}
                      onClick={async () => {
                        const parsed = Number(draftLimits[row.symbol]);
                        if (!Number.isFinite(parsed) || parsed < 0) return;
                        setSaving(true);
                        try {
                          await onSaveAssetControl({ symbol: row.symbol, soft_risk_limit_usd: parsed });
                        } finally {
                          setSaving(false);
                        }
                      }}
                      style={{ marginLeft: 6, padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "#2d3340", color: "inherit", cursor: "pointer" }}
                    >
                      Set
                    </button>
                  </td>
                  <td style={{ textAlign: "right", padding: 8 }}>
                    <span style={cellPulseStyle(`${row.symbol}:risk`)}>{num(row.current_risk_usd, 4)}</span>
                  </td>
                  <td style={{ padding: 8 }}>
                    <span style={cellPulseStyle(`${row.symbol}:last`)}>{parseApiTimestamp(row.last_run_ts)?.toLocaleString() ?? "-"}</span>
                    <span style={{ color: "#9ca3af", marginLeft: 6 }}>
                      {row.last_evaluated_state ? `(${formatAssetState(row.last_evaluated_state, row.last_evaluated_note)})` : ""}
                    </span>
                  </td>
                  <td style={{ padding: 8 }}>
                    <span style={cellPulseStyle(`${row.symbol}:next`)}>{formatCountdown(row.next_run_ts)}</span>
                  </td>
                  <td style={{ padding: 8, maxWidth: 360, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {Object.entries(row.tuning_params).map(([k, v]) => `${k}=${v}`).join(", ")}
                  </td>
                  <td style={{ padding: 8 }}>
                    <button
                      type="button"
                      onClick={async () => {
                        setLogSymbol(row.symbol);
                        setLogsLoading(true);
                        try {
                          const logs = await fetchAssetLogs({ symbol: row.symbol, limit: 200 });
                          setLogRows(logs);
                        } finally {
                          setLogsLoading(false);
                        }
                      }}
                      style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "#2d3340", color: "inherit", cursor: "pointer" }}
                    >
                      View Logs
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {logSymbol && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 50,
          }}
          onClick={() => setLogSymbol(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(980px, 92vw)",
              maxHeight: "78vh",
              overflow: "hidden",
              background: "#0f131c",
              border: "1px solid #2d3340",
              borderRadius: 8,
              display: "grid",
              gridTemplateRows: "auto 1fr",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", borderBottom: "1px solid #2d3340" }}>
              <strong>Runtime Logs — {logSymbol}</strong>
              <button type="button" onClick={() => setLogSymbol(null)} style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "transparent", color: "inherit", cursor: "pointer" }}>
                Close
              </button>
            </div>
            <div style={{ overflow: "auto" }}>
              {logsLoading ? (
                <div style={{ padding: 12, fontSize: 12 }}>Loading logs...</div>
              ) : logRows.length === 0 ? (
                <div style={{ padding: 12, fontSize: 12 }}>No logs available.</div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: 8 }}>Timestamp</th>
                      <th style={{ textAlign: "left", padding: 8 }}>State</th>
                      <th style={{ textAlign: "left", padding: 8 }}>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logRows.map((row) => (
                      <tr key={row.id} style={{ borderTop: "1px solid #1b1f29" }}>
                        <td style={{ padding: 8 }}>{new Date(row.created_at).toLocaleString()}</td>
                        <td style={{ padding: 8 }}>{row.state}</td>
                        <td style={{ padding: 8 }}>{row.note ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }}>Open Positions</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 8 }}>Symbol</th>
                <th style={{ textAlign: "left", padding: 8 }}>Side</th>
                <th style={{ textAlign: "right", padding: 8 }}>Entry</th>
                <th style={{ textAlign: "right", padding: 8 }}>Last</th>
                <th style={{ textAlign: "right", padding: 8 }}>Qty</th>
                <th style={{ textAlign: "right", padding: 8 }}>Unrealized P&amp;L</th>
                <th style={{ textAlign: "right", padding: 8 }}>Unrealized %</th>
                <th style={{ textAlign: "right", padding: 8 }}>Hold Bars</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.length === 0 ? (
                <tr><td style={{ padding: 8 }} colSpan={8}>No open positions.</td></tr>
              ) : (
                openPositions.map((row) => (
                  <tr key={row.id} style={{ borderTop: "1px solid #1b1f29" }}>
                    <td style={{ padding: 8 }}>{row.symbol}</td>
                    <td style={{ padding: 8 }}>{row.trade_side === "short" ? "Short" : "Long"}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.entry_price, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.last_price, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.qty, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.unrealized_pnl, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.unrealized_return_pct, 3)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{row.hold_bars}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600, display: "flex", justifyContent: "space-between" }}>
          <span>Historical Net P&amp;L</span>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              onClick={() => onPnlMode("sim")}
              style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: pnlMode === "sim" ? "#2d3340" : "transparent", color: "inherit", cursor: "pointer" }}
            >
              Sim
            </button>
            <button
              type="button"
              onClick={() => onPnlMode("live")}
              style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: pnlMode === "live" ? "#2d3340" : "transparent", color: "inherit", cursor: "pointer" }}
            >
              Real
            </button>
          </div>
        </div>
        <div style={{ padding: 10 }}>
          {cumulative.length === 0 ? (
            <div style={{ fontSize: 12 }}>No closed trades yet.</div>
          ) : (
            <svg width="100%" viewBox="0 0 860 170" style={{ display: "block", background: "#0f131c", borderRadius: 6 }}>
              {singlePnlPoint ? (
                <circle cx={singlePnlPoint.x} cy={singlePnlPoint.y} r={4} fill="#4ea1ff" />
              ) : (
                <polyline points={pnlPoints} fill="none" stroke="#4ea1ff" strokeWidth={2} />
              )}
            </svg>
          )}
        </div>
      </section>

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }}>Closed Trades</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 8 }}>Exit Time</th>
                <th style={{ textAlign: "left", padding: 8 }}>Symbol</th>
                <th style={{ textAlign: "left", padding: 8 }}>Mode</th>
                <th style={{ textAlign: "left", padding: 8 }}>Side</th>
                <th style={{ textAlign: "right", padding: 8 }}>Entry</th>
                <th style={{ textAlign: "right", padding: 8 }}>Exit</th>
                <th style={{ textAlign: "right", padding: 8 }}>Qty</th>
                <th style={{ textAlign: "right", padding: 8 }}>Net P&amp;L</th>
                <th style={{ textAlign: "right", padding: 8 }}>Return %</th>
                <th style={{ textAlign: "left", padding: 8 }}>Reason</th>
              </tr>
            </thead>
            <tbody>
              {closedTrades.length === 0 ? (
                <tr><td style={{ padding: 8 }} colSpan={10}>No closed trades.</td></tr>
              ) : (
                closedTrades.map((row) => (
                  <tr key={row.id} style={{ borderTop: "1px solid #1b1f29" }}>
                    <td style={{ padding: 8 }}>{new Date(row.exit_ts).toLocaleString()}</td>
                    <td style={{ padding: 8 }}>{row.symbol}</td>
                    <td style={{ padding: 8 }}>{row.execution_mode === "sim" ? "Sim" : "Real"}</td>
                    <td style={{ padding: 8 }}>{row.trade_side === "short" ? "Short" : "Long"}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.entry_price, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.exit_price, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.qty, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.net_pnl, 6)}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>{num(row.return_pct, 3)}</td>
                    <td style={{ padding: 8 }}>{row.exit_reason}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
