import React, { useEffect, useRef } from "react";
import { createChart, LineSeries, type Time } from "lightweight-charts";
import type { IndicatorRow } from "../api/types";

type Props = {
  rows: IndicatorRow[];
  showRsi: boolean;
  showAtr: boolean;
  showBbWidth: boolean;
};

function Panel({ title, rows, keyName, color }: { title: string; rows: IndicatorRow[]; keyName: keyof IndicatorRow; color: string }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { color: "#0f1115" }, textColor: "#9ca3af" },
      rightPriceScale: { borderColor: "#2f3542" },
      timeScale: { borderColor: "#2f3542", timeVisible: true },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
      height: 150,
    });
    const series = chart.addSeries(LineSeries, { color, lineWidth: 2 });
    series.setData(
      rows
        .filter((r) => typeof r[keyName] === "number")
        .map((r) => ({ time: Math.floor(new Date(r.ts).getTime() / 1000) as Time, value: Number(r[keyName]) }))
    );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [rows, keyName, color]);

  return (
    <div style={{ borderTop: "1px solid #22262f" }}>
      <div style={{ padding: "4px 8px", fontSize: 12 }}>{title}</div>
      <div ref={ref} />
    </div>
  );
}

export default function IndicatorPanels({ rows, showRsi, showAtr, showBbWidth }: Props) {
  return (
    <div>
      {showRsi && <Panel title="RSI" rows={rows} keyName="rsi" color="#38bdf8" />}
      {showAtr && <Panel title="ATR" rows={rows} keyName="atr" color="#f97316" />}
      {showBbWidth && <Panel title="BB Width" rows={rows} keyName="bb_width" color="#a78bfa" />}
    </div>
  );
}
