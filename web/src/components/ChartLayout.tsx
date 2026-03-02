import React, { useMemo } from "react";
import type { Gap, IndicatorRow } from "../api/types";
import CandleChart from "./CandleChart";
import IndicatorPanels from "./IndicatorPanels";
import VolumeProfile from "./VolumeProfile";
import DataHealthPanel from "./DataHealthPanel";
import { buildVolumeProfile } from "../utils/volumeProfile";
import { num } from "../utils/formatting";

type Props = {
  rows: IndicatorRow[];
  gaps: Gap[];
  overlays: { bbands: boolean; ema20: boolean; ema50: boolean; ema200: boolean };
  panels: { rsi: boolean; atr: boolean; bbWidth: boolean; volumeProfile: boolean };
  crosshair: IndicatorRow | null;
  setCrosshair: (row: IndicatorRow | null) => void;
};

export default function ChartLayout({ rows, gaps, overlays, panels, crosshair, setCrosshair }: Props) {
  const profile = useMemo(() => buildVolumeProfile(rows), [rows]);
  const row = crosshair ?? rows[rows.length - 1] ?? null;

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
        <CandleChart rows={rows} overlays={overlays} onCrosshair={setCrosshair} />
        <IndicatorPanels rows={rows} showRsi={panels.rsi} showAtr={panels.atr} showBbWidth={panels.bbWidth} />
        <DataHealthPanel lastTs={rows[rows.length - 1]?.ts} gapCount={gaps.length} gaps={gaps} />
      </div>
      {panels.volumeProfile && <VolumeProfile bins={profile} />}
    </div>
  );
}
