import React, { useEffect, useRef } from "react";
import { createChart, HistogramSeries, LineSeries, type Time } from "lightweight-charts";
import type { IndicatorRow } from "../api/types";

type Props = {
  rows: IndicatorRow[];
  showVolume: boolean;
  showRsi: boolean;
  showAtr: boolean;
  showBbWidth: boolean;
};

function VolumePanel({ rows }: { rows: IndicatorRow[] }) {
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
    const series = chart.addSeries(HistogramSeries, {
      priceScaleId: "",
      priceFormat: { type: "volume" },
      color: "#64748b",
    });
    series.setData(
      rows.map((r) => ({
        time: Math.floor(new Date(r.ts).getTime() / 1000) as Time,
        value: r.volume,
        color: r.close >= r.open ? "#1f8f4c" : "#8f2d2d",
      }))
    );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [rows]);

  return (
    <div style={{ borderTop: "1px solid #22262f" }}>
      <div style={{ padding: "4px 8px", fontSize: 12 }}>Volume</div>
      <div ref={ref} />
    </div>
  );
}

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

export default function IndicatorPanels({ rows, showVolume, showRsi, showAtr, showBbWidth }: Props) {
  return (
    <div>
      {showVolume && <VolumePanel rows={rows} />}
      {showRsi && <Panel title="RSI" rows={rows} keyName="rsi" color="#38bdf8" />}
      {showAtr && <Panel title="ATR" rows={rows} keyName="atr" color="#f97316" />}
      {showBbWidth && <Panel title="BB Width" rows={rows} keyName="bb_width" color="#a78bfa" />}
    </div>
  );
}
