import React, { useMemo } from "react";
import type { AssetControl, ClosedTrade, Gap, IndicatorRow, OpenPosition } from "../api/types";
import CandleChart from "./CandleChart";
import IndicatorPanels from "./IndicatorPanels";
import VolumeProfile from "./VolumeProfile";
import DataHealthPanel from "./DataHealthPanel";
import { buildVolumeProfile } from "../utils/volumeProfile";
import { num } from "../utils/formatting";
import { formatDateTimeWithZone, getClientTimeZone, getClientTimeZoneLabel } from "../utils/time";

type TradeMarker = {
  ts: string;
  kind: "long_opened" | "long_closed" | "short_opened" | "short_closed";
  mode: "sim" | "live";
};

type Props = {
  timeframe: string;
  rows: IndicatorRow[];
  gaps: Gap[];
  overlays: { bbands: boolean; ema20: boolean; ema50: boolean; ema200: boolean };
  panels: { rsi: boolean; atr: boolean; bbWidth: boolean; volumeProfile: boolean };
  openPositions: OpenPosition[];
  closedTrades: ClosedTrade[];
  assetControl?: AssetControl;
  crosshair: IndicatorRow | null;
  setCrosshair: (row: IndicatorRow | null) => void;
  chartDataCap?: {
    capLimit: number;
    totalRows: number;
    shownRows: number;
    omittedRows: number;
    omittedStartTs: string;
    omittedEndTs: string;
    visibleStartTs: string;
    visibleEndTs: string;
  } | null;
};

type EntryConditionState = {
  rsi: boolean | null;
  trend: boolean | null;
  bb: boolean | null;
  momentum: boolean | null;
  volatility: boolean | null;
  gateFlat: boolean;
  gateCooldown: boolean;
  gateCadence: boolean;
  all: boolean | null;
};

type CloseConditionState = {
  rsi: boolean | null;
  trend: boolean | null;
  signal: boolean | null;
  holdGate: boolean | null;
  stopHit: boolean | null;
  takeProfitHit: boolean | null;
  timedExit: boolean | null;
  all: boolean | null;
};

type ThresholdSliderMetric = {
  key: string;
  label: string;
  color: string;
  value: number | null;
  threshold: number | null;
  min: number;
  max: number;
  pass: boolean | null;
  valueText: string;
  thresholdText: string;
};

type ThresholdSlidersProps = {
  title: string;
  metrics: ThresholdSliderMetric[];
  sideEnabled: boolean;
};

type EntryDecisionDiagnostics = {
  evalTs: string | null;
  actionTs: string | null;
  hasOpenPosition: boolean;
  lastExitReason: string | null;
  barsSinceExit: number | null;
  cooldownRequiredBars: number;
  cooldownPass: boolean;
  entriesLastHour: number;
  entriesLastDay: number;
  cadenceHourPass: boolean;
  cadenceDayPass: boolean;
  longAllowed: boolean;
  shortAllowed: boolean;
  longSignal: boolean | null;
  shortSignal: boolean | null;
  expectedAction: "enter_long" | "enter_short" | "hold";
  actualAction: "enter_long" | "enter_short" | "hold";
};

