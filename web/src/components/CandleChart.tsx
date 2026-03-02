import React, { useEffect, useRef } from "react";
import {
  createChart,
  type ISeriesApi,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type Time,
} from "lightweight-charts";
import type { IndicatorRow } from "../api/types";
import { candleHeat } from "../utils/volumeProfile";

type Props = {
  rows: IndicatorRow[];
  overlays: { bbands: boolean; ema20: boolean; ema50: boolean; ema200: boolean };
  onCrosshair: (row: IndicatorRow | null) => void;
};

function toTime(ts: string): Time {
  return Math.floor(new Date(ts).getTime() / 1000) as Time;
}

export default function CandleChart({ rows, overlays, onCrosshair }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { color: "#0f1115" }, textColor: "#c5d0e6" },
      rightPriceScale: { borderColor: "#2f3542" },
      timeScale: { borderColor: "#2f3542", timeVisible: true },
      crosshair: { mode: 1 },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      borderVisible: false,
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: "",
      priceFormat: { type: "volume" },
      color: "#64748b",
    });

    const bbLower = chart.addSeries(LineSeries, { color: "#1d4ed8", lineWidth: 1 });
    const bbMid = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1 });
    const bbUpper = chart.addSeries(LineSeries, { color: "#1d4ed8", lineWidth: 1 });
    const ema20 = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1 });
    const ema50 = chart.addSeries(LineSeries, { color: "#eab308", lineWidth: 1 });
    const ema200 = chart.addSeries(LineSeries, { color: "#a855f7", lineWidth: 1 });

    candleSeries.setData(
      rows.map((r) => ({
        time: toTime(r.ts),
        open: r.open,
        high: r.high,
        low: r.low,
        close: r.close,
        color: `rgba(${r.close >= r.open ? "34,197,94" : "239,68,68"},${candleHeat(r.volume, r.volume_sma)})`,
      }))
    );

    volumeSeries.setData(
      rows.map((r) => ({
        time: toTime(r.ts),
        value: r.volume,
        color: r.close >= r.open ? "#1f8f4c" : "#8f2d2d",
      }))
    );

    const setLine = (series: ISeriesApi<"Line">, key: keyof IndicatorRow, enabled: boolean) => {
      if (!enabled) {
        series.setData([]);
        return;
      }
      series.setData(
        rows
          .filter((r) => typeof r[key] === "number")
          .map((r) => ({ time: toTime(r.ts), value: Number(r[key]) }))
      );
    };

    setLine(bbLower, "bb_lower", overlays.bbands);
    setLine(bbMid, "bb_mid", overlays.bbands);
    setLine(bbUpper, "bb_upper", overlays.bbands);
    setLine(ema20, "ema20", overlays.ema20);
    setLine(ema50, "ema50", overlays.ema50);
    setLine(ema200, "ema200", overlays.ema200);

    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) {
        onCrosshair(null);
        return;
      }
      const row = rows.find((r) => toTime(r.ts) === param.time);
      onCrosshair(row ?? null);
    });

    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 800, height: 520 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [rows, overlays, onCrosshair]);

  return <div ref={ref} style={{ width: "100%", height: 520 }} />;
}
