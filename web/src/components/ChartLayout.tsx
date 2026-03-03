import React, { useMemo } from "react";
import type { ClosedTrade, Gap, IndicatorRow, OpenPosition } from "../api/types";
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
  crosshair: IndicatorRow | null;
  setCrosshair: (row: IndicatorRow | null) => void;
};

export default function ChartLayout({ rows, gaps, overlays, panels, openPositions, closedTrades, crosshair, setCrosshair }: Props) {
  const profile = useMemo(() => buildVolumeProfile(rows), [rows]);
  const row = crosshair ?? rows[rows.length - 1] ?? null;
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
        <CandleChart rows={rows} overlays={overlays} tradeMarkers={tradeMarkers} onCrosshair={setCrosshair} />
        <IndicatorPanels rows={rows} showVolume={true} showRsi={panels.rsi} showAtr={panels.atr} showBbWidth={panels.bbWidth} />
        <DataHealthPanel lastTs={rows[rows.length - 1]?.ts} gapCount={gaps.length} gaps={gaps} />
      </div>
      {panels.volumeProfile && <VolumeProfile bins={profile} />}
    </div>
  );
}