function ThresholdSliders({ title, metrics, sideEnabled }: ThresholdSlidersProps) {
  const sliderHeight = 122;

  const toPct = (value: number, min: number, max: number): number => {
    const span = Math.max(max - min, 1e-9);
    const normalized = (value - min) / span;
    return Math.min(1, Math.max(0, normalized));
  };

  return (
    <div style={{ border: "1px solid #2b3442", borderRadius: 8, background: "#0f1520", padding: "8px 10px", minWidth: 280 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 12, color: "#dbe6f5", fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 10, color: sideEnabled ? "#9ca3af" : "#ef4444" }}>{sideEnabled ? "active" : "inactive"}</div>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        {metrics.map((metric) => {
          const valuePct = metric.value === null ? null : toPct(metric.value, metric.min, metric.max);
          const thresholdPct = metric.threshold === null ? null : toPct(metric.threshold, metric.min, metric.max);
          const statusColor = metric.pass === null ? "#94a3b8" : metric.pass ? "#22c55e" : "#ef4444";
          return (
            <div key={`${title}-${metric.key}`} style={{ width: 86, textAlign: "center", opacity: sideEnabled ? 1 : 0.5 }}>
              <div style={{ fontSize: 10, color: "#cbd5e1", marginBottom: 4 }}>{metric.label}</div>
              <div style={{ height: sliderHeight, position: "relative", margin: "0 auto", width: 16, borderRadius: 10, background: "#101827", border: "1px solid #334155" }}>
                {thresholdPct !== null ? (
                  <div
                    style={{
                      position: "absolute",
                      left: -10,
                      right: -10,
                      bottom: `${thresholdPct * (sliderHeight - 2)}px`,
                      height: 2,
                      background: "#f59e0b",
                    }}
                  />
                ) : null}
                {valuePct !== null ? (
                  <div
                    style={{
                      position: "absolute",
                      left: -3,
                      width: 22,
                      bottom: `${valuePct * (sliderHeight - 2) - 5}px`,
                      height: 10,
                      borderRadius: 6,
                      background: metric.color,
                      boxShadow: `0 0 0 1px ${metric.color}`,
                    }}
                  />
                ) : null}
              </div>
              <div style={{ marginTop: 4, fontSize: 10, color: "#9ca3af" }}>cur {metric.valueText}</div>
              <div style={{ fontSize: 10, color: "#9ca3af" }}>thr {metric.thresholdText}</div>
              <div style={{ marginTop: 2, fontSize: 10, color: statusColor }}>
                {metric.pass === null ? "n/a" : metric.pass ? "pass" : "block"}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 6, fontSize: 10, color: "#93a3b8" }}>
        Yellow line = trigger threshold. Colored handle = current value at cursor/live bar.
      </div>
    </div>
  );
}

function getEmaFastValue(row: IndicatorRow | null | undefined, emaFast: number | undefined): number | null {
  if (!row || emaFast === undefined) {
    return null;
  }
  const value = (row as unknown as Record<string, number | null | undefined>)[`ema${emaFast}`];
  return typeof value === "number" ? value : null;
}

function getEmaValue(row: IndicatorRow | null | undefined, length: number | undefined): number | null {
  if (!row || length === undefined) {
    return null;
  }
  const value = (row as unknown as Record<string, number | null | undefined>)[`ema${length}`];
  return typeof value === "number" ? value : null;
}

function allTrue(values: Array<boolean | null>): boolean | null {
  if (values.some((v) => v === null)) {
    return null;
  }
  return values.every((v) => v === true);
}

function normalizeApiTs(ts: string | null | undefined): string | null {
  if (!ts) {
    return null;
  }
  return /Z$|[+-]\d{2}:\d{2}$/.test(ts) ? ts : `${ts}Z`;
}

function computeBbMetric(
  side: "long" | "short",
  bbMode: string,
  closeValue: number | null,
  bbLowerValue: number | null,
  bbUpperValue: number | null,
  thresholdPct: number | undefined
): { value: number | null; threshold: number | null; pass: boolean | null; valueText: string; thresholdText: string; min: number; max: number } {
  if (bbMode === "off") {
    return {
      value: 0,
      threshold: 0,
      pass: true,
      valueText: "off",
      thresholdText: "off",
      min: -1,
      max: 1,
    };
  }

  if (closeValue === null) {
    return { value: null, threshold: 0, pass: null, valueText: "n/a", thresholdText: "0", min: -1, max: 1 };
  }

  if (bbMode === "touch_revert") {
    if (bbLowerValue === null || bbUpperValue === null) {
      return { value: null, threshold: 0, pass: null, valueText: "n/a", thresholdText: "0", min: -1, max: 1 };
    }
    const dist = side === "long" ? closeValue - bbLowerValue : bbUpperValue - closeValue;
    return {
      value: dist,
      threshold: 0,
      pass: dist <= 0,
      valueText: num(dist, 5),
      thresholdText: "0",
      min: -0.02,
      max: 0.02,
    };
  }

  if (bbLowerValue === null || bbUpperValue === null) {
    return { value: null, threshold: 0, pass: null, valueText: "n/a", thresholdText: "0", min: -1, max: 1 };
  }

  const range = bbUpperValue - bbLowerValue;
  if (range <= 0) {
    return { value: null, threshold: 0, pass: null, valueText: "n/a", thresholdText: "0", min: -1, max: 1 };
  }

  const threshold = thresholdPct ?? 0.8;
  const cutoff = side === "long" ? bbLowerValue + threshold * range : bbUpperValue - threshold * range;
  const dist = side === "long" ? closeValue - cutoff : cutoff - closeValue;

  return {
    value: dist,
    threshold: 0,
    pass: dist <= 0,
    valueText: num(dist, 5),
    thresholdText: "0",
    min: -0.03,
    max: 0.03,
  };
}

export default function ChartLayout({ timeframe, rows, gaps, overlays, panels, openPositions, closedTrades, assetControl, crosshair, setCrosshair, chartDataCap }: Props) {
  const tz = getClientTimeZone();
  const tzLabel = getClientTimeZoneLabel();
  const profile = useMemo(() => buildVolumeProfile(rows), [rows]);
  const row = crosshair ?? rows[rows.length - 1] ?? null;
  const rowIndex = row ? rows.findIndex((r) => r.ts === row.ts) : -1;
  const evalRow = rowIndex > 0 ? rows[rowIndex - 1] : row;
  const tuning = assetControl?.tuning_params ?? {};

  const rsiEntry = typeof tuning.rsi_entry === "number" ? tuning.rsi_entry : undefined;
  const rsiExit = typeof tuning.rsi_exit === "number" ? tuning.rsi_exit : undefined;
  const emaFast = typeof tuning.ema_fast === "number" ? tuning.ema_fast : undefined;
  const maxHoldBars = typeof tuning.max_hold_bars === "number" ? tuning.max_hold_bars : undefined;
  const minHoldSignalBars =
    typeof tuning.min_hold_bars === "number"
      ? tuning.min_hold_bars
      : (typeof tuning.min_hold_bars_before_signal_exit === "number" ? tuning.min_hold_bars_before_signal_exit : undefined);
  const cooldownBarsAfterExit = typeof tuning.cooldown_bars_after_exit === "number" ? tuning.cooldown_bars_after_exit : (timeframe === "1m" ? 10 : 3);
  const cooldownBarsAfterStop = typeof tuning.cooldown_bars_after_stop === "number" ? tuning.cooldown_bars_after_stop : (timeframe === "1m" ? 20 : 5);
  const maxEntriesPerHour = typeof tuning.max_entries_per_hour === "number" ? tuning.max_entries_per_hour : (timeframe === "1m" ? 12 : 3);
  const maxEntriesPerDay = typeof tuning.max_entries_per_day === "number" ? tuning.max_entries_per_day : (timeframe === "1m" ? 120 : 24);
  const minEntryAtrPct = typeof tuning.min_entry_atr_pct === "number" ? tuning.min_entry_atr_pct : 0;
  const bbThreshold = typeof tuning.bb_range_threshold_pct === "number" ? tuning.bb_range_threshold_pct : undefined;
  const bbMode = assetControl?.bb_entry_mode ?? "off";
  const tradeSide = assetControl?.trade_side ?? "long_only";
  const longEnabled = tradeSide !== "short_only";
  const shortEnabled = tradeSide !== "long_only";
  const momentumEnabled = rows.some((r) => typeof r.swing_long_ready === "boolean" || typeof r.swing_short_ready === "boolean");

  const close = evalRow?.close ?? null;
  const bbLower = evalRow?.bb_lower ?? null;
  const bbUpper = evalRow?.bb_upper ?? null;
  const momRoc = evalRow?.mom_roc ?? null;
  const swingLongReady = evalRow?.swing_long_ready ?? null;
  const swingShortReady = evalRow?.swing_short_ready ?? null;

  const emaFastValue =
    evalRow && emaFast !== undefined
      ? (evalRow as unknown as Record<string, number | null | undefined>)[`ema${emaFast}`] ?? null
      : null;

  const timeframeSeconds = useMemo(() => {
    if (timeframe.endsWith("m")) return Math.max(1, Number(timeframe.slice(0, -1))) * 60;
    if (timeframe.endsWith("h")) return Math.max(1, Number(timeframe.slice(0, -1))) * 3600;
    if (timeframe.endsWith("d")) return Math.max(1, Number(timeframe.slice(0, -1))) * 86400;
    return 300;
  }, [timeframe]);

  const parseTsMs = (ts: string): number => Date.parse(/Z$|[+-]\d{2}:\d{2}$/.test(ts) ? ts : `${ts}Z`);

  const tradeWindows = useMemo(
    () =>
      closedTrades
        .map((t) => ({
          entryMs: parseTsMs(t.entry_ts),
          exitMs: parseTsMs(t.exit_ts),
          exitReason: t.exit_reason,
        }))
        .filter((w) => Number.isFinite(w.entryMs) && Number.isFinite(w.exitMs))
        .sort((a, b) => a.entryMs - b.entryMs),
    [closedTrades]
  );

  const openWindows = useMemo(
    () =>
      openPositions
        .map((p) => ({ entryMs: parseTsMs(p.entry_ts) }))
        .filter((w) => Number.isFinite(w.entryMs)),
    [openPositions]
  );

  const evaluateEntryState = (prevRow: IndicatorRow | null | undefined, side: "long" | "short"): EntryConditionState => {
    if (!prevRow) {
      return { rsi: null, trend: null, bb: null, momentum: null, volatility: null, gateFlat: false, gateCooldown: false, gateCadence: false, all: null };
    }
    const closeValue = prevRow.close ?? null;
    const emaValue = getEmaFastValue(prevRow, emaFast);
    const atrValue = prevRow.atr ?? null;

    const rsiPass =
      prevRow.rsi !== undefined && prevRow.rsi !== null
        ? side === "long"
          ? (rsiEntry !== undefined ? prevRow.rsi <= rsiEntry : null)
          : (rsiExit !== undefined ? prevRow.rsi >= rsiExit : null)
        : null;

    const trendPass =
      closeValue !== null && emaValue !== null
        ? side === "long"
          ? closeValue > emaValue
          : closeValue < emaValue
        : null;

    const bbMetric = computeBbMetric(side, bbMode, closeValue, prevRow.bb_lower ?? null, prevRow.bb_upper ?? null, bbThreshold);
    const bbPass = bbMetric.pass;

    const momentumPass = momentumEnabled
      ? side === "long"
        ? (prevRow.swing_long_ready ?? null)
        : (prevRow.swing_short_ready ?? null)
      : true;

    const volatilityPass =
      minEntryAtrPct > 0
        ? (atrValue !== null && closeValue !== null && closeValue > 0 ? (atrValue / closeValue) * 100 >= minEntryAtrPct : null)
        : true;

    const evalMs = parseTsMs(prevRow.ts);
    const gateFlatClosed = !tradeWindows.some((w) => evalMs >= w.entryMs && evalMs <= w.exitMs);
    const gateFlatOpen = !openWindows.some((w) => evalMs >= w.entryMs);
    const gateFlat = gateFlatClosed && gateFlatOpen;

    const lastExit = tradeWindows.filter((w) => w.exitMs <= evalMs).sort((a, b) => b.exitMs - a.exitMs)[0];
    let gateCooldown = true;
    if (lastExit) {
      const barsSinceExit = Math.floor((evalMs - lastExit.exitMs) / timeframeSeconds);
      const required = lastExit.exitReason === "stop" ? cooldownBarsAfterStop : cooldownBarsAfterExit;
      gateCooldown = barsSinceExit >= required;
    }

    const entriesLastHour = tradeWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 3600_000).length
      + openWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 3600_000).length;
    const entriesLastDay = tradeWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 86_400_000).length
      + openWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 86_400_000).length;
    const gateCadence = entriesLastHour < maxEntriesPerHour && entriesLastDay < maxEntriesPerDay;

    const all = allTrue([rsiPass, trendPass, bbPass, momentumPass, volatilityPass, gateFlat, gateCooldown, gateCadence]);
    return { rsi: rsiPass, trend: trendPass, bb: bbPass, momentum: momentumPass, volatility: volatilityPass, gateFlat, gateCooldown, gateCadence, all };
  };

  const currentLong = evaluateEntryState(evalRow, "long");
  const currentShort = evaluateEntryState(evalRow, "short");

  const activeLongPosition = useMemo(
    () => openPositions.filter((p) => p.trade_side === "long").sort((a, b) => Date.parse(b.entry_ts) - Date.parse(a.entry_ts))[0],
    [openPositions]
  );
  const activeShortPosition = useMemo(
    () => openPositions.filter((p) => p.trade_side === "short").sort((a, b) => Date.parse(b.entry_ts) - Date.parse(a.entry_ts))[0],
    [openPositions]
  );

  const evaluateCloseState = (side: "long" | "short"): CloseConditionState => {
    const position = side === "long" ? activeLongPosition : activeShortPosition;
    if (!evalRow) {
      return {
        rsi: null,
        trend: null,
        signal: null,
        holdGate: null,
        stopHit: null,
        takeProfitHit: null,
        timedExit: null,
        all: null,
      };
    }

    const rsiValue = evalRow.rsi ?? null;
    const closeValue = evalRow.close ?? null;
    const emaValue = getEmaFastValue(evalRow, emaFast);

    const rsiPass =
      rsiValue !== null
        ? side === "long"
          ? (rsiExit !== undefined ? rsiValue >= rsiExit : null)
          : (rsiEntry !== undefined ? rsiValue <= rsiEntry : null)
        : null;

    const trendPass =
      closeValue !== null && emaValue !== null
        ? side === "long"
          ? closeValue < emaValue
          : closeValue > emaValue
        : null;

    const signal =
      rsiPass === null && trendPass === null
        ? null
        : Boolean(rsiPass === true || trendPass === true);

    if (!position) {
      return {
        rsi: rsiPass,
        trend: trendPass,
        signal,
        holdGate: null,
        stopHit: null,
        takeProfitHit: null,
        timedExit: null,
        all: null,
      };
    }

    const holdNext = Number(position.hold_bars) + 1;
    const holdThreshold = Math.max(0, minHoldSignalBars ?? 0);
    const holdGate = holdNext >= holdThreshold;

    const currentBar = row;
    const stopHit =
      currentBar && position.stop_price !== null && position.stop_price !== undefined
        ? side === "long"
          ? (currentBar.low ?? Number.POSITIVE_INFINITY) <= position.stop_price
          : (currentBar.high ?? Number.NEGATIVE_INFINITY) >= position.stop_price
        : null;

    const takeProfitHit =
      currentBar && position.take_profit_price !== null && position.take_profit_price !== undefined
        ? side === "long"
          ? (currentBar.high ?? Number.NEGATIVE_INFINITY) >= position.take_profit_price
          : (currentBar.low ?? Number.POSITIVE_INFINITY) <= position.take_profit_price
        : null;

    const timedExit = maxHoldBars !== undefined ? holdNext >= maxHoldBars : null;
    const signalActive = signal !== null ? holdGate && signal : null;

    const all =
      stopHit === null && takeProfitHit === null && timedExit === null && signalActive === null
        ? null
        : Boolean(stopHit === true || takeProfitHit === true || timedExit === true || signalActive === true);

    return {
      rsi: rsiPass,
      trend: trendPass,
      signal,
      holdGate,
      stopHit,
      takeProfitHit,
      timedExit,
      all,
    };
  };

  const currentCloseLong = evaluateCloseState("long");
  const currentCloseShort = evaluateCloseState("short");

  const longMetrics = useMemo<ThresholdSliderMetric[]>(() => {
    const rsiValue = evalRow?.rsi ?? null;
    const trendValue = close !== null && emaFastValue !== null && emaFastValue !== 0 ? ((close - emaFastValue) / emaFastValue) * 100 : null;
    const bbMetric = computeBbMetric("long", bbMode, close, bbLower, bbUpper, bbThreshold);
    const atrPctValue = close !== null && evalRow?.atr !== null && evalRow?.atr !== undefined && close > 0
      ? (evalRow.atr / close) * 100
      : null;
    return [
      {
        key: "rsi",
        label: "RSI",
        color: "#38bdf8",
        value: rsiValue,
        threshold: rsiEntry ?? null,
        min: 0,
        max: 100,
        pass: currentLong.rsi,
        valueText: num(rsiValue, 2),
        thresholdText: num(rsiEntry, 2),
      },
      {
        key: "trend",
        label: "Trend %",
        color: "#f59e0b",
        value: trendValue,
        threshold: 0,
        min: -1.5,
        max: 1.5,
        pass: currentLong.trend,
        valueText: `${num(trendValue, 3)}%`,
        thresholdText: "0.000%",
      },
      {
        key: "bb",
        label: "BB Dist",
        color: "#a78bfa",
        value: bbMetric.value,
        threshold: bbMetric.threshold,
        min: bbMetric.min,
        max: bbMetric.max,
        pass: currentLong.bb,
        valueText: bbMetric.valueText,
        thresholdText: bbMetric.thresholdText,
      },
      {
        key: "momentum",
        label: "Momentum",
        color: "#34d399",
        value: momentumEnabled ? (swingLongReady ? 1 : 0) : 1,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentLong.momentum,
        valueText: momentumEnabled ? String(Boolean(swingLongReady)) : "off",
        thresholdText: "true",
      },
      {
        key: "volatility",
        label: "ATR %",
        color: "#f472b6",
        value: atrPctValue,
        threshold: minEntryAtrPct > 0 ? minEntryAtrPct : 0,
        min: 0,
        max: 0.4,
        pass: currentLong.volatility,
        valueText: `${num(atrPctValue, 4)}%`,
        thresholdText: minEntryAtrPct > 0 ? `${num(minEntryAtrPct, 4)}%` : "off",
      },
      {
        key: "gate",
        label: "Gate",
        color: "#f97316",
        value: currentLong.gateFlat && currentLong.gateCooldown && currentLong.gateCadence ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentLong.gateFlat && currentLong.gateCooldown && currentLong.gateCadence,
        valueText: `F:${currentLong.gateFlat ? 1 : 0} C:${currentLong.gateCooldown ? 1 : 0} R:${currentLong.gateCadence ? 1 : 0}`,
        thresholdText: "all=1",
      },
      {
        key: "all",
        label: "Entry",
        color: "#22c55e",
        value: currentLong.all === null ? null : currentLong.all ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentLong.all,
        valueText: currentLong.all === null ? "n/a" : String(currentLong.all),
        thresholdText: "true",
      },
    ];
  }, [evalRow, close, emaFastValue, bbMode, bbLower, bbUpper, bbThreshold, rsiEntry, currentLong.rsi, currentLong.trend, currentLong.bb, currentLong.momentum, currentLong.volatility, currentLong.gateFlat, currentLong.gateCooldown, currentLong.gateCadence, currentLong.all, momentumEnabled, swingLongReady, minEntryAtrPct]);

  const shortMetrics = useMemo<ThresholdSliderMetric[]>(() => {
    const rsiValue = evalRow?.rsi ?? null;
    const trendValue = close !== null && emaFastValue !== null && emaFastValue !== 0 ? ((close - emaFastValue) / emaFastValue) * 100 : null;
    const bbMetric = computeBbMetric("short", bbMode, close, bbLower, bbUpper, bbThreshold);
    const atrPctValue = close !== null && evalRow?.atr !== null && evalRow?.atr !== undefined && close > 0
      ? (evalRow.atr / close) * 100
      : null;
    return [
      {
        key: "rsi",
        label: "RSI",
        color: "#38bdf8",
        value: rsiValue,
        threshold: rsiExit ?? null,
        min: 0,
        max: 100,
        pass: currentShort.rsi,
        valueText: num(rsiValue, 2),
        thresholdText: num(rsiExit, 2),
      },
      {
        key: "trend",
        label: "Trend %",
        color: "#f59e0b",
        value: trendValue,
        threshold: 0,
        min: -1.5,
        max: 1.5,
        pass: currentShort.trend,
        valueText: `${num(trendValue, 3)}%`,
        thresholdText: "0.000%",
      },
      {
        key: "bb",
        label: "BB Dist",
        color: "#a78bfa",
        value: bbMetric.value,
        threshold: bbMetric.threshold,
        min: bbMetric.min,
        max: bbMetric.max,
        pass: currentShort.bb,
        valueText: bbMetric.valueText,
        thresholdText: bbMetric.thresholdText,
      },
      {
        key: "momentum",
        label: "Momentum",
        color: "#34d399",
        value: momentumEnabled ? (swingShortReady ? 1 : 0) : 1,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentShort.momentum,
        valueText: momentumEnabled ? String(Boolean(swingShortReady)) : "off",
        thresholdText: "true",
      },
      {
        key: "volatility",
        label: "ATR %",
        color: "#f472b6",
        value: atrPctValue,
        threshold: minEntryAtrPct > 0 ? minEntryAtrPct : 0,
        min: 0,
        max: 0.4,
        pass: currentShort.volatility,
        valueText: `${num(atrPctValue, 4)}%`,
        thresholdText: minEntryAtrPct > 0 ? `${num(minEntryAtrPct, 4)}%` : "off",
      },
      {
        key: "gate",
        label: "Gate",
        color: "#f97316",
        value: currentShort.gateFlat && currentShort.gateCooldown && currentShort.gateCadence ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentShort.gateFlat && currentShort.gateCooldown && currentShort.gateCadence,
        valueText: `F:${currentShort.gateFlat ? 1 : 0} C:${currentShort.gateCooldown ? 1 : 0} R:${currentShort.gateCadence ? 1 : 0}`,
        thresholdText: "all=1",
      },
      {
        key: "all",
        label: "Entry",
        color: "#ef4444",
        value: currentShort.all === null ? null : currentShort.all ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentShort.all,
        valueText: currentShort.all === null ? "n/a" : String(currentShort.all),
        thresholdText: "true",
      },
    ];
  }, [evalRow, close, emaFastValue, bbMode, bbLower, bbUpper, bbThreshold, rsiExit, currentShort.rsi, currentShort.trend, currentShort.bb, currentShort.momentum, currentShort.volatility, currentShort.gateFlat, currentShort.gateCooldown, currentShort.gateCadence, currentShort.all, momentumEnabled, swingShortReady, minEntryAtrPct]);

  const closeLongMetrics = useMemo<ThresholdSliderMetric[]>(() => {
    const rsiValue = evalRow?.rsi ?? null;
    const trendValue = close !== null && emaFastValue !== null && emaFastValue !== 0 ? ((close - emaFastValue) / emaFastValue) * 100 : null;
    const holdNext = activeLongPosition ? Number(activeLongPosition.hold_bars) + 1 : null;
    const minHold = Math.max(0, minHoldSignalBars ?? 0);
    return [
      {
        key: "rsi_exit",
        label: "RSI Exit",
        color: "#38bdf8",
        value: rsiValue,
        threshold: rsiExit ?? null,
        min: 0,
        max: 100,
        pass: currentCloseLong.rsi,
        valueText: num(rsiValue, 2),
        thresholdText: num(rsiExit, 2),
      },
      {
        key: "trend_exit",
        label: "Trend %",
        color: "#f59e0b",
        value: trendValue,
        threshold: 0,
        min: -1.5,
        max: 1.5,
        pass: currentCloseLong.trend,
        valueText: `${num(trendValue, 3)}%`,
        thresholdText: "< 0",
      },
      {
        key: "signal",
        label: "Signal",
        color: "#60a5fa",
        value: currentCloseLong.signal === null ? null : currentCloseLong.signal ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentCloseLong.signal,
        valueText: currentCloseLong.signal === null ? "n/a" : String(currentCloseLong.signal),
        thresholdText: "true",
      },
      {
        key: "hold_gate",
        label: "Hold Gate",
        color: "#34d399",
        value: holdNext,
        threshold: minHold,
        min: 0,
        max: Math.max(minHold + 5, (maxHoldBars ?? minHold) + 2, 10),
        pass: currentCloseLong.holdGate,
        valueText: holdNext === null ? "n/a" : String(holdNext),
        thresholdText: String(minHold),
      },
      {
        key: "stop_tp_timed",
        label: "Hard Exits",
        color: "#f97316",
        value:
          currentCloseLong.stopHit === true || currentCloseLong.takeProfitHit === true || currentCloseLong.timedExit === true
            ? 1
            : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass:
          currentCloseLong.stopHit === null && currentCloseLong.takeProfitHit === null && currentCloseLong.timedExit === null
            ? null
            : Boolean(currentCloseLong.stopHit || currentCloseLong.takeProfitHit || currentCloseLong.timedExit),
        valueText: `S:${String(currentCloseLong.stopHit)} TP:${String(currentCloseLong.takeProfitHit)} T:${String(currentCloseLong.timedExit)}`,
        thresholdText: "any=true",
      },
      {
        key: "exit",
        label: "Exit",
        color: "#22c55e",
        value: currentCloseLong.all === null ? null : currentCloseLong.all ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentCloseLong.all,
        valueText: currentCloseLong.all === null ? "n/a" : String(currentCloseLong.all),
        thresholdText: "true",
      },
    ];
  }, [evalRow, close, emaFastValue, rsiExit, currentCloseLong.rsi, currentCloseLong.trend, currentCloseLong.signal, currentCloseLong.holdGate, currentCloseLong.stopHit, currentCloseLong.takeProfitHit, currentCloseLong.timedExit, currentCloseLong.all, activeLongPosition, minHoldSignalBars, maxHoldBars]);

  const closeShortMetrics = useMemo<ThresholdSliderMetric[]>(() => {
    const rsiValue = evalRow?.rsi ?? null;
    const trendValue = close !== null && emaFastValue !== null && emaFastValue !== 0 ? ((close - emaFastValue) / emaFastValue) * 100 : null;
    const holdNext = activeShortPosition ? Number(activeShortPosition.hold_bars) + 1 : null;
    const minHold = Math.max(0, minHoldSignalBars ?? 0);
    return [
      {
        key: "rsi_exit",
        label: "RSI Exit",
        color: "#38bdf8",
        value: rsiValue,
        threshold: rsiEntry ?? null,
        min: 0,
        max: 100,
        pass: currentCloseShort.rsi,
        valueText: num(rsiValue, 2),
        thresholdText: num(rsiEntry, 2),
      },
      {
        key: "trend_exit",
        label: "Trend %",
        color: "#f59e0b",
        value: trendValue,
        threshold: 0,
        min: -1.5,
        max: 1.5,
        pass: currentCloseShort.trend,
        valueText: `${num(trendValue, 3)}%`,
        thresholdText: "> 0",
      },
      {
        key: "signal",
        label: "Signal",
        color: "#60a5fa",
        value: currentCloseShort.signal === null ? null : currentCloseShort.signal ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentCloseShort.signal,
        valueText: currentCloseShort.signal === null ? "n/a" : String(currentCloseShort.signal),
        thresholdText: "true",
      },
      {
        key: "hold_gate",
        label: "Hold Gate",
        color: "#34d399",
        value: holdNext,
        threshold: minHold,
        min: 0,
        max: Math.max(minHold + 5, (maxHoldBars ?? minHold) + 2, 10),
        pass: currentCloseShort.holdGate,
        valueText: holdNext === null ? "n/a" : String(holdNext),
        thresholdText: String(minHold),
      },
      {
        key: "stop_tp_timed",
        label: "Hard Exits",
        color: "#f97316",
        value:
          currentCloseShort.stopHit === true || currentCloseShort.takeProfitHit === true || currentCloseShort.timedExit === true
            ? 1
            : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass:
          currentCloseShort.stopHit === null && currentCloseShort.takeProfitHit === null && currentCloseShort.timedExit === null
            ? null
            : Boolean(currentCloseShort.stopHit || currentCloseShort.takeProfitHit || currentCloseShort.timedExit),
        valueText: `S:${String(currentCloseShort.stopHit)} TP:${String(currentCloseShort.takeProfitHit)} T:${String(currentCloseShort.timedExit)}`,
        thresholdText: "any=true",
      },
      {
        key: "exit",
        label: "Exit",
        color: "#ef4444",
        value: currentCloseShort.all === null ? null : currentCloseShort.all ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: currentCloseShort.all,
        valueText: currentCloseShort.all === null ? "n/a" : String(currentCloseShort.all),
        thresholdText: "true",
      },
    ];
  }, [evalRow, close, emaFastValue, rsiEntry, currentCloseShort.rsi, currentCloseShort.trend, currentCloseShort.signal, currentCloseShort.holdGate, currentCloseShort.stopHit, currentCloseShort.takeProfitHit, currentCloseShort.timedExit, currentCloseShort.all, activeShortPosition, minHoldSignalBars, maxHoldBars]);

  const simpleMechanism = useMemo(() => {
    if ((timeframe !== "1m" && timeframe !== "5m") || rowIndex < 2 || !evalRow) {
      return null;
    }
    const prevEval = rows[rowIndex - 2];
    if (!prevEval) {
      return null;
    }

    const bbMid = evalRow.bb_mid ?? null;
    const bbLowerV = evalRow.bb_lower ?? null;
    const bbUpperV = evalRow.bb_upper ?? null;
    const halfWidth = bbMid !== null && bbLowerV !== null && bbUpperV !== null ? (bbUpperV - bbLowerV) * 0.5 : null;
    const localBbDeviation = close !== null && bbMid !== null && halfWidth !== null && halfWidth > 0 ? (close - bbMid) / halfWidth : null;
    const serverBbDeviation = typeof evalRow.bb_deviation === "number" ? evalRow.bb_deviation : null;

    const tunedEmaFast = typeof tuning.ema_fast === "number" ? tuning.ema_fast : undefined;
    const tunedEmaSlow = typeof tuning.ema_slow === "number" ? tuning.ema_slow : undefined;
    const tunedSlopeLookback = typeof tuning.slope_lookback_bars === "number" ? tuning.slope_lookback_bars : 3;
    const tunedFlattenFactor = typeof tuning.slope_flatten_factor === "number" ? tuning.slope_flatten_factor : 0.82;
    const tunedEntryDev = typeof tuning.bb_entry_deviation === "number" ? tuning.bb_entry_deviation : 1.05;
    const tunedExitDev = typeof tuning.bb_exit_deviation === "number" ? tuning.bb_exit_deviation : 0.15;
    const serverEntryDev = typeof evalRow.entry_deviation === "number" ? evalRow.entry_deviation : null;

    const emaFastNow = getEmaValue(evalRow, tunedEmaFast);
    const emaFastPrev = getEmaValue(prevEval, tunedEmaFast);
    const emaSlowNow = getEmaValue(evalRow, tunedEmaSlow);
    const localSlopeNow = emaFastNow !== null && emaFastPrev !== null ? emaFastNow - emaFastPrev : null;
    const serverSlopeNow = typeof evalRow.slope_now === "number" ? evalRow.slope_now : null;
    const slopeLookback =
      rowIndex >= tunedSlopeLookback + 1 && emaFastNow !== null
        ? (() => {
            const lookbackVal = getEmaValue(rows[rowIndex - (tunedSlopeLookback + 1)], tunedEmaFast);
            return lookbackVal !== null ? (emaFastNow - lookbackVal) / tunedSlopeLookback : null;
          })()
      : null;
    const serverSlopeLookback = typeof evalRow.slope_lookback === "number" ? evalRow.slope_lookback : null;
    const localFlattenRatio = localSlopeNow !== null && slopeLookback !== null ? Math.abs(localSlopeNow) / Math.max(Math.abs(slopeLookback), 1e-9) : null;
    const serverFlattenRatio = typeof evalRow.flatten_ratio === "number" ? evalRow.flatten_ratio : null;

    const bbDeviation = serverBbDeviation ?? localBbDeviation;
    const slopeNow = serverSlopeNow ?? localSlopeNow;
    const effectiveSlopeLookback = serverSlopeLookback ?? slopeLookback;
    const flattenRatio = serverFlattenRatio ?? localFlattenRatio;

    const localLongRounding = slopeNow !== null && effectiveSlopeLookback !== null && flattenRatio !== null
      ? slopeNow > effectiveSlopeLookback && slopeNow < 0 && flattenRatio <= tunedFlattenFactor
      : null;
    const localShortRounding = slopeNow !== null && effectiveSlopeLookback !== null && flattenRatio !== null
      ? slopeNow < effectiveSlopeLookback && slopeNow > 0 && flattenRatio <= tunedFlattenFactor
      : null;
    const longRounding = typeof evalRow.long_rounding === "boolean" ? evalRow.long_rounding : localLongRounding;
    const shortRounding = typeof evalRow.short_rounding === "boolean" ? evalRow.short_rounding : localShortRounding;

    const localLongEntry = bbDeviation !== null && emaFastNow !== null && emaSlowNow !== null && close !== null && longRounding !== null
      ? bbDeviation <= -tunedEntryDev && emaFastNow <= emaSlowNow && close <= emaFastNow && longRounding
      : null;
    const localShortEntry = bbDeviation !== null && emaFastNow !== null && emaSlowNow !== null && close !== null && shortRounding !== null
      ? bbDeviation >= tunedEntryDev && emaFastNow >= emaSlowNow && close >= emaFastNow && shortRounding
      : null;
    const longEntry = typeof evalRow.long_entry_signal === "boolean" ? evalRow.long_entry_signal : localLongEntry;
    const shortEntry = typeof evalRow.short_entry_signal === "boolean" ? evalRow.short_entry_signal : localShortEntry;

    const longExitSignal = bbDeviation !== null && emaFastNow !== null && close !== null && slopeNow !== null
      ? bbDeviation >= -tunedExitDev || (close >= emaFastNow && slopeNow >= 0)
      : null;
    const shortExitSignal = bbDeviation !== null && emaFastNow !== null && close !== null && slopeNow !== null
      ? bbDeviation <= tunedExitDev || (close <= emaFastNow && slopeNow <= 0)
      : null;

    return {
      bbDeviation,
      slopeNow,
      slopeLookback: effectiveSlopeLookback,
      flattenRatio,
      longRounding,
      shortRounding,
      longEntry,
      shortEntry,
      longExitSignal,
      shortExitSignal,
      entryDeviation: serverEntryDev ?? tunedEntryDev,
      exitDeviation: tunedExitDev,
      flattenFactor: tunedFlattenFactor,
    };
  }, [timeframe, rowIndex, evalRow, rows, close, tuning]);

  const entryDiagnostics = useMemo<EntryDecisionDiagnostics | null>(() => {
    if ((timeframe !== "1m" && timeframe !== "5m") || !evalRow || !row || !simpleMechanism) {
      return null;
    }

    const evalMs = parseTsMs(evalRow.ts);
    const openPositionAtEval =
      tradeWindows.some((w) => evalMs >= w.entryMs && evalMs <= w.exitMs) ||
      openWindows.some((w) => evalMs >= w.entryMs);

    const lastExit = tradeWindows
      .filter((w) => w.exitMs <= evalMs)
      .sort((a, b) => b.exitMs - a.exitMs)[0];

    const barsSinceExit = lastExit ? Math.floor((evalMs - lastExit.exitMs) / timeframeSeconds) : null;
    const cooldownRequiredBars = lastExit
      ? (lastExit.exitReason === "stop" ? cooldownBarsAfterStop : cooldownBarsAfterExit)
      : 0;
    const cooldownPass = barsSinceExit === null ? true : barsSinceExit >= cooldownRequiredBars;

    const entriesLastHour =
      tradeWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 3_600_000).length +
      openWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 3_600_000).length;
    const entriesLastDay =
      tradeWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 86_400_000).length +
      openWindows.filter((w) => w.entryMs <= evalMs && w.entryMs > evalMs - 86_400_000).length;

    const cadenceHourPass = entriesLastHour < maxEntriesPerHour;
    const cadenceDayPass = entriesLastDay < maxEntriesPerDay;

    const longAllowed = tradeSide !== "short_only";
    const shortAllowed = tradeSide !== "long_only";
    const longSignal = longAllowed ? simpleMechanism.longEntry : null;
    const shortSignal = shortAllowed ? simpleMechanism.shortEntry : null;

    let expectedAction: "enter_long" | "enter_short" | "hold" = "hold";
    if (!openPositionAtEval && cooldownPass && cadenceHourPass && cadenceDayPass) {
      if (longSignal === true) {
        expectedAction = "enter_long";
      } else if (shortSignal === true) {
        expectedAction = "enter_short";
      }
    }

    const actionTs = normalizeApiTs(row.ts);
    const actualAction = closedTrades.some((t) => normalizeApiTs(t.entry_ts) === actionTs)
      ? (closedTrades.find((t) => normalizeApiTs(t.entry_ts) === actionTs)?.trade_side === "short" ? "enter_short" : "enter_long")
      : (openPositions.some((p) => normalizeApiTs(p.entry_ts) === actionTs)
          ? (openPositions.find((p) => normalizeApiTs(p.entry_ts) === actionTs)?.trade_side === "short" ? "enter_short" : "enter_long")
          : "hold");

    return {
      evalTs: evalRow.ts,
      actionTs: row.ts,
      hasOpenPosition: openPositionAtEval,
      lastExitReason: lastExit?.exitReason ?? null,
      barsSinceExit,
      cooldownRequiredBars,
      cooldownPass,
      entriesLastHour,
      entriesLastDay,
      cadenceHourPass,
      cadenceDayPass,
      longAllowed,
      shortAllowed,
      longSignal,
      shortSignal,
      expectedAction,
      actualAction,
    };
  }, [
    timeframe,
    evalRow,
    row,
    simpleMechanism,
    tradeWindows,
    openWindows,
    timeframeSeconds,
    cooldownBarsAfterExit,
    cooldownBarsAfterStop,
    maxEntriesPerHour,
    maxEntriesPerDay,
    tradeSide,
    closedTrades,
    openPositions,
  ]);

  const entryLongSimpleMetrics = useMemo<ThresholdSliderMetric[] | null>(() => {
    if (!simpleMechanism || !entryDiagnostics) {
      return null;
    }
    const longBbPass =
      simpleMechanism.bbDeviation === null || simpleMechanism.entryDeviation === null
        ? null
        : simpleMechanism.bbDeviation <= -simpleMechanism.entryDeviation;
    return [
      {
        key: "bb_dev",
        label: "BB dev",
        color: "#a78bfa",
        value: simpleMechanism.bbDeviation,
        threshold: -(simpleMechanism.entryDeviation ?? 0),
        min: -2.2,
        max: 2.2,
        pass: longBbPass,
        valueText: num(simpleMechanism.bbDeviation, 3),
        thresholdText: num(-(simpleMechanism.entryDeviation ?? 0), 3),
      },
      {
        key: "round",
        label: "Rounding",
        color: "#34d399",
        value: simpleMechanism.longRounding === null ? null : simpleMechanism.longRounding ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: simpleMechanism.longRounding,
        valueText: String(simpleMechanism.longRounding),
        thresholdText: "true",
      },
      {
        key: "flat_gate",
        label: "Flat",
        color: "#f97316",
        value: entryDiagnostics.hasOpenPosition ? 0 : 1,
        threshold: 1,
        min: 0,
        max: 1,
        pass: !entryDiagnostics.hasOpenPosition,
        valueText: entryDiagnostics.hasOpenPosition ? "position_open" : "flat",
        thresholdText: "flat",
      },
      {
        key: "cooldown_gate",
        label: "Cooldown",
        color: "#f59e0b",
        value: entryDiagnostics.barsSinceExit,
        threshold: entryDiagnostics.cooldownRequiredBars,
        min: 0,
        max: Math.max(entryDiagnostics.cooldownRequiredBars + 2, 10),
        pass: entryDiagnostics.cooldownPass,
        valueText: entryDiagnostics.barsSinceExit === null ? "n/a" : String(entryDiagnostics.barsSinceExit),
        thresholdText: String(entryDiagnostics.cooldownRequiredBars),
      },
      {
        key: "cadence_gate",
        label: "Cadence",
        color: "#60a5fa",
        value: entryDiagnostics.cadenceHourPass && entryDiagnostics.cadenceDayPass ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: entryDiagnostics.cadenceHourPass && entryDiagnostics.cadenceDayPass,
        valueText: `H:${entryDiagnostics.entriesLastHour}/${maxEntriesPerHour} D:${entryDiagnostics.entriesLastDay}/${maxEntriesPerDay}`,
        thresholdText: "under caps",
      },
      {
        key: "expected",
        label: "Expected",
        color: "#22c55e",
        value: entryDiagnostics.expectedAction === "enter_long" ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: entryDiagnostics.expectedAction === "enter_long",
        valueText: entryDiagnostics.expectedAction,
        thresholdText: "enter_long",
      },
      {
        key: "actual",
        label: "Actual",
        color: "#eab308",
        value: entryDiagnostics.actualAction === "enter_long" ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: entryDiagnostics.actualAction === "enter_long",
        valueText: entryDiagnostics.actualAction,
        thresholdText: "enter_long",
      },
    ];
  }, [simpleMechanism, entryDiagnostics, maxEntriesPerHour, maxEntriesPerDay]);

  const entryShortSimpleMetrics = useMemo<ThresholdSliderMetric[] | null>(() => {
    if (!simpleMechanism || !entryDiagnostics) {
      return null;
    }
    const shortBbPass =
      simpleMechanism.bbDeviation === null || simpleMechanism.entryDeviation === null
        ? null
        : simpleMechanism.bbDeviation >= simpleMechanism.entryDeviation;
    return [
      {
        key: "bb_dev",
        label: "BB dev",
        color: "#a78bfa",
        value: simpleMechanism.bbDeviation,
        threshold: simpleMechanism.entryDeviation ?? 0,
        min: -2.2,
        max: 2.2,
        pass: shortBbPass,
        valueText: num(simpleMechanism.bbDeviation, 3),
        thresholdText: num(simpleMechanism.entryDeviation ?? 0, 3),
      },
      {
        key: "round",
        label: "Rounding",
        color: "#34d399",
        value: simpleMechanism.shortRounding === null ? null : simpleMechanism.shortRounding ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: simpleMechanism.shortRounding,
        valueText: String(simpleMechanism.shortRounding),
        thresholdText: "true",
      },
      {
        key: "flat_gate",
        label: "Flat",
        color: "#f97316",
        value: entryDiagnostics.hasOpenPosition ? 0 : 1,
        threshold: 1,
        min: 0,
        max: 1,
        pass: !entryDiagnostics.hasOpenPosition,
        valueText: entryDiagnostics.hasOpenPosition ? "position_open" : "flat",
        thresholdText: "flat",
      },
      {
        key: "cooldown_gate",
        label: "Cooldown",
        color: "#f59e0b",
        value: entryDiagnostics.barsSinceExit,
        threshold: entryDiagnostics.cooldownRequiredBars,
        min: 0,
        max: Math.max(entryDiagnostics.cooldownRequiredBars + 2, 10),
        pass: entryDiagnostics.cooldownPass,
        valueText: entryDiagnostics.barsSinceExit === null ? "n/a" : String(entryDiagnostics.barsSinceExit),
        thresholdText: String(entryDiagnostics.cooldownRequiredBars),
      },
      {
        key: "cadence_gate",
        label: "Cadence",
        color: "#60a5fa",
        value: entryDiagnostics.cadenceHourPass && entryDiagnostics.cadenceDayPass ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: entryDiagnostics.cadenceHourPass && entryDiagnostics.cadenceDayPass,
        valueText: `H:${entryDiagnostics.entriesLastHour}/${maxEntriesPerHour} D:${entryDiagnostics.entriesLastDay}/${maxEntriesPerDay}`,
        thresholdText: "under caps",
      },
      {
        key: "expected",
        label: "Expected",
        color: "#ef4444",
        value: entryDiagnostics.expectedAction === "enter_short" ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: entryDiagnostics.expectedAction === "enter_short",
        valueText: entryDiagnostics.expectedAction,
        thresholdText: "enter_short",
      },
      {
        key: "actual",
        label: "Actual",
        color: "#eab308",
        value: entryDiagnostics.actualAction === "enter_short" ? 1 : 0,
        threshold: 1,
        min: 0,
        max: 1,
        pass: entryDiagnostics.actualAction === "enter_short",
        valueText: entryDiagnostics.actualAction,
        thresholdText: "enter_short",
      },
    ];
  }, [simpleMechanism, entryDiagnostics, maxEntriesPerHour, maxEntriesPerDay]);

  const displayLongMetrics = entryLongSimpleMetrics ?? longMetrics;
  const displayShortMetrics = entryShortSimpleMetrics ?? shortMetrics;

  const entryMismatchReason = useMemo(() => {
    if (!entryDiagnostics) {
      return null;
    }
    if (entryDiagnostics.expectedAction === entryDiagnostics.actualAction) {
      return "Expected and actual action match for selected bar.";
    }
    if (entryDiagnostics.hasOpenPosition) {
      return "Blocked: position already open at evaluation bar (engine cannot open a second position).";
    }
    if (!entryDiagnostics.longAllowed && entryDiagnostics.expectedAction === "enter_long") {
      return "Blocked: trade side mode does not allow long entries.";
    }
    if (!entryDiagnostics.shortAllowed && entryDiagnostics.expectedAction === "enter_short") {
      return "Blocked: trade side mode does not allow short entries.";
    }
    if (!entryDiagnostics.cooldownPass) {
      const lastExit = entryDiagnostics.lastExitReason ?? "recent exit";
      return `Blocked: cooldown active after ${lastExit} (bars since exit ${entryDiagnostics.barsSinceExit ?? 0}/${entryDiagnostics.cooldownRequiredBars}).`;
    }
    if (!entryDiagnostics.cadenceHourPass || !entryDiagnostics.cadenceDayPass) {
      return `Blocked: cadence cap reached (hour ${entryDiagnostics.entriesLastHour}/${maxEntriesPerHour}, day ${entryDiagnostics.entriesLastDay}/${maxEntriesPerDay}).`;
    }
    if (entryDiagnostics.longSignal === null && entryDiagnostics.shortSignal === null) {
      return "Signal unavailable: selected evaluation bar is missing BB/EMA inputs (bb deviation or slope rounding cannot be computed).";
    }
    if (entryDiagnostics.expectedAction === "hold" && entryDiagnostics.actualAction === "hold") {
      return "Gates passed, but no long/short entry signal fired on this bar, so engine correctly held.";
    }
    if (entryDiagnostics.expectedAction !== "hold" && entryDiagnostics.actualAction === "hold") {
      return "Expected entry but engine held. Check execution constraints or adapter-level order rejection around this timestamp.";
    }
    return `Expected ${entryDiagnostics.expectedAction} but actual was ${entryDiagnostics.actualAction}.`;
  }, [entryDiagnostics, maxEntriesPerHour, maxEntriesPerDay]);

  const sideAvailability =
    tradeSide === "long_short" ? "Long + Short" : tradeSide === "short_only" ? "Short only" : "Long only";

  const tradeMarkers = useMemo<TradeMarker[]>(() => {
    const openMarkers: TradeMarker[] = openPositions.map((p) => ({
      ts: p.entry_ts,
      kind: p.trade_side === "short" ? "short_opened" : "long_opened",
      mode: p.execution_mode,
    }));
    const closedMarkers: TradeMarker[] = closedTrades.flatMap((t) => [
      {
        ts: t.entry_ts,
        kind: t.trade_side === "short" ? "short_opened" : "long_opened",
        mode: t.execution_mode,
      },
      {
        ts: t.exit_ts,
        kind: t.trade_side === "short" ? "short_closed" : "long_closed",
        mode: t.execution_mode,
      },
    ]);
    return [...openMarkers, ...closedMarkers];
  }, [openPositions, closedTrades]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: panels.volumeProfile ? "1fr 240px" : "1fr" }}>
      <div>
        <div style={{ display: "flex", gap: 12, fontSize: 12, padding: "8px 10px", borderBottom: "1px solid #22262f" }}>
          <span>O {num(row?.open, 5)}</span>
          <span>H {num(row?.high, 5)}</span>
          <span>L {num(row?.low, 5)}</span>
          <span>C {num(row?.close, 5)}</span>
          <span>V {num(row?.volume, 0)}</span>
          <span>RSI {num(row?.rsi)}</span>
          <span>ATR {num(row?.atr)}</span>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 11, padding: "6px 10px", borderBottom: "1px solid #22262f", color: "#9ca3af" }}>
          <span style={{ color: "#22c55e" }}>↑ LO</span>
          <span style={{ color: "#3b82f6" }}>● LC</span>
          <span style={{ color: "#ef4444" }}>↓ SO</span>
          <span style={{ color: "#a855f7" }}>● SC</span>
          <span>Suffix: S=Sim, R=Real</span>
        </div>
        {chartDataCap ? (
          <div style={{ margin: "8px 10px", padding: "8px 10px", borderRadius: 8, border: "1px solid #3e4d63", background: "#121b29", color: "#c5d6ee", fontSize: 11 }}>
            <strong style={{ color: "#dbeafe" }}>Render cap active:</strong> showing most recent {chartDataCap.shownRows.toLocaleString()} of {chartDataCap.totalRows.toLocaleString()} points (limit={chartDataCap.capLimit.toLocaleString()}).
            <div style={{ marginTop: 4, color: "#9fb3cc" }}>
              Omitted {chartDataCap.omittedRows.toLocaleString()} points from {formatDateTimeWithZone(chartDataCap.omittedStartTs)} to {formatDateTimeWithZone(chartDataCap.omittedEndTs)}.
            </div>
            <div style={{ color: "#9fb3cc" }}>
              Visible range: {formatDateTimeWithZone(chartDataCap.visibleStartTs)} to {formatDateTimeWithZone(chartDataCap.visibleEndTs)}.
            </div>
          </div>
        ) : null}
        <div style={{ margin: "8px 10px", border: "1px solid #2b3442", borderRadius: 8, background: "#121722", padding: "8px 10px" }}>
          <div style={{ fontSize: 11, color: "#93a3b8", marginBottom: 6 }}>
            Timezone: {tzLabel} ({tz})
          </div>
          <div style={{ fontSize: 11, color: "#93a3b8", marginBottom: 6 }}>
            Engine Inputs @ {row?.ts ? formatDateTimeWithZone(row.ts) : "n/a"}
          </div>
          <div style={{ fontSize: 11, color: "#93a3b8", marginBottom: 6 }}>
            Runtime evaluates previous closed bar: {evalRow?.ts ? formatDateTimeWithZone(evalRow.ts) : "n/a"}
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "#9ca3af", marginBottom: 8 }}>
            <span>Engine symbol {assetControl?.symbol ?? "n/a"}</span>
            <span>Engine timeframe {assetControl?.timeframe ?? timeframe}</span>
            <span>Tuning version {assetControl?.tuning_version ?? 0}</span>
            <span>Tuning source {assetControl?.tuning_source ?? "default"}</span>
            <span>Diag status {evalRow?.engine_diag_status ?? "n/a"}</span>
            <span>Diag EMA fast {evalRow?.engine_ema_fast ?? "n/a"}</span>
            <span>Diag EMA slow {evalRow?.engine_ema_slow ?? "n/a"}</span>
            <span>Trade side mode {sideAvailability}</span>
            <span>EMA fast {num(emaFast)}</span>
            <span>BB mode {bbMode}</span>
            {bbMode === "range_revert" ? <span>BB threshold {num(bbThreshold ?? 0.8, 2)}</span> : null}
            <span>Min ATR% {num(minEntryAtrPct, 3)}</span>
            {minHoldSignalBars !== undefined ? <span>Min hold before signal exit {num(minHoldSignalBars)}</span> : null}
            {maxHoldBars !== undefined ? <span>Max hold bars {num(maxHoldBars)}</span> : null}
            <span>Momentum ROC {num(momRoc, 6)}</span>
            <span>Close {num(close)} / EMA{emaFast ?? "?"} {num(emaFastValue)}</span>
            <span>BB lower {num(bbLower)} / BB upper {num(bbUpper)}</span>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <ThresholdSliders title="Open Long (Engine Decision)" metrics={displayLongMetrics} sideEnabled={longEnabled} />
              <ThresholdSliders title="Close Long" metrics={closeLongMetrics} sideEnabled={longEnabled} />
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <ThresholdSliders title="Open Short (Engine Decision)" metrics={displayShortMetrics} sideEnabled={shortEnabled} />
              <ThresholdSliders title="Close Short" metrics={closeShortMetrics} sideEnabled={shortEnabled} />
            </div>
            {entryMismatchReason ? (
              <div
                style={{
                  fontSize: 11,
                  color: entryDiagnostics && entryDiagnostics.expectedAction !== entryDiagnostics.actualAction ? "#fca5a5" : "#9ca3af",
                  background: "#0f1520",
                  border: "1px solid #2b3442",
                  borderRadius: 6,
                  padding: "6px 8px",
                }}
              >
                Mismatch Reason: {entryMismatchReason}
              </div>
            ) : null}
          </div>
        </div>
        {simpleMechanism ? (
          <div style={{ margin: "8px 10px", border: "1px solid #2d3f32", borderRadius: 8, background: "#101b14", padding: "8px 10px" }}>
            <div style={{ fontSize: 11, color: "#a7f3d0", marginBottom: 8 }}>
              {timeframe} Simple Engine Mechanism (BB deviation + EMA slope rounding)
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "#bbf7d0", marginBottom: 6 }}>
              <span>BB dev {num(simpleMechanism.bbDeviation, 3)} (entry threshold ±{num(simpleMechanism.entryDeviation, 2)})</span>
              <span>Slope now {num(simpleMechanism.slopeNow, 6)}</span>
              <span>Slope lookback {num(simpleMechanism.slopeLookback, 6)}</span>
              <span>Flatten ratio {num(simpleMechanism.flattenRatio, 3)} {"<="} {num(simpleMechanism.flattenFactor, 2)}</span>
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 11, color: "#d1fae5" }}>
              <span>Long rounding {String(simpleMechanism.longRounding)}</span>
              <span>Short rounding {String(simpleMechanism.shortRounding)}</span>
              <span>Long entry signal {String(simpleMechanism.longEntry)}</span>
              <span>Short entry signal {String(simpleMechanism.shortEntry)}</span>
              <span>Long exit signal {String(simpleMechanism.longExitSignal)} (exit dev {-simpleMechanism.exitDeviation})</span>
              <span>Short exit signal {String(simpleMechanism.shortExitSignal)} (exit dev {simpleMechanism.exitDeviation})</span>
            </div>
          </div>
        ) : null}
        <CandleChart rows={rows} overlays={overlays} tradeMarkers={tradeMarkers} onCrosshair={setCrosshair} />
        <IndicatorPanels rows={rows} showVolume={true} showRsi={panels.rsi} showAtr={panels.atr} showBbWidth={panels.bbWidth} />
        <DataHealthPanel lastTs={rows[rows.length - 1]?.ts} gapCount={gaps.length} gaps={gaps} />
      </div>
      {panels.volumeProfile && <VolumeProfile bins={profile} />}
    </div>
  );
}
