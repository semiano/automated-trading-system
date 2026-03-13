import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchAssetLogs, fetchCandles, fetchIndicators } from "../api/client";
import type { AssetControl, AssetEngineLog, AssetTuningVersion, ClosedTrade, IndicatorRow, LiveReadiness, OpenPosition, PortfolioBalancesSnapshot } from "../api/types";
import { num } from "../utils/formatting";

type Props = {
  openPositions: OpenPosition[];
  closedTrades: ClosedTrade[];
  totalNetPnl: number;
  assetControls: AssetControl[];
  portfolioBalances: PortfolioBalancesSnapshot | null;
  liveReadiness: LiveReadiness | null;
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
  onSaveAssetTuning: (payload: {
    symbol: string;
    timeframe: string;
    bb_length?: number;
    bb_stdev?: number;
    atr_length?: number;
    ema_fast?: number;
    ema_slow?: number;
    bb_entry_deviation?: number;
    bb_exit_deviation?: number;
    slope_lookback_bars?: number;
    slope_flatten_factor?: number;
    stop_atr?: number;
    take_profit_atr?: number;
    max_hold_bars?: number;
    min_hold_bars?: number;
    max_take_profit_pct?: number;
    note?: string;
    source?: string;
    updated_by?: string;
  }) => Promise<void>;
  onFetchAssetTuningVersions: (payload: { symbol: string; timeframe: string; limit?: number }) => Promise<AssetTuningVersion[]>;
  onValueBalanceAsset: (payload: {
    symbol: string;
    target_base_ratio?: number;
    tolerance_bps?: number;
  }) => Promise<void>;
  onAugmentSimWallet: (payload: {
    symbol: string;
    bucket: "cash" | "asset";
    amount_usd: number;
  }) => Promise<void>;
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

function tradeLengthLabel(trade: ClosedTrade): string {
  if (typeof trade.hold_bars_at_exit === "number" && Number.isFinite(trade.hold_bars_at_exit) && trade.hold_bars_at_exit > 0) {
    return `${trade.hold_bars_at_exit} @ ${trade.timeframe}`;
  }
  const barsHeld = tradeLengthBars(trade.entry_ts, trade.exit_ts, trade.timeframe);
  return barsHeld !== null ? `${barsHeld} @ ${trade.timeframe}` : "-";
}

function usd(value: number): string {
  return value.toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

function slippageLabel(bps: number | null | undefined, impactUsd: number | null | undefined): string {
  if (bps == null || impactUsd == null) return "-";
  const bpsText = `${num(bps, 2)} bps`;
  const usdText = impactUsd >= 0 ? `+${usd(impactUsd)}` : usd(impactUsd);
  return `${bpsText} (${usdText})`;
}

function slippageTone(impactUsd: number | null | undefined): string {
  if (impactUsd == null) return "inherit";
  if (impactUsd > 0) return "#fca5a5";
  if (impactUsd < 0) return "#86efac";
  return "#cbd5e1";
}

export default function PortfolioPage({ openPositions, closedTrades, totalNetPnl, assetControls, portfolioBalances, liveReadiness, pnlMode, onPnlMode, onSaveAssetControl, onSaveAssetTuning, onFetchAssetTuningVersions, onValueBalanceAsset, onAugmentSimWallet }: Props) {
  const [draftLimits, setDraftLimits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [logSymbol, setLogSymbol] = useState<string | null>(null);
  const [logRows, setLogRows] = useState<AssetEngineLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [tuningRow, setTuningRow] = useState<AssetControl | null>(null);
  const [tuningDraft, setTuningDraft] = useState<Record<string, string>>({});
  const [tuningNote, setTuningNote] = useState<string>("");
  const [tuningSource, setTuningSource] = useState<string>("");
  const [tuningUpdatedBy, setTuningUpdatedBy] = useState<string>("");
  const [tuningVersions, setTuningVersions] = useState<AssetTuningVersion[]>([]);
  const [tuningLoading, setTuningLoading] = useState(false);
  const [tuningSaving, setTuningSaving] = useState(false);
  const [rebalancingSymbol, setRebalancingSymbol] = useState<string | null>(null);
  const [augmentingKey, setAugmentingKey] = useState<string | null>(null);
  const [filterSymbol, setFilterSymbol] = useState<string>("all");
  const [filterTimeframe, setFilterTimeframe] = useState<string>("all");
  const [filterSide, setFilterSide] = useState<string>("all");
  const [filterReason, setFilterReason] = useState<string>("all");
  const [filterPnl, setFilterPnl] = useState<string>("all");
  const [yMode, setYMode] = useState<"net" | "pct">("pct");
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [previewTrade, setPreviewTrade] = useState<ClosedTrade | null>(null);
  const [previewRows, setPreviewRows] = useState<IndicatorRow[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewHoverIndex, setPreviewHoverIndex] = useState<number | null>(null);
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
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!previewTrade) return;
    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        setPreviewTrade(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewTrade]);

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

  const parseApiTsMillis = (value: string | null | undefined): number => {
    const parsed = parseApiTimestamp(value);
    return parsed ? parsed.getTime() : Number.NaN;
  };

  const openTradePreview = async (trade: ClosedTrade) => {
    setPreviewTrade(trade);
    setPreviewRows([]);
    setPreviewError(null);
    setPreviewHoverIndex(null);
    setPreviewLoading(true);

    try {
      const tfSeconds = timeframeToSeconds(trade.timeframe) ?? 300;
      const entryMs = parseApiTsMillis(trade.entry_ts);
      const exitMs = parseApiTsMillis(trade.exit_ts);
      const centerStart = Number.isFinite(entryMs) ? entryMs : Date.now();
      const centerEnd = Number.isFinite(exitMs) ? exitMs : centerStart;
      const minMs = Math.min(centerStart, centerEnd);
      const maxMs = Math.max(centerStart, centerEnd);

      const start = new Date(Math.max(0, minMs - tfSeconds * 80_000)).toISOString();
      const end = new Date(maxMs + tfSeconds * 80_000).toISOString();

      const [candles, indicatorRows] = await Promise.all([
        fetchCandles({ symbol: trade.symbol, timeframe: trade.timeframe, venue: trade.venue, start, end, limit: 2000 }),
        fetchIndicators({
          symbol: trade.symbol,
          timeframe: trade.timeframe,
          venue: trade.venue,
          start,
          end,
          indicators: "bbands,ema20,ema50,ema200",
        }).catch(() => [] as IndicatorRow[]),
      ]);

      const merged = new Map<string, IndicatorRow>();
      candles.forEach((row) => merged.set(row.ts, { ...row }));
      indicatorRows.forEach((row) => merged.set(row.ts, { ...(merged.get(row.ts) ?? row), ...row }));

      const sorted = Array.from(merged.values()).sort((a, b) => parseApiTsMillis(a.ts) - parseApiTsMillis(b.ts));
      if (sorted.length === 0) {
        setPreviewRows([]);
        setPreviewError("No candles found for this trade window.");
        return;
      }

      const firstInside = sorted.findIndex((row) => parseApiTsMillis(row.ts) >= minMs);
      let lastInside = -1;
      for (let i = sorted.length - 1; i >= 0; i -= 1) {
        if (parseApiTsMillis(sorted[i].ts) <= maxMs) {
          lastInside = i;
          break;
        }
      }

      const baseStart = firstInside >= 0 ? firstInside : 0;
      const baseEnd = lastInside >= 0 ? Math.max(lastInside, baseStart) : sorted.length - 1;
      const windowStart = Math.max(0, baseStart - 10);
      const windowEnd = Math.min(sorted.length - 1, baseEnd + 10);
      setPreviewRows(sorted.slice(windowStart, windowEnd + 1));
    } catch {
      setPreviewRows([]);
      setPreviewError("Failed to load trade preview data.");
    } finally {
      setPreviewLoading(false);
    }
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

  const editableTuningFields = [
    "bb_length",
    "bb_stdev",
    "atr_length",
    "ema_fast",
    "ema_slow",
    "bb_entry_deviation",
    "bb_exit_deviation",
    "slope_lookback_bars",
    "slope_flatten_factor",
    "stop_atr",
    "take_profit_atr",
    "max_hold_bars",
    "min_hold_bars",
    "max_take_profit_pct",
  ] as const;

  const openTuningPopover = async (row: AssetControl) => {
    setTuningRow(row);
    const nextDraft: Record<string, string> = {};
    for (const key of editableTuningFields) {
      const value = row.tuning_params[key];
      nextDraft[key] = typeof value === "number" ? String(value) : "";
    }
    setTuningDraft(nextDraft);
    setTuningNote(row.tuning_note ?? "");
    setTuningSource(row.tuning_source ?? "manual");
    setTuningUpdatedBy(row.tuning_updated_by ?? "");
    setTuningLoading(true);
    try {
      const versions = await onFetchAssetTuningVersions({ symbol: row.symbol, timeframe: row.timeframe, limit: 30 });
      setTuningVersions(versions);
    } finally {
      setTuningLoading(false);
    }
  };

  const saveTuningFromPopover = async () => {
    if (!tuningRow) return;
    const payload: Record<string, string | number | undefined> = {
      symbol: tuningRow.symbol,
      timeframe: tuningRow.timeframe,
      note: tuningNote || undefined,
      source: tuningSource || undefined,
      updated_by: tuningUpdatedBy || undefined,
    };
    for (const key of editableTuningFields) {
      const raw = tuningDraft[key]?.trim();
      if (!raw) continue;
      const parsed = Number(raw);
      if (Number.isFinite(parsed)) {
        payload[key] = parsed;
      }
    }

    setTuningSaving(true);
    try {
      await onSaveAssetTuning(payload as Parameters<Props["onSaveAssetTuning"]>[0]);
      const versions = await onFetchAssetTuningVersions({ symbol: tuningRow.symbol, timeframe: tuningRow.timeframe, limit: 30 });
      setTuningVersions(versions);
    } finally {
      setTuningSaving(false);
    }
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

    const tradeTimes = filteredClosedTrades.map((trade, index) => {
      const t = Date.parse(trade.exit_ts);
      return Number.isNaN(t) ? index : t;
    });
    const minTime = Math.min(...tradeTimes);
    const maxTime = Math.max(...tradeTimes);
    const timeSpan = Math.max(maxTime - minTime, 1);
    const xFor = (timeMs: number) =>
      chartValues.length === 1
        ? chartMargins.left + innerWidth / 2
        : chartMargins.left + ((timeMs - minTime) / timeSpan) * innerWidth;

    const dots = chartValues.map((value, index) => ({
      x: xFor(tradeTimes[index]),
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

    const dayGridLines: Array<{ x: number; label: string }> = [];
    const startDay = new Date(minTime);
    startDay.setHours(0, 0, 0, 0);
    if (startDay.getTime() < minTime) {
      startDay.setDate(startDay.getDate() + 1);
    }
    const endTime = maxTime;
    for (let t = startDay.getTime(); t <= endTime; t += 86_400_000) {
      dayGridLines.push({ x: xFor(t), label: new Date(t).toLocaleDateString() });
    }

    return { dots, points, ticks, yFor, dayGridLines };
  }, [chartValues, filteredClosedTrades]);

  const activeHoverIndex = hoveredIndex !== null && chartStats && hoveredIndex >= 0 && hoveredIndex < chartStats.dots.length
    ? hoveredIndex
    : null;
  const hoverDot = activeHoverIndex !== null && chartStats ? chartStats.dots[activeHoverIndex] : null;
  const balancesMode = portfolioBalances?.mode ?? pnlMode;
  const isSimBalances = balancesMode === "sim";
  const freeLabel = isSimBalances ? "Available Cash (USD)" : "Free Qty";
  const freeTitle = isSimBalances
    ? "SIM: available cash after applying realized/unrealized PnL and open notional commitments."
    : "LIVE: free exchange quantity for this asset/currency.";
  const pxLabel = isSimBalances ? "Unit (USD)" : "USD Price";
  const pxTitle = isSimBalances
    ? "SIM: fixed to 1.0 because values are already represented in USD budget units."
    : "LIVE: inferred USD conversion price used for valuation.";
  const valueLabel = isSimBalances ? "Equity (USD)" : "Value (USD)";
  const valueTitle = isSimBalances
    ? "SIM: symbol equity = budget + realized PnL + unrealized PnL."
    : "LIVE: USD-marked value of free quantity for this asset/currency.";

  const fundingRows = useMemo(() => {
    const controlsForMode = assetControls.filter((row) => row.execution_mode === balancesMode);
    const requiredBySymbol = new Map<string, number>();
    for (const row of controlsForMode) {
      requiredBySymbol.set(row.symbol, (requiredBySymbol.get(row.symbol) ?? 0) + Number(row.soft_risk_limit_usd || 0));
    }

    const currencyFree = new Map<string, number>();
    const currencyValueUsd = new Map<string, number>();
    for (const row of portfolioBalances?.assets ?? []) {
      const ccy = String(row.asset || "").toUpperCase();
      if (!ccy) continue;
      currencyFree.set(ccy, Number(row.free || 0));
      currencyValueUsd.set(ccy, Number(row.value_usd || 0));
    }

    const symbolsForTable = new Set<string>(requiredBySymbol.keys());
    for (const row of assetControls) symbolsForTable.add(row.symbol);
    if (!isSimBalances && symbolsForTable.size === 0) {
      for (const row of portfolioBalances?.assets ?? []) symbolsForTable.add(row.asset);
    }

    const splitSymbol = (value: string): { base: string; quote: string | null } => {
      if (value.includes("/")) {
        const [base, quote] = value.split("/", 2);
        return { base: base.toUpperCase(), quote: quote.toUpperCase() };
      }
      return { base: value.toUpperCase(), quote: null };
    };

    const assetRows = Array.from(symbolsForTable).sort().map((symbol) => {
      const required = requiredBySymbol.get(symbol) ?? 0;
      const { base, quote } = splitSymbol(symbol);

      let assetQty = 0;
      let assetUsd = 0;
      let cashQty = 0;
      let cashUsd = 0;
      let price = 0;

      if (isSimBalances) {
        const simRow = (portfolioBalances?.assets ?? []).find((r) => r.asset === symbol);
        const equity = Number(simRow?.value_usd || 0);
        const availableCash = Number(simRow?.free || 0);
        cashUsd = Math.max(availableCash, 0);
        assetUsd = Math.max(equity - cashUsd, 0);
        cashQty = cashUsd;
        assetQty = assetUsd;
        price = 1.0;
      } else {
        assetQty = Number(currencyFree.get(base) || 0);
        assetUsd = Number(currencyValueUsd.get(base) || 0);
        if (quote) {
          cashQty = Number(currencyFree.get(quote) || 0);
          cashUsd = Number(currencyValueUsd.get(quote) || 0);
        }

        const liveRow = controlsForMode.find((r) => r.symbol === symbol && r.live_balance?.price != null);
        const livePx = Number(liveRow?.live_balance?.price || 0);
        if (Number.isFinite(livePx) && livePx > 0) {
          price = livePx;
        } else if (assetQty > 0 && assetUsd > 0) {
          price = assetUsd / assetQty;
        }

        if (!quote && assetUsd <= 0 && cashUsd <= 0) {
          const currencyRow = (portfolioBalances?.assets ?? []).find((r) => String(r.asset).toUpperCase() === base);
          if (currencyRow) {
            assetQty = Number(currencyRow.free || 0);
            assetUsd = Number(currencyRow.value_usd || 0);
            if (assetQty > 0 && assetUsd > 0) price = assetUsd / assetQty;
          }
        }
      }

      const actual = assetUsd;
      const ratio = required > 0 ? actual / required : null;
      const gapUsd = actual - required;
      const requiredQty = price > 0 ? required / price : null;
      const gapQty = price > 0 ? gapUsd / price : null;
      let status: "aligned" | "needs_alignment" | "critical" | "surplus" | "no_target" = "no_target";

      if (required > 0) {
        if (ratio !== null && ratio < 0.5) status = "critical";
        else if (ratio !== null && ratio < 0.9) status = "needs_alignment";
        else if (ratio !== null && ratio > 1.5) status = "surplus";
        else status = "aligned";
      } else if (actual > 0 || cashUsd > 0) {
        status = "aligned";
      }

      return {
        rowType: "asset" as const,
        symbol,
        required,
        actual,
        ratio,
        requiredQty,
        actualQty: assetQty,
        gapUsd,
        gapQty,
        cashUsd,
        cashQty,
        status,
      };
    });

    const totalRequiredCashUsd = assetRows.reduce((sum, row) => sum + row.required, 0);
    const totalActualCashUsd = assetRows.reduce((sum, row) => sum + row.cashUsd, 0);
    const totalActualCashQty = assetRows.reduce((sum, row) => sum + row.cashQty, 0);
    const cashGapUsd = totalActualCashUsd - totalRequiredCashUsd;
    let cashStatus: "aligned" | "needs_alignment" | "critical" | "surplus" | "no_target" = "no_target";
    if (totalRequiredCashUsd > 0) {
      const ratio = totalActualCashUsd / totalRequiredCashUsd;
      if (ratio < 0.5) cashStatus = "critical";
      else if (ratio < 0.9) cashStatus = "needs_alignment";
      else if (ratio > 1.5) cashStatus = "surplus";
      else cashStatus = "aligned";
    }

    return [
      ...assetRows,
      {
        rowType: "cash" as const,
        symbol: "CASH (PORTFOLIO)",
        required: totalRequiredCashUsd,
        actual: totalActualCashUsd,
        ratio: totalRequiredCashUsd > 0 ? totalActualCashUsd / totalRequiredCashUsd : null,
        requiredQty: totalRequiredCashUsd,
        actualQty: totalActualCashQty,
        gapUsd: cashGapUsd,
        gapQty: cashGapUsd,
        cashUsd: totalActualCashUsd,
        cashQty: totalActualCashQty,
        status: cashStatus,
      },
    ];
  }, [assetControls, balancesMode, isSimBalances, portfolioBalances]);

  const fundingBadge = (status: "aligned" | "needs_alignment" | "critical" | "surplus" | "no_target") => {
    if (status === "aligned") return { text: "Aligned", bg: "#1f4d32", fg: "#d1fae5" };
    if (status === "needs_alignment") return { text: "Needs Align", bg: "#5a4316", fg: "#fde68a" };
    if (status === "critical") return { text: "Critical", bg: "#5b1f1f", fg: "#fecaca" };
    if (status === "surplus") return { text: "Surplus", bg: "#1e3a5f", fg: "#bfdbfe" };
    return { text: "No Target", bg: "#374151", fg: "#e5e7eb" };
  };

  return (
    <div style={{ padding: 12, display: "grid", gap: 14 }}>
      <div style={{ display: "flex", gap: 12, fontSize: 13 }}>
        <strong>Open Positions: {openPositions.length}</strong>
        <strong>Closed Trades: {closedTrades.length}</strong>
        <strong>Total Net P&amp;L: {num(totalNetPnl, 4)}</strong>
      </div>

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Portfolio Balances</span>
          <div style={{ display: "inline-flex", gap: 8 }}>
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
        <div style={{ padding: 10, fontSize: 12, display: "grid", gap: 8 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            <span title="Sum of all rows in this mode.">
              Total: <strong>{portfolioBalances ? usd(portfolioBalances.total_value_usd) : "-"}</strong>
            </span>
            <span title={isSimBalances ? "SIM available budget pool across symbols." : "LIVE value held in USD-like quote currencies (USD/USDT/USDC/etc.)."}>
              Cash: <strong>{portfolioBalances ? usd(portfolioBalances.cash_value_usd) : "-"}</strong>
            </span>
            <span title={isSimBalances ? "SIM budget currently allocated to open risk." : "LIVE value held in non-cash assets (e.g. BTC, ETH)."}>
              Asset: <strong>{portfolioBalances ? usd(portfolioBalances.asset_value_usd) : "-"}</strong>
            </span>
            <span title="Cash / Total.">
              Cash Ratio: <strong>{portfolioBalances ? `${num(portfolioBalances.cash_ratio * 100, 2)}%` : "-"}</strong>
            </span>
            <span title="Asset / Total.">
              Asset Ratio: <strong>{portfolioBalances ? `${num(portfolioBalances.asset_ratio * 100, 2)}%` : "-"}</strong>
            </span>
          </div>
          {portfolioBalances?.note ? <div style={{ color: "#9ca3af" }}>{portfolioBalances.note}</div> : null}
          {liveReadiness ? (
            <div style={{ color: "#c7ced8" }}>
              Live Readiness: <strong style={{ color: liveReadiness.balance_readable ? "#86efac" : "#fca5a5" }}>{liveReadiness.balance_readable ? "balance OK" : "balance failed"}</strong>
              {" | "}venue=<strong>{liveReadiness.venue}</strong>
              {" | "}sandbox=<strong>{liveReadiness.sandbox ? "on" : "off"}</strong>
              {" | "}keys=<strong>{liveReadiness.api_key_present && liveReadiness.api_secret_present ? "present" : "missing"}</strong>
              {" | "}real adapter=<strong>{liveReadiness.real_adapter_enabled_any ? "enabled" : "disabled"}</strong>
              {" | "}live orders=<strong>{liveReadiness.live_order_enabled_any ? "enabled" : "disabled"}</strong>
            </div>
          ) : null}
          {liveReadiness?.note ? <div style={{ color: "#9ca3af" }}>{liveReadiness.note}</div> : null}
          {!liveReadiness?.balance_readable && liveReadiness?.balance_error ? <div style={{ color: "#fca5a5" }}>{liveReadiness.balance_error}</div> : null}
          <div style={{ color: "#9ca3af" }}>
            {isSimBalances
              ? "SIM mode: balances are trade-aware simulation balances (cash, exposure, and equity), not exchange wallets."
              : "LIVE mode: balances are exchange free balances valued in USD."}
          </div>
          <div style={{ color: "#9ca3af" }}>
            As Of: {portfolioBalances?.as_of ? new Date(portfolioBalances.as_of).toLocaleString() : "-"}
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: 8 }}>Balance Row</th>
                  <th style={{ textAlign: "right", padding: 8 }} title="Required balance in USD and units.">Balance Required (USD | Units)</th>
                  <th style={{ textAlign: "right", padding: 8 }} title="Actual balance in USD and units.">Balance Actual (USD | Units)</th>
                  <th style={{ textAlign: "right", padding: 8 }} title="Actual minus Required in USD and units.">Gap (USD | Units)</th>
                  <th style={{ textAlign: "right", padding: 8 }} title="Actual/Required ratio.">Coverage</th>
                  <th style={{ textAlign: "left", padding: 8 }} title="Color-coded alignment indicator for balancing or funding action.">Status</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {fundingRows.length === 0 ? (
                  <tr>
                    <td style={{ padding: 8 }} colSpan={7}>No balance rows.</td>
                  </tr>
                ) : (
                  fundingRows.map((row) => {
                    const badge = fundingBadge(row.status);
                    return (
                    <tr key={row.symbol} style={{ borderTop: "1px solid #1b1f29" }}>
                      <td style={{ padding: 8 }}>
                        <div>{row.rowType === "cash" ? "Cash Balance" : row.symbol}</div>
                        {row.rowType === "asset" ? <div style={{ color: "#9ca3af" }}>Asset leg</div> : <div style={{ color: "#9ca3af" }}>Portfolio cash row</div>}
                      </td>
                      <td style={{ textAlign: "right", padding: 8 }}>
                        <div>{usd(row.required)}</div>
                        <div style={{ color: "#9ca3af" }}>{row.requiredQty == null ? "-" : num(row.requiredQty, 6)}</div>
                      </td>
                      <td style={{ textAlign: "right", padding: 8 }}>
                        <div>{usd(row.actual)}</div>
                        <div style={{ color: "#9ca3af" }}>{num(row.actualQty, 6)}</div>
                      </td>
                      <td style={{ textAlign: "right", padding: 8, color: row.gapUsd < 0 ? "#fca5a5" : "#86efac" }}>
                        <div>{num(row.gapUsd, 2)}</div>
                        <div style={{ color: "#9ca3af" }}>{row.gapQty == null ? "-" : num(row.gapQty, 6)}</div>
                      </td>
                      <td style={{ textAlign: "right", padding: 8 }}>{row.ratio == null ? "-" : `${num(row.ratio * 100, 1)}%`}</td>
                      <td style={{ padding: 8 }}>
                        <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 999, background: badge.bg, color: badge.fg, fontWeight: 600 }}>
                          {badge.text}
                        </span>
                      </td>
                      <td style={{ padding: 8 }}>
                        {isSimBalances ? (
                          <button
                            type="button"
                            disabled={augmentingKey === row.symbol}
                            onClick={async () => {
                              const controlsForMode = assetControls.filter((c) => c.execution_mode === balancesMode);
                              const symbols = Array.from(new Set(controlsForMode.map((c) => c.symbol))).sort();
                              if (symbols.length === 0) {
                                window.alert("No symbols available for SIM wallet adjustment.");
                                return;
                              }

                              const bucket: "cash" | "asset" = row.rowType === "cash" ? "cash" : "asset";
                              const targetSymbol = row.rowType === "cash"
                                ? (() => {
                                    const symbolInput = window.prompt(`Symbol for cash adjustment (${symbols.join(", ")})`, symbols[0]);
                                    if (symbolInput == null) return null;
                                    const picked = symbolInput.trim().toUpperCase();
                                    const matched = symbols.find((s) => s.toUpperCase() === picked);
                                    if (!matched) {
                                      window.alert("Select a valid symbol from the control plane list.");
                                      return null;
                                    }
                                    return matched;
                                  })()
                                : row.symbol;
                              if (!targetSymbol) return;

                              const input = window.prompt(`Set ${targetSymbol} ${bucket} balance to absolute USD amount (positive)`, "100");
                              if (input == null) return;
                              const amount = Number(input);
                              if (!Number.isFinite(amount) || amount <= 0) {
                                window.alert("Enter a positive USD amount.");
                                return;
                              }

                              setAugmentingKey(row.symbol);
                              try {
                                await onAugmentSimWallet({ symbol: targetSymbol, bucket, amount_usd: amount });
                              } catch (err) {
                                window.alert(err instanceof Error ? err.message : "Failed to set sim wallet balance");
                              } finally {
                                setAugmentingKey(null);
                              }
                            }}
                            style={{
                              border: "1px solid #2d3340",
                              background: "transparent",
                              color: "inherit",
                              borderRadius: 4,
                              padding: "3px 8px",
                              cursor: augmentingKey === row.symbol ? "default" : "pointer",
                            }}
                          >
                            {augmentingKey === row.symbol ? "Saving..." : "Set Balance"}
                          </button>
                        ) : (
                          <span style={{ color: "#6b7280" }}>-</span>
                        )}
                      </td>
                    </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          <div style={{ color: "#9ca3af" }}>
            {isSimBalances
              ? "SIM rows show required/actual/gap per asset leg plus an aggregate cash row sourced from the virtual SIM wallet."
              : "LIVE rows show required/actual/gap per asset leg plus an aggregate cash row from exchange cash balances."}
          </div>
          <div style={{ color: "#9ca3af" }}>
            Raw fields: {freeLabel}, {pxLabel}, {valueLabel}.
          </div>
        </div>
      </section>

      <section style={{ border: "1px solid #22262f", borderRadius: 6 }}>
        <div style={{ padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }}>Control Plane</div>
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
                  <td style={{ padding: 8, maxWidth: 360 }}>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => {
                        void openTuningPopover(row);
                      }}
                      style={{
                        padding: "3px 8px",
                        borderRadius: 4,
                        border: "1px solid #2d3340",
                        background: "#2d3340",
                        color: "inherit",
                        cursor: "pointer",
                      }}
                    >
                      Tuning Params
                    </button>
                    <div style={{ marginTop: 4, color: "#9ca3af", fontSize: 11 }}>
                      v{row.tuning_version ?? 0}
                      {row.tuning_source ? ` • ${row.tuning_source}` : ""}
                    </div>
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

      {tuningRow && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 55,
          }}
          onClick={() => setTuningRow(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(1040px, 94vw)",
              maxHeight: "86vh",
              overflow: "hidden",
              background: "#0f131c",
              border: "1px solid #2d3340",
              borderRadius: 8,
              display: "grid",
              gridTemplateRows: "auto 1fr",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", borderBottom: "1px solid #2d3340" }}>
              <strong>Tuning Params — {tuningRow.symbol} ({tuningRow.timeframe})</strong>
              <button type="button" onClick={() => setTuningRow(null)} style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "transparent", color: "inherit", cursor: "pointer" }}>
                Close
              </button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: 12, padding: 12, overflow: "auto" }}>
              <div style={{ display: "grid", gap: 8, alignContent: "start" }}>
                <div style={{ display: "grid", gap: 6, gridTemplateColumns: "repeat(2, minmax(180px, 1fr))" }}>
                  {editableTuningFields.map((field) => (
                    <label key={field} style={{ display: "grid", gap: 4, fontSize: 12 }}>
                      <span style={{ color: "#9ca3af" }}>{field}</span>
                      <input
                        type="number"
                        step="any"
                        value={tuningDraft[field] ?? ""}
                        onChange={(e) => setTuningDraft((prev) => ({ ...prev, [field]: e.target.value }))}
                        style={{ padding: "5px 7px", background: "#0b0f16", color: "inherit", border: "1px solid #2d3340", borderRadius: 4 }}
                      />
                    </label>
                  ))}
                </div>

                <div style={{ display: "grid", gap: 6 }}>
                  <label style={{ display: "grid", gap: 4, fontSize: 12 }}>
                    <span style={{ color: "#9ca3af" }}>Source (example: automated_backtest, manual)</span>
                    <input
                      type="text"
                      value={tuningSource}
                      onChange={(e) => setTuningSource(e.target.value)}
                      style={{ padding: "5px 7px", background: "#0b0f16", color: "inherit", border: "1px solid #2d3340", borderRadius: 4 }}
                    />
                  </label>
                  <label style={{ display: "grid", gap: 4, fontSize: 12 }}>
                    <span style={{ color: "#9ca3af" }}>Updated By</span>
                    <input
                      type="text"
                      value={tuningUpdatedBy}
                      onChange={(e) => setTuningUpdatedBy(e.target.value)}
                      style={{ padding: "5px 7px", background: "#0b0f16", color: "inherit", border: "1px solid #2d3340", borderRadius: 4 }}
                    />
                  </label>
                  <label style={{ display: "grid", gap: 4, fontSize: 12 }}>
                    <span style={{ color: "#9ca3af" }}>Version Note</span>
                    <textarea
                      value={tuningNote}
                      onChange={(e) => setTuningNote(e.target.value)}
                      rows={3}
                      style={{ padding: "6px 8px", background: "#0b0f16", color: "inherit", border: "1px solid #2d3340", borderRadius: 4, resize: "vertical" }}
                    />
                  </label>
                </div>

                <div>
                  <button
                    type="button"
                    disabled={tuningSaving}
                    onClick={() => {
                      void saveTuningFromPopover();
                    }}
                    style={{ padding: "5px 10px", borderRadius: 4, border: "1px solid #2d3340", background: "#2d3340", color: "inherit", cursor: "pointer" }}
                  >
                    {tuningSaving ? "Saving..." : "Save New Version"}
                  </button>
                </div>
              </div>

              <div style={{ borderLeft: "1px solid #1b1f29", paddingLeft: 12, minHeight: 260 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>Version History</div>
                {tuningLoading ? (
                  <div style={{ fontSize: 12 }}>Loading versions...</div>
                ) : tuningVersions.length === 0 ? (
                  <div style={{ fontSize: 12, color: "#9ca3af" }}>No saved tuning versions yet.</div>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: "left", padding: 6 }}>Version</th>
                        <th style={{ textAlign: "left", padding: 6 }}>When</th>
                        <th style={{ textAlign: "left", padding: 6 }}>Source</th>
                        <th style={{ textAlign: "left", padding: 6 }}>Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tuningVersions.map((v) => (
                        <tr key={v.id} style={{ borderTop: "1px solid #1b1f29" }}>
                          <td style={{ padding: 6 }}>
                            v{v.version} {v.is_active ? <span style={{ color: "#85e89d" }}>(active)</span> : null}
                          </td>
                          <td style={{ padding: 6 }}>{new Date(v.created_at).toLocaleString()}</td>
                          <td style={{ padding: 6 }}>{v.source ?? "-"}</td>
                          <td style={{ padding: 6 }}>{v.note ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

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

              {chartStats.dayGridLines.map((line, idx) => (
                <g key={`day-grid-${idx}`}>
                  <line
                    x1={line.x}
                    y1={chartMargins.top}
                    x2={line.x}
                    y2={chartHeight - chartMargins.bottom}
                    stroke="#1f2a3a"
                    strokeWidth={1}
                  />
                  <text x={line.x} y={chartHeight - 8} textAnchor="middle" fontSize={9} fill="#7f8ea3">
                    {line.label}
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
              <span style={{ color: slippageTone(hoverDot.trade.total_slippage_usd) }}>Slip {slippageLabel(hoverDot.trade.entry_slippage_bps != null && hoverDot.trade.exit_slippage_bps != null ? hoverDot.trade.entry_slippage_bps + hoverDot.trade.exit_slippage_bps : null, hoverDot.trade.total_slippage_usd)}</span>
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
                <th style={{ textAlign: "right", padding: 8 }}>Entry Fill</th>
                <th style={{ textAlign: "right", padding: 8 }}>Entry Spot</th>
                <th style={{ textAlign: "right", padding: 8 }}>Entry Slip</th>
                <th style={{ textAlign: "right", padding: 8 }}>Exit Fill</th>
                <th style={{ textAlign: "right", padding: 8 }}>Exit Spot</th>
                <th style={{ textAlign: "right", padding: 8 }}>Exit Slip</th>
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
                <tr><td style={{ padding: 8 }} colSpan={18}>No closed trades.</td></tr>
              ) : (
                filteredClosedTrades.map((row, idx) => {
                  const notionalUsd = row.entry_price * row.qty;
                  const returnUsd = notionalUsd * (row.return_pct / 100);
                  const pnlPositive = row.net_pnl >= 0;
                  const rowBg = idx % 2 === 0 ? "transparent" : "#0d1118";
                  return (
                    <tr key={row.id} style={{ borderTop: "1px solid #1b1f29", background: rowBg }}>
                      <td style={{ padding: 8 }}>{new Date(row.exit_ts).toLocaleString()}</td>
                      <td style={{ padding: 8, fontWeight: 600 }}>{row.symbol}</td>
                      <td style={{ padding: 8 }}>{row.execution_mode === "sim" ? "Sim" : "Real"}</td>
                      <td style={{ padding: 8 }}>{row.timeframe}</td>
                      <td style={{ textAlign: "right", padding: 8 }}>{tradeLengthLabel(row)}</td>
                      <td style={{ padding: 8 }}>{row.trade_side === "short" ? "Short" : "Long"}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{num(row.entry_price, 6)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{row.entry_spot_price != null ? num(row.entry_spot_price, 6) : "-"}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: slippageTone(row.entry_slippage_usd) }}>{slippageLabel(row.entry_slippage_bps, row.entry_slippage_usd)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{num(row.exit_price, 6)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{row.exit_spot_price != null ? num(row.exit_spot_price, 6) : "-"}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: slippageTone(row.exit_slippage_usd) }}>{slippageLabel(row.exit_slippage_bps, row.exit_slippage_usd)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace" }}>{usd(notionalUsd)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: pnlPositive ? "#34d399" : "#f87171", fontWeight: 600 }}>{usd(row.net_pnl)}</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: pnlPositive ? "#34d399" : "#f87171" }}>{num(row.return_pct, 3)}%</td>
                      <td style={{ textAlign: "right", padding: 8, fontFamily: "monospace", color: pnlPositive ? "#34d399" : "#f87171" }}>{usd(returnUsd)}</td>
                      <td style={{ padding: 8 }}>{row.exit_reason}</td>
                      <td style={{ padding: 8 }}>
                        <button
                          type="button"
                          onClick={() => void openTradePreview(row)}
                          style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "#101827", color: "#dbe6f5", cursor: "pointer", fontSize: 11 }}
                        >
                          Quick View
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

      {previewTrade ? (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setPreviewTrade(null)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(8, 11, 18, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 70,
            padding: 14,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(1100px, 95vw)",
              maxHeight: "85vh",
              overflow: "hidden",
              background: "#0f131c",
              border: "1px solid #2d3340",
              borderRadius: 10,
              display: "grid",
              gridTemplateRows: "auto 1fr",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", borderBottom: "1px solid #2d3340", gap: 10 }}>
              <strong>
                Trade Quick View - {previewTrade.symbol} ({previewTrade.timeframe})
              </strong>
              <button type="button" onClick={() => setPreviewTrade(null)} style={{ padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "transparent", color: "inherit", cursor: "pointer" }}>
                Close
              </button>
            </div>
            <div style={{ overflow: "auto", padding: 12 }}>
              {previewLoading ? (
                <div style={{ fontSize: 12 }}>Loading trade preview...</div>
              ) : previewError ? (
                <div style={{ fontSize: 12, color: "#fca5a5" }}>{previewError}</div>
              ) : previewRows.length === 0 ? (
                <div style={{ fontSize: 12 }}>No preview candles.</div>
              ) : (
                (() => {
                  const w = 1020;
                  const h = 360;
                  const m = { left: 54, right: 18, top: 18, bottom: 28 };
                  const iw = w - m.left - m.right;
                  const ih = h - m.top - m.bottom;
                  const lows = previewRows.map((r) => r.low);
                  const highs = previewRows.map((r) => r.high);
                  const overlays = previewRows.flatMap((r) => [r.bb_lower, r.bb_mid, r.bb_upper, r.ema20, r.ema50, r.ema200].filter((v): v is number => typeof v === "number" && Number.isFinite(v)));
                  const minV = Math.min(...lows, ...(overlays.length > 0 ? overlays : lows));
                  const maxV = Math.max(...highs, ...(overlays.length > 0 ? overlays : highs));
                  const span = Math.max(maxV - minV, 1e-9);
                  const pad = span * 0.06;
                  const dMin = minV - pad;
                  const dMax = maxV + pad;
                  const dSpan = Math.max(dMax - dMin, 1e-9);
                  const xStep = previewRows.length > 1 ? iw / (previewRows.length - 1) : iw;
                  const xFor = (i: number) => m.left + i * xStep;
                  const yFor = (v: number) => m.top + ih - ((v - dMin) / dSpan) * ih;

                  const pathFor = (key: "bb_lower" | "bb_mid" | "bb_upper" | "ema20" | "ema50" | "ema200") => {
                    let d = "";
                    previewRows.forEach((row, i) => {
                      const v = row[key];
                      if (typeof v !== "number" || !Number.isFinite(v)) return;
                      d += `${d ? " L" : "M"}${xFor(i)} ${yFor(v)}`;
                    });
                    return d;
                  };

                  const entryMs = parseApiTsMillis(previewTrade.entry_ts);
                  const exitMs = parseApiTsMillis(previewTrade.exit_ts);
                  let entryIdx = 0;
                  let exitIdx = previewRows.length - 1;
                  let bestEntryDist = Number.POSITIVE_INFINITY;
                  let bestExitDist = Number.POSITIVE_INFINITY;
                  previewRows.forEach((row, i) => {
                    const t = parseApiTsMillis(row.ts);
                    const entryDist = Math.abs(t - entryMs);
                    const exitDist = Math.abs(t - exitMs);
                    if (entryDist < bestEntryDist) {
                      bestEntryDist = entryDist;
                      entryIdx = i;
                    }
                    if (exitDist < bestExitDist) {
                      bestExitDist = exitDist;
                      exitIdx = i;
                    }
                  });

                  const beforeBars = entryIdx;
                  const insideBars = Math.max(0, exitIdx - entryIdx + 1);
                  const afterBars = Math.max(0, previewRows.length - 1 - exitIdx);
                  const activeIdx = previewHoverIndex !== null && previewHoverIndex >= 0 && previewHoverIndex < previewRows.length
                    ? previewHoverIndex
                    : null;
                  const activeRow = activeIdx !== null ? previewRows[activeIdx] : null;
                  const activeX = activeIdx !== null ? xFor(activeIdx) : null;

                  return (
                    <>
                      <div style={{ marginBottom: 8, fontSize: 12, color: "#cbd5e1", display: "flex", flexWrap: "wrap", gap: 14 }}>
                        <span>Window Bars: <strong>{previewRows.length}</strong> ({beforeBars} before, {insideBars} in-trade, {afterBars} after)</span>
                        <span>Entry: <strong>{new Date(previewTrade.entry_ts).toLocaleString()}</strong></span>
                        <span>Exit: <strong>{new Date(previewTrade.exit_ts).toLocaleString()}</strong></span>
                        <span>Entry Spot/Fill: <strong>{previewTrade.entry_spot_price != null ? num(previewTrade.entry_spot_price, 6) : "-"} / {num(previewTrade.entry_price, 6)}</strong></span>
                        <span style={{ color: slippageTone(previewTrade.entry_slippage_usd) }}>Entry Slip: <strong>{slippageLabel(previewTrade.entry_slippage_bps, previewTrade.entry_slippage_usd)}</strong></span>
                        <span>Exit Spot/Fill: <strong>{previewTrade.exit_spot_price != null ? num(previewTrade.exit_spot_price, 6) : "-"} / {num(previewTrade.exit_price, 6)}</strong></span>
                        <span style={{ color: slippageTone(previewTrade.exit_slippage_usd) }}>Exit Slip: <strong>{slippageLabel(previewTrade.exit_slippage_bps, previewTrade.exit_slippage_usd)}</strong></span>
                        <span style={{ color: slippageTone(previewTrade.total_slippage_usd) }}>Total Slip Impact: <strong>{previewTrade.total_slippage_usd != null ? usd(previewTrade.total_slippage_usd) : "-"}</strong></span>
                        <span>Reason: <strong>{previewTrade.exit_reason}</strong></span>
                      </div>
                      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: "block", background: "#0b1119", borderRadius: 8, border: "1px solid #1f2937" }}>
                        {[0, 1, 2, 3, 4].map((tick) => {
                          const frac = tick / 4;
                          const y = m.top + frac * ih;
                          const v = dMax - frac * dSpan;
                          return (
                            <g key={`preview-grid-${tick}`}>
                              <line x1={m.left} y1={y} x2={w - m.right} y2={y} stroke="#1f2a3a" strokeWidth={1} />
                              <text x={m.left - 7} y={y + 4} textAnchor="end" fontSize={10} fill="#93a3b8">{num(v, 6)}</text>
                            </g>
                          );
                        })}

                        <line x1={xFor(entryIdx)} y1={m.top} x2={xFor(entryIdx)} y2={h - m.bottom} stroke="#67e8f9" strokeDasharray="4 3" strokeWidth={1.2} />
                        <line x1={xFor(exitIdx)} y1={m.top} x2={xFor(exitIdx)} y2={h - m.bottom} stroke="#fca5a5" strokeDasharray="4 3" strokeWidth={1.2} />

                        {activeX !== null ? (
                          <line x1={activeX} y1={m.top} x2={activeX} y2={h - m.bottom} stroke="#e2e8f0" strokeDasharray="3 3" strokeWidth={1} opacity={0.6} />
                        ) : null}

                        {previewRows.map((row, i) => {
                          const x = xFor(i);
                          const yHigh = yFor(row.high);
                          const yLow = yFor(row.low);
                          const yOpen = yFor(row.open);
                          const yClose = yFor(row.close);
                          const up = row.close >= row.open;
                          const bodyTop = Math.min(yOpen, yClose);
                          const bodyH = Math.max(1, Math.abs(yClose - yOpen));
                          const bodyW = Math.max(2, Math.min(9, xStep * 0.62));
                          return (
                            <g key={`candle-${row.ts}`} onMouseEnter={() => setPreviewHoverIndex(i)} onMouseMove={() => setPreviewHoverIndex(i)}>
                              <line x1={x} y1={yHigh} x2={x} y2={yLow} stroke={up ? "#34d399" : "#f87171"} strokeWidth={1} />
                              <rect x={x - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={up ? "#34d399" : "#f87171"} opacity={0.9} />
                            </g>
                          );
                        })}

                        <path d={pathFor("bb_upper")} fill="none" stroke="#60a5fa" strokeWidth={1.2} opacity={0.85} />
                        <path d={pathFor("bb_mid")} fill="none" stroke="#93c5fd" strokeWidth={1.1} opacity={0.8} />
                        <path d={pathFor("bb_lower")} fill="none" stroke="#60a5fa" strokeWidth={1.2} opacity={0.85} />
                        <path d={pathFor("ema20")} fill="none" stroke="#f59e0b" strokeWidth={1.35} />
                        <path d={pathFor("ema50")} fill="none" stroke="#a78bfa" strokeWidth={1.25} />
                        <path d={pathFor("ema200")} fill="none" stroke="#f43f5e" strokeWidth={1.1} opacity={0.9} />
                      </svg>
                      {activeRow ? (
                        <div style={{ marginTop: 8, padding: "7px 9px", borderRadius: 6, border: "1px solid #334155", background: "#101827", fontSize: 11, color: "#cbd5e1", display: "flex", gap: 12, flexWrap: "wrap" }}>
                          <span>{new Date(activeRow.ts).toLocaleString()}</span>
                          <span>O {num(activeRow.open, 6)}</span>
                          <span>H {num(activeRow.high, 6)}</span>
                          <span>L {num(activeRow.low, 6)}</span>
                          <span>C {num(activeRow.close, 6)}</span>
                          <span>BB U/M/L {num(activeRow.bb_upper, 6)} / {num(activeRow.bb_mid, 6)} / {num(activeRow.bb_lower, 6)}</span>
                          <span>EMA 20/50/200 {num(activeRow.ema20, 6)} / {num(activeRow.ema50, 6)} / {num(activeRow.ema200, 6)}</span>
                        </div>
                      ) : null}
                      <div style={{ marginTop: 8, display: "flex", gap: 14, flexWrap: "wrap", fontSize: 11, color: "#9ca3af" }}>
                        <span><span style={{ color: "#67e8f9" }}>|</span> Entry marker</span>
                        <span><span style={{ color: "#fca5a5" }}>|</span> Exit marker</span>
                        <span><span style={{ color: "#e2e8f0" }}>|</span> Hover marker</span>
                        <span><span style={{ color: "#60a5fa" }}>-</span> Bollinger Bands</span>
                        <span><span style={{ color: "#f59e0b" }}>-</span> EMA20</span>
                        <span><span style={{ color: "#a78bfa" }}>-</span> EMA50</span>
                        <span><span style={{ color: "#f43f5e" }}>-</span> EMA200</span>
                      </div>
                    </>
                  );
                })()
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
