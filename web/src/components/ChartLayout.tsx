import React, { useMemo } from "react";
import type { AssetControl, ClosedTrade, Gap, IndicatorRow, OpenPosition } from "../api/types";
import CandleChart from "./CandleChart";
import IndicatorPanels from "./IndicatorPanels";
import VolumeProfile from "./VolumeProfile";
import DataHealthPanel from "./DataHealthPanel";
import { buildVolumeProfile } from "../utils/volumeProfile";
import { num } from "../utils/formatting";

type TradeMarker = {
  ts: string;
  kind: "long_opened" | "long_closed" | "short_opened" | "short_closed";
  mode: "sim" | "live";
};

type Props = {
  rows: IndicatorRow[];
  gaps: Gap[];
  overlays: { bbands: boolean; ema20: boolean; ema50: boolean; ema200: boolean };
  panels: { rsi: boolean; atr: boolean; bbWidth: boolean; volumeProfile: boolean };
  openPositions: OpenPosition[];
  closedTrades: ClosedTrade[];
  assetControl?: AssetControl;
  crosshair: IndicatorRow | null;
  setCrosshair: (row: IndicatorRow | null) => void;
};

type EntryConditionState = {
  rsi: boolean | null;
  trend: boolean | null;
  bb: boolean | null;
  momentum: boolean | null;
  volatility: boolean | null;
  all: boolean | null;
};

type BinaryLane = {
  key: string;
  label: string;
  color: string;
  values: number[];
  current: boolean | null;
};

type BinarySubplotProps = {
  title: string;
  lanes: BinaryLane[];
  sideEnabled: boolean;
};

