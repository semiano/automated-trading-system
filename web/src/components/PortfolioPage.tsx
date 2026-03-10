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
    timeframe: string;
    enabled?: boolean;
    execution_mode?: "sim" | "live";
    trade_side?: "long_only" | "long_short" | "short_only";
    soft_risk_limit_usd?: number;
  }) => Promise<void>;
  onValueBalanceAsset: (payload: {
    symbol: string;
    target_base_ratio?: number;
    tolerance_bps?: number;
  }) => Promise<void>;
  onSaveRiskPolicy: (payload: {
    risk_budget_policy?: "per_symbol" | "portfolio";
    portfolio_soft_risk_limit_usd?: number;
  }) => Promise<void>;
  onGoToTradeChart: (trade: ClosedTrade) => void;
};

function timeframeColor(tf: string): string {
  if (tf === "5m") return "#f59e0b";
  return "#4ea1ff";
}

function timeframeToSeconds(tf: string): number | null {
  if (tf.endsWith("m")) return Number(tf.slice(0, -1)) * 60;
  if (tf.endsWith("h")) return Number(tf.slice(0, -1)) * 3600;
  if (tf.endsWith("d")) return Number(tf.slice(0, -1)) * 86400;
  return null;
}

function tradeLengthBars(entryTs: string, exitTs: string, timeframe: string): number | null {
  const tfSeconds = timeframeToSeconds(timeframe);
  if (!tfSeconds || !Number.isFinite(tfSeconds) || tfSeconds <= 0) return null;
  const entryMs = Date.parse(entryTs);
  const exitMs = Date.parse(exitTs);
  if (!Number.isFinite(entryMs) || !Number.isFinite(exitMs)) return null;
  const elapsedSeconds = Math.max(0, (exitMs - entryMs) / 1000);
  return Math.max(1, Math.round(elapsedSeconds / tfSeconds));
}