function BinarySubplot({ title, lanes, sideEnabled }: BinarySubplotProps) {
  const pointCount = lanes[0]?.values.length ?? 0;
  const laneHeight = 14;
  const chartWidth = Math.max(260, pointCount * 4);
  const chartHeight = Math.max(1, lanes.length) * laneHeight;

  const pointsFor = (values: number[], laneIndex: number): string => {
    if (values.length === 0) {
      return "";
    }
    const high = laneIndex * laneHeight + 3;
    const low = laneIndex * laneHeight + laneHeight - 3;
    return values
      .map((v, i) => {
        const x = values.length === 1 ? 0 : (i * (chartWidth - 1)) / (values.length - 1);
        const y = v === 1 ? high : low;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  };

  const currentText = (value: boolean | null): string => {
    if (!sideEnabled) {
      return "inactive";
    }
    if (value === null) {
      return "n/a";
    }
    return value ? "1" : "0";
  };

  return (
    <div style={{ border: "1px solid #2b3442", borderRadius: 8, background: "#0f1520", padding: "8px 10px", minWidth: 280 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 12, color: "#dbe6f5", fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 10, color: sideEnabled ? "#9ca3af" : "#ef4444" }}>
          {sideEnabled ? "active" : "inactive"}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "70px 1fr 34px", gap: 6, alignItems: "start" }}>
        <div>
          {lanes.map((lane) => (
            <div key={lane.key} style={{ height: laneHeight, fontSize: 10, color: "#9ca3af", lineHeight: `${laneHeight}px` }}>
              {lane.label}
            </div>
          ))}
        </div>
        <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} style={{ width: "100%", height: chartHeight, background: "#0b111b", borderRadius: 4 }}>
          {lanes.map((lane, idx) => {
            const y = idx * laneHeight + laneHeight - 3;
            return <line key={`${lane.key}-base`} x1={0} y1={y} x2={chartWidth} y2={y} stroke="#1f2a3a" strokeWidth={1} />;
          })}
          {lanes.map((lane, idx) => (
            <polyline
              key={lane.key}
              fill="none"
              stroke={lane.color}
              strokeWidth={1.8}
              points={pointsFor(lane.values, idx)}
              opacity={sideEnabled ? 1 : 0.45}
            />
          ))}
        </svg>
        <div>
          {lanes.map((lane) => (
            <div key={`${lane.key}-curr`} style={{ height: laneHeight, fontSize: 10, color: "#cbd5e1", textAlign: "right", lineHeight: `${laneHeight}px` }}>
              {currentText(lane.current)}
            </div>
          ))}
        </div>
      </div>
      <div style={{ marginTop: 6, fontSize: 10, color: "#93a3b8" }}>`ALL=1` means entry signal conditions were fully met on that bar.</div>
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

function allTrue(values: Array<boolean | null>): boolean | null {
  if (values.some((v) => v === null)) {
    return null;
  }
  return values.every((v) => v === true);
}

export default function ChartLayout({ rows, gaps, overlays, panels, openPositions, closedTrades, assetControl, crosshair, setCrosshair }: Props) {
  const profile = useMemo(() => buildVolumeProfile(rows), [rows]);
  const row = crosshair ?? rows[rows.length - 1] ?? null;
  const rowIndex = row ? rows.findIndex((r) => r.ts === row.ts) : -1;
  const evalRow = rowIndex > 0 ? rows[rowIndex - 1] : row;
  const tuning = assetControl?.tuning_params ?? {};

  const rsiEntry = typeof tuning.rsi_entry === "number" ? tuning.rsi_entry : undefined;
  const rsiExit = typeof tuning.rsi_exit === "number" ? tuning.rsi_exit : undefined;
  const emaFast = typeof tuning.ema_fast === "number" ? tuning.ema_fast : undefined;
  const maxHoldBars = typeof tuning.max_hold_bars === "number" ? tuning.max_hold_bars : undefined;
  const minHoldSignalBars = typeof tuning.min_hold_bars_before_signal_exit === "number" ? tuning.min_hold_bars_before_signal_exit : undefined;
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

  const evaluateEntryState = (prevRow: IndicatorRow | null | undefined, side: "long" | "short"): EntryConditionState => {
    if (!prevRow) {
      return { rsi: null, trend: null, bb: null, momentum: null, volatility: null, all: null };
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

    let bbPass: boolean | null = null;
    if (bbMode === "off") {
      bbPass = true;
    } else if (bbMode === "touch_revert") {
      const bbBound = side === "long" ? prevRow.bb_lower ?? null : prevRow.bb_upper ?? null;
      if (closeValue !== null && bbBound !== null) {
        bbPass = side === "long" ? closeValue <= bbBound : closeValue >= bbBound;
      }
    } else if (bbMode === "range_revert") {
      const lower = prevRow.bb_lower ?? null;
      const upper = prevRow.bb_upper ?? null;
      if (closeValue !== null && lower !== null && upper !== null && upper > lower) {
        const threshold = bbThreshold ?? 0.8;
        const range = upper - lower;
        const cutoff = side === "long" ? lower + threshold * range : upper - threshold * range;
        bbPass = side === "long" ? closeValue <= cutoff : closeValue >= cutoff;
      }
    }

    const momentumPass = momentumEnabled
      ? side === "long"
        ? (prevRow.swing_long_ready ?? null)
        : (prevRow.swing_short_ready ?? null)
      : true;

    const volatilityPass =
      minEntryAtrPct > 0
        ? (atrValue !== null && closeValue !== null && closeValue > 0 ? (atrValue / closeValue) * 100 >= minEntryAtrPct : null)
        : true;

    const all = allTrue([rsiPass, trendPass, bbPass, momentumPass, volatilityPass]);
    return { rsi: rsiPass, trend: trendPass, bb: bbPass, momentum: momentumPass, volatility: volatilityPass, all };
  };

  const currentLong = evaluateEntryState(evalRow, "long");
  const currentShort = evaluateEntryState(evalRow, "short");

  const conditionSeries = useMemo(() => {
    const start = Math.max(1, rows.length - 120);
    const toBit = (v: boolean | null): number => (v === true ? 1 : 0);

    const longLanes: BinaryLane[] = [
      { key: "rsi", label: "RSI", color: "#38bdf8", values: [], current: currentLong.rsi },
      { key: "trend", label: "Trend", color: "#f59e0b", values: [], current: currentLong.trend },
      { key: "bb", label: "BB", color: "#a78bfa", values: [], current: currentLong.bb },
      { key: "momentum", label: "Mom", color: "#34d399", values: [], current: currentLong.momentum },
      { key: "volatility", label: "Vol", color: "#f472b6", values: [], current: currentLong.volatility },
      { key: "all", label: "ALL", color: "#22c55e", values: [], current: currentLong.all },
    ];
    const shortLanes: BinaryLane[] = [
      { key: "rsi", label: "RSI", color: "#38bdf8", values: [], current: currentShort.rsi },
      { key: "trend", label: "Trend", color: "#f59e0b", values: [], current: currentShort.trend },
      { key: "bb", label: "BB", color: "#a78bfa", values: [], current: currentShort.bb },
      { key: "momentum", label: "Mom", color: "#34d399", values: [], current: currentShort.momentum },
      { key: "volatility", label: "Vol", color: "#f472b6", values: [], current: currentShort.volatility },
      { key: "all", label: "ALL", color: "#ef4444", values: [], current: currentShort.all },
    ];

    for (let i = start; i < rows.length; i += 1) {
      const prevRow = rows[i - 1];
      const longState = evaluateEntryState(prevRow, "long");
      const shortState = evaluateEntryState(prevRow, "short");

      longLanes[0].values.push(toBit(longState.rsi));
      longLanes[1].values.push(toBit(longState.trend));
      longLanes[2].values.push(toBit(longState.bb));
      longLanes[3].values.push(toBit(longState.momentum));
      longLanes[4].values.push(toBit(longState.volatility));
      longLanes[5].values.push(toBit(longState.all));

      shortLanes[0].values.push(toBit(shortState.rsi));
      shortLanes[1].values.push(toBit(shortState.trend));
      shortLanes[2].values.push(toBit(shortState.bb));
      shortLanes[3].values.push(toBit(shortState.momentum));
      shortLanes[4].values.push(toBit(shortState.volatility));
      shortLanes[5].values.push(toBit(shortState.all));
    }

    return { longLanes, shortLanes };
  }, [rows, currentLong.rsi, currentLong.trend, currentLong.bb, currentLong.momentum, currentLong.volatility, currentLong.all, currentShort.rsi, currentShort.trend, currentShort.bb, currentShort.momentum, currentShort.volatility, currentShort.all]);

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
          <span>O {num(row?.open)}</span>
          <span>H {num(row?.high)}</span>
          <span>L {num(row?.low)}</span>
          <span>C {num(row?.close)}</span>
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
        <div style={{ margin: "8px 10px", border: "1px solid #2b3442", borderRadius: 8, background: "#121722", padding: "8px 10px" }}>
          <div style={{ fontSize: 11, color: "#93a3b8", marginBottom: 6 }}>
            Engine Inputs @ {row?.ts ?? "n/a"}
          </div>
          <div style={{ fontSize: 11, color: "#93a3b8", marginBottom: 6 }}>
            Runtime evaluates previous closed bar: {evalRow?.ts ?? "n/a"}
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "#9ca3af", marginBottom: 8 }}>
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
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 10 }}>
            <BinarySubplot title="Open Long" lanes={conditionSeries.longLanes} sideEnabled={longEnabled} />
            <BinarySubplot title="Open Short" lanes={conditionSeries.shortLanes} sideEnabled={shortEnabled} />
          </div>
        </div>
        <CandleChart rows={rows} overlays={overlays} tradeMarkers={tradeMarkers} onCrosshair={setCrosshair} />
        <IndicatorPanels rows={rows} showVolume={true} showRsi={panels.rsi} showAtr={panels.atr} showBbWidth={panels.bbWidth} />
        <DataHealthPanel lastTs={rows[rows.length - 1]?.ts} gapCount={gaps.length} gaps={gaps} />
      </div>
      {panels.volumeProfile && <VolumeProfile bins={profile} />}
    </div>
  );
}