function usd(value: number): string {
  return value.toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

export default function PortfolioPage({ openPositions, closedTrades, totalNetPnl, assetControls, riskPolicy, pnlMode, onPnlMode, onSaveAssetControl, onValueBalanceAsset, onSaveRiskPolicy, onGoToTradeChart }: Props) {
  const [draftLimits, setDraftLimits] = useState<Record<string, string>>({});
  const [draftPortfolioLimit, setDraftPortfolioLimit] = useState<string>(String(riskPolicy.portfolio_soft_risk_limit_usd));
  const [saving, setSaving] = useState(false);
  const [logSymbol, setLogSymbol] = useState<string | null>(null);
  const [logRows, setLogRows] = useState<AssetEngineLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [rebalancingSymbol, setRebalancingSymbol] = useState<string | null>(null);
  const [filterSymbol, setFilterSymbol] = useState<string>("all");
  const [filterTimeframe, setFilterTimeframe] = useState<string>("all");
  const [filterSide, setFilterSide] = useState<string>("all");
  const [filterReason, setFilterReason] = useState<string>("all");
  const [filterPnl, setFilterPnl] = useState<string>("all");
  const [yMode, setYMode] = useState<"net" | "pct">("pct");
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [flashUntil, setFlashUntil] = useState<Record<string, number>>({});
  const prevSignalsRef = useRef<Record<string, { lastRun: string; nextRun: string; risk: number }>>({});

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const row of assetControls) {
      next[`${row.symbol}:${row.timeframe}`] = String(row.soft_risk_limit_usd);
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
      const key = `${row.symbol}:${row.timeframe}`;
      const prev = prevSignalsRef.current[key];
      if (prev) {
        if (prev.lastRun !== signal.lastRun) flashUpdates[`${key}:last`] = now + 900;
        if (prev.nextRun !== signal.nextRun) flashUpdates[`${key}:next`] = now + 900;
        if (prev.risk !== signal.risk) flashUpdates[`${key}:risk`] = now + 900;
      }
      nextSignals[key] = signal;
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
    if ((
      state === "insufficient_bars"
      || state === "regime_blocked"
      || state === "chop_blocked"
      || state === "cooldown_active"
      || state === "max_entries_per_hour"
      || state === "max_entries_per_day"
    ) && note) {
      return `${state}: ${note}`;
    }
    return state;
  };

  const orderedClosedTrades = useMemo(
    () => [...closedTrades].sort((a, b) => Date.parse(a.exit_ts) - Date.parse(b.exit_ts)),
    [closedTrades]
  );

  const symbolOptions = useMemo(() => {
    const values = Array.from(new Set(orderedClosedTrades.map((t) => t.symbol))).sort();
    return values;
  }, [orderedClosedTrades]);

  const timeframeOptions = useMemo(() => {
    const values = Array.from(new Set(orderedClosedTrades.map((t) => t.timeframe))).sort();
    return values;
  }, [orderedClosedTrades]);

  const reasonOptions = useMemo(() => {
    const values = Array.from(new Set(orderedClosedTrades.map((t) => t.exit_reason))).sort();
    return values;
  }, [orderedClosedTrades]);

  const filteredClosedTrades = useMemo(
    () =>
      orderedClosedTrades.filter((row) => {
        if (filterSymbol !== "all" && row.symbol !== filterSymbol) return false;
        if (filterTimeframe !== "all" && row.timeframe !== filterTimeframe) return false;
        if (filterSide !== "all" && row.trade_side !== filterSide) return false;
        if (filterReason !== "all" && row.exit_reason !== filterReason) return false;
        if (filterPnl === "win" && row.net_pnl <= 0) return false;
        if (filterPnl === "loss" && row.net_pnl >= 0) return false;
        return true;
      }),
    [orderedClosedTrades, filterSymbol, filterTimeframe, filterSide, filterReason, filterPnl]
  );

  const filteredSummary = useMemo(() => {
    const count = filteredClosedTrades.length;
    const net = filteredClosedTrades.reduce((sum, row) => sum + row.net_pnl, 0);
    const gross = filteredClosedTrades.reduce((sum, row) => sum + row.gross_pnl, 0);
    const fees = filteredClosedTrades.reduce((sum, row) => sum + row.fees, 0);
    const avgReturn = count > 0 ? filteredClosedTrades.reduce((sum, row) => sum + row.return_pct, 0) / count : 0;
    const wins = filteredClosedTrades.filter((row) => row.net_pnl > 0).length;
    const winRate = count > 0 ? (wins / count) * 100 : 0;
    return { count, net, gross, fees, avgReturn, winRate };
  }, [filteredClosedTrades]);

  const cumulativeNet = useMemo(() => {
    let running = 0;
    return filteredClosedTrades.map((trade) => {
      running += trade.net_pnl;
      return running;
    });
  }, [filteredClosedTrades]);

  const cumulativePct = useMemo(() => {
    let equity = 1.0;
    return filteredClosedTrades.map((trade) => {
      equity *= 1 + trade.return_pct / 100;
      return (equity - 1) * 100;
    });
  }, [filteredClosedTrades]);

  const chartValues = yMode === "pct" ? cumulativePct : cumulativeNet;
  const chartWidth = 860;
  const chartHeight = 210;
  const chartMargins = { left: 62, right: 12, top: 14, bottom: 26 };
  const innerWidth = chartWidth - chartMargins.left - chartMargins.right;
  const innerHeight = chartHeight - chartMargins.top - chartMargins.bottom;

  const chartStats = useMemo(() => {
    if (chartValues.length === 0) {
      return null;
    }
    const minV = Math.min(...chartValues);
    const maxV = Math.max(...chartValues);
    const span = Math.max(maxV - minV, 1e-9);
    const pad = span * 0.08;
    const domainMin = minV - pad;
    const domainMax = maxV + pad;
    const domainSpan = Math.max(domainMax - domainMin, 1e-9);

    const yFor = (value: number) => chartMargins.top + innerHeight - ((value - domainMin) / domainSpan) * innerHeight;
    const xFor = (index: number) =>
      chartValues.length === 1
        ? chartMargins.left + innerWidth / 2
        : chartMargins.left + (index / (chartValues.length - 1)) * innerWidth;

    const dots = chartValues.map((value, index) => ({
      x: xFor(index),
      y: yFor(value),
      value,
      timeframe: filteredClosedTrades[index]?.timeframe ?? "1m",
      trade: filteredClosedTrades[index],
    }));
    const points = dots.map((d) => `${d.x},${d.y}`).join(" ");

    const ticks = [0, 1, 2, 3, 4].map((i) => {
      const frac = i / 4;
      const value = domainMin + (1 - frac) * domainSpan;
      return { value, y: chartMargins.top + frac * innerHeight };
    });

    return { dots, points, ticks, yFor };
  }, [chartValues, filteredClosedTrades]);

  const activeHoverIndex = hoveredIndex !== null && chartStats && hoveredIndex >= 0 && hoveredIndex < chartStats.dots.length
    ? hoveredIndex
    : null;
  const hoverDot = activeHoverIndex !== null && chartStats ? chartStats.dots[activeHoverIndex] : null;

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
                <th style={{ textAlign: "left", padding: 8 }}>BB Entry</th>
                <th style={{ textAlign: "right", padding: 8 }}>Soft Risk</th>
                <th style={{ textAlign: "right", padding: 8 }}>Current Risk</th>
                <th style={{ textAlign: "left", padding: 8 }}>Last Run</th>
                <th style={{ textAlign: "left", padding: 8 }}>Next Run</th>
                <th style={{ textAlign: "left", padding: 8 }}>Tuning Params</th>
                <th style={{ textAlign: "left", padding: 8 }}>Asset Balance</th>
                <th style={{ textAlign: "left", padding: 8 }}>Logs</th>
              </tr>
            </thead>
            <tbody>
              {assetControls.map((row) => (
                <tr key={`${row.symbol}:${row.timeframe}`} style={{ borderTop: "1px solid #1b1f29" }}>
                  <td style={{ padding: 8 }}>{row.symbol} <span style={{ color: "#9ca3af" }}>({row.timeframe})</span></td>
                  <td style={{ padding: 8 }}>
                    <div style={{ display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }}>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={async () => {
                          setSaving(true);
                          try {
                            await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, enabled: true });
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
                            await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, enabled: false });
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
                            await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, trade_side: "long_only" });
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
                            await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, trade_side: "long_short" });
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
                            await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, trade_side: "short_only" });
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
                            await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, execution_mode: "sim" });
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
                            await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, execution_mode: "live" });
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
                  <td style={{ padding: 8 }}>
                    {row.bb_entry_mode === "touch_revert"
                      ? "TouchRevert"
                      : row.bb_entry_mode === "range_revert"
                        ? "RangeRevert"
                        : "Off"}
                  </td>
                  <td style={{ textAlign: "right", padding: 8 }}>
                    <input
                      type="number"
                      min={0}
                      step={1}
                      value={draftLimits[`${row.symbol}:${row.timeframe}`] ?? String(row.soft_risk_limit_usd)}
                      onChange={(e) => setDraftLimits((prev) => ({ ...prev, [`${row.symbol}:${row.timeframe}`]: e.target.value }))}
                      style={{ width: 90, padding: "3px 6px", background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4 }}
                    />
                    <button
                      type="button"
                      disabled={saving}
                      onClick={async () => {
                        const parsed = Number(draftLimits[`${row.symbol}:${row.timeframe}`]);
                        if (!Number.isFinite(parsed) || parsed < 0) return;
                        setSaving(true);
                        try {
                          await onSaveAssetControl({ symbol: row.symbol, timeframe: row.timeframe, soft_risk_limit_usd: parsed });
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
                    <span style={cellPulseStyle(`${row.symbol}:${row.timeframe}:risk`)}>{num(row.current_risk_usd, 4)}</span>
                  </td>
                  <td style={{ padding: 8 }}>
                    <span style={cellPulseStyle(`${row.symbol}:${row.timeframe}:last`)}>{parseApiTimestamp(row.last_run_ts)?.toLocaleString() ?? "-"}</span>
                    <span style={{ color: "#9ca3af", marginLeft: 6 }}>
                      {row.last_evaluated_state ? `(${formatAssetState(row.last_evaluated_state, row.last_evaluated_note)})` : ""}
                    </span>
                  </td>
                  <td style={{ padding: 8 }}>
                    <span style={cellPulseStyle(`${row.symbol}:${row.timeframe}:next`)}>{formatCountdown(row.next_run_ts)}</span>
                  </td>
                  <td style={{ padding: 8, maxWidth: 360, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {Object.entries(row.tuning_params).map(([k, v]) => `${k}=${v}`).join(", ")}
                  </td>
                  <td style={{ padding: 8, minWidth: 290 }}>
                    {row.execution_mode !== "live" ? (
                      <div style={{ display: "grid", gap: 4 }}>
                        <div>
                          <strong style={{ color: "#9ca3af" }}>SIM mode</strong>
                          <span style={{ marginLeft: 8, color: "#9ca3af" }}>live balances hidden</span>
                        </div>
                        <div style={{ color: "#9ca3af" }}>
                          Switch execution mode to <strong style={{ color: "#c7ced8" }}>live</strong> to view base/quote balances.
                        </div>
                      </div>
                    ) : row.live_balance ? (
                      <div style={{ display: "grid", gap: 4 }}>
                        <div>
                          <strong
                            style={{
                              color:
                                row.live_balance.status === "ok"
                                  ? "#85e89d"
                                  : row.live_balance.status === "imbalanced"
                                    ? "#f0d28a"
                                    : "#f2b8b5",
                            }}
                          >
                            {row.live_balance.status}
                          </strong>
                          {typeof row.live_balance.base_value_ratio === "number" ? (
                            <span style={{ marginLeft: 8, color: "#c7ced8" }}>
                              base ratio={num(row.live_balance.base_value_ratio * 100, 1)}%
                            </span>
                          ) : null}
                        </div>
                        <div style={{ color: "#c7ced8" }}>
                          quote={num(row.live_balance.quote_free, 4)} | base={num(row.live_balance.base_free, 6)}
                        </div>
                        <div style={{ color: "#9ca3af" }}>{row.live_balance.note ?? "-"}</div>
                        <button
                          type="button"
                          disabled={saving || rebalancingSymbol === row.symbol}
                          onClick={async () => {
                            setRebalancingSymbol(row.symbol);
                            try {
                              await onValueBalanceAsset({ symbol: row.symbol, target_base_ratio: 0.5, tolerance_bps: 25 });
                            } finally {
                              setRebalancingSymbol(null);
                            }
                          }}
                          style={{
                            width: "fit-content",
                            padding: "3px 8px",
                            borderRadius: 4,
                            border: "1px solid #2d3340",
                            background: "#2d3340",
                            color: "inherit",
                            cursor: "pointer",
                          }}
                        >
                          {rebalancingSymbol === row.symbol ? "Balancing..." : "Value Balance"}
                        </button>
                      </div>
                    ) : (
                      <div style={{ display: "grid", gap: 4 }}>
                        <strong style={{ color: "#f0d28a" }}>Live mode</strong>
                        <span style={{ color: "#9ca3af" }}>Balance snapshot unavailable right now. Try refresh in a few seconds.</span>
                      </div>
                    )}
                  </td>
                  <td style={{ padding: 8 }}>
                    <button
                      type="button"
                      onClick={async () => {
                        setLogSymbol(row.symbol);
                        setLogsLoading(true);
                        try {
                          const logs = await fetchAssetLogs({ symbol: row.symbol, timeframe: row.timeframe, limit: 200 });
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
                      <th style={{ textAlign: "left", padding: 8 }}>Timeframe</th>
                      <th style={{ textAlign: "left", padding: 8 }}>State</th>
                      <th style={{ textAlign: "left", padding: 8 }}>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logRows.map((row) => (
                      <tr key={row.id} style={{ borderTop: "1px solid #1b1f29" }}>
                        <td style={{ padding: 8 }}>{new Date(row.created_at).toLocaleString()}</td>
                        <td style={{ padding: 8 }}>{row.timeframe}</td>
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
                <th style={{ textAlign: "left", padding: 8 }}>Timeframe</th>
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
                <tr><td style={{ padding: 8 }} colSpan={9}>No open positions.</td></tr>
              ) : (
                openPositions.map((row) => (
                  <tr key={row.id} style={{ borderTop: "1px solid #1b1f29" }}>
                    <td style={{ padding: 8 }}>{row.symbol}</td>
                    <td style={{ padding: 8 }}>{row.timeframe}</td>
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
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
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
            <div style={{ width: 1, height: 16, background: "#2d3340", margin: "0 2px" }} />
            <button
              type="button"
              onClick={() => setYMode("pct")}
              style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: yMode === "pct" ? "#2d3340" : "transparent", color: "inherit", cursor: "pointer" }}
            >
              Y: %
            </button>
            <button
              type="button"
              onClick={() => setYMode("net")}
              style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: yMode === "net" ? "#2d3340" : "transparent", color: "inherit", cursor: "pointer" }}
            >
              Y: Net
            </button>
          </div>
        </div>
        <div style={{ padding: 10 }}>
          {chartValues.length === 0 || !chartStats ? (
            <div style={{ fontSize: 12 }}>No closed trades yet.</div>
          ) : (
            <svg width="100%" viewBox={`0 0 ${chartWidth} ${chartHeight}`} style={{ display: "block", background: "#0f131c", borderRadius: 6 }}>
              {chartStats.ticks.map((tick, idx) => (
                <g key={`tick-${idx}`}>
                  <line x1={chartMargins.left} y1={tick.y} x2={chartWidth - chartMargins.right} y2={tick.y} stroke="#1f2a3a" strokeWidth={1} />
                  <text x={chartMargins.left - 8} y={tick.y + 4} textAnchor="end" fontSize={10} fill="#93a3b8">
                    {yMode === "pct" ? `${num(tick.value, 2)}%` : num(tick.value, 4)}
                  </text>
                </g>
              ))}

              <line x1={chartMargins.left} y1={chartMargins.top} x2={chartMargins.left} y2={chartHeight - chartMargins.bottom} stroke="#334155" strokeWidth={1.2} />
              <line x1={chartMargins.left} y1={chartHeight - chartMargins.bottom} x2={chartWidth - chartMargins.right} y2={chartHeight - chartMargins.bottom} stroke="#334155" strokeWidth={1.2} />

              <polyline points={chartStats.points} fill="none" stroke="#4ea1ff" strokeWidth={2} />

              {chartStats.dots.map((pt, idx) => (
                <circle
                  key={`${idx}-${pt.timeframe}`}
                  cx={pt.x}
                  cy={pt.y}
                  r={activeHoverIndex === idx ? 4.8 : 2.8}
                  fill={timeframeColor(pt.timeframe)}
                  stroke={activeHoverIndex === idx ? "#f8fafc" : "transparent"}
                  strokeWidth={1}
                  onMouseEnter={() => setHoveredIndex(idx)}
                  onMouseMove={() => setHoveredIndex(idx)}
                  onMouseLeave={() => setHoveredIndex(null)}
                  style={{ cursor: "pointer" }}
                />
              ))}

              {hoverDot ? (
                <g>
                  <line x1={hoverDot.x} y1={chartMargins.top} x2={hoverDot.x} y2={chartHeight - chartMargins.bottom} stroke="#f8fafc" strokeDasharray="4 3" strokeWidth={1} opacity={0.8} />
                  <line x1={chartMargins.left} y1={hoverDot.y} x2={chartWidth - chartMargins.right} y2={hoverDot.y} stroke="#cbd5e1" strokeDasharray="3 3" strokeWidth={1} opacity={0.45} />
                </g>
              ) : null}
            </svg>
          )}
          {hoverDot ? (
            <div style={{ marginTop: 8, padding: "7px 9px", borderRadius: 6, border: "1px solid #334155", background: "#101827", fontSize: 11, color: "#cbd5e1", display: "flex", gap: 12, flexWrap: "wrap" }}>
              <span>{new Date(hoverDot.trade.exit_ts).toLocaleString()}</span>
              <span>{hoverDot.trade.symbol}</span>
              <span>{hoverDot.trade.timeframe}</span>
              <span>{hoverDot.trade.trade_side === "short" ? "Short" : "Long"}</span>
              <span>Trade Net {num(hoverDot.trade.net_pnl, 6)}</span>
              <span>Cum {yMode === "pct" ? `${num(hoverDot.value, 3)}%` : num(hoverDot.value, 6)}</span>
              <span>Reason {hoverDot.trade.exit_reason}</span>
            </div>
          ) : null}
          <div style={{ marginTop: 8, display: "flex", gap: 14, fontSize: 11, color: "#9ca3af" }}>
            <span><span style={{ color: "#4ea1ff" }}>●</span> 1m trade</span>
            <span><span style={{ color: "#f59e0b" }}>●</span> 5m trade</span>
          </div>
        </div>
      </section>

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }}>Closed Trades</div>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #1b1f29", display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", fontSize: 12 }}>
          <span style={{ color: "#9ca3af" }}>Filters</span>
          <select value={filterSymbol} onChange={(e) => setFilterSymbol(e.target.value)} style={{ background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4, padding: "2px 6px" }}>
            <option value="all">All Symbols</option>
            {symbolOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select value={filterTimeframe} onChange={(e) => setFilterTimeframe(e.target.value)} style={{ background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4, padding: "2px 6px" }}>
            <option value="all">All TF</option>
            {timeframeOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select value={filterSide} onChange={(e) => setFilterSide(e.target.value)} style={{ background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4, padding: "2px 6px" }}>
            <option value="all">All Sides</option>
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
          <select value={filterReason} onChange={(e) => setFilterReason(e.target.value)} style={{ background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4, padding: "2px 6px" }}>
            <option value="all">All Reasons</option>
            {reasonOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select value={filterPnl} onChange={(e) => setFilterPnl(e.target.value)} style={{ background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4, padding: "2px 6px" }}>
            <option value="all">All PnL</option>
            <option value="win">Wins Only</option>
            <option value="loss">Losses Only</option>
          </select>
          <button
            type="button"
            onClick={() => {
              setFilterSymbol("all");
              setFilterTimeframe("all");
              setFilterSide("all");
              setFilterReason("all");
              setFilterPnl("all");
            }}
            style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "transparent", color: "inherit", cursor: "pointer" }}
          >
            Clear
          </button>
        </div>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #1b1f29", fontSize: 12, color: "#cbd5e1", display: "flex", flexWrap: "wrap", gap: 14 }}>
          <span>Filtered Trades: <strong>{filteredSummary.count}</strong></span>
          <span>Filtered Net: <strong>{num(filteredSummary.net, 6)}</strong></span>
          <span>Filtered Gross: <strong>{num(filteredSummary.gross, 6)}</strong></span>
          <span>Filtered Fees: <strong>{num(filteredSummary.fees, 6)}</strong></span>
          <span>Avg Return: <strong>{num(filteredSummary.avgReturn, 3)}%</strong></span>
          <span>Win Rate: <strong>{num(filteredSummary.winRate, 2)}%</strong></span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 8 }}>Exit Time</th>
                <th style={{ textAlign: "left", padding: 8 }}>Symbol</th>
                <th style={{ textAlign: "left", padding: 8 }}>Mode</th>
                <th style={{ textAlign: "left", padding: 8 }}>TF</th>
                <th style={{ textAlign: "right", padding: 8 }}>Length</th>
                <th style={{ textAlign: "left", padding: 8 }}>Side</th>
                <th style={{ textAlign: "right", padding: 8 }}>Entry</th>
                <th style={{ textAlign: "right", padding: 8 }}>Exit</th>
                <th style={{ textAlign: "right", padding: 8 }}>P&amp;L Qty $</th>
                <th style={{ textAlign: "right", padding: 8 }}>Net P&amp;L</th>
                <th style={{ textAlign: "right", padding: 8 }}>Return %</th>
                <th style={{ textAlign: "right", padding: 8 }}>Return $</th>
                <th style={{ textAlign: "left", padding: 8 }}>Reason</th>
                <th style={{ textAlign: "left", padding: 8 }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredClosedTrades.length === 0 ? (
                <tr><td style={{ padding: 8 }} colSpan={14}>No closed trades.</td></tr>
              ) : (
                filteredClosedTrades.map((row, idx) => {
                  const notionalUsd = row.entry_price * row.qty;
                  const returnUsd = notionalUsd * (row.return_pct / 100);
                  const barsHeld = tradeLengthBars(row.entry_ts, row.exit_ts, row.timeframe);
                  const pnlPositive = row.net_pnl >= 0;
                  const rowBg = idx % 2 === 0 ? "transparent" : "#0d1118";
                  return (
                    <tr key={row.id} style={{ borderTop: "1px solid #1b1f29", background: rowBg }}>
                      <td style={{ padding: 8 }}>{new Date(row.exit_ts).toLocaleString()}</td>
                      <td style={{ padding: 8, fontWeight: 600 }}>{row.symbol}</td>
                      <td style={{ padding: 8 }}>{row.execution_mode === "sim" ? "Sim" : "Real"}</td>
                      <td style={{ padding: 8 }}>{row.timeframe}</td>
                      <td style={{ textAlign: "right", padding: 8 }}>{barsHeld !== null ? `${barsHeld} @ ${row.timeframe}` : "-"}</td>
                      <td style={{ padding: 8 }}>{row.trade_side === "short" ? "Short" : "Long"}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{num(row.entry_price, 6)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{num(row.exit_price, 6)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{usd(notionalUsd)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: pnlPositive ? "#34d399" : "#f87171", fontWeight: 600 }}>{usd(row.net_pnl)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: pnlPositive ? "#34d399" : "#f87171" }}>{num(row.return_pct, 3)}%</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: pnlPositive ? "#34d399" : "#f87171" }}>{usd(returnUsd)}</td>
                      <td style={{ padding: 8 }}>{row.exit_reason}</td>
                      <td style={{ padding: 8 }}>
                        <button
                          type="button"
                          onClick={() => onGoToTradeChart(row)}
                          style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "#101827", color: "#dbe6f5", cursor: "pointer", fontSize: 11 }}
                        >
                          Go to Chart
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
