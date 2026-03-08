import React, { useEffect, useMemo, useRef } from "react";
import {
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  CandlestickSeries,
  LineSeries,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { IndicatorRow } from "../api/types";
import { candleHeat } from "../utils/volumeProfile";

type TradeMarker = {
  ts: string;
  kind: "long_opened" | "long_closed" | "short_opened" | "short_closed";
  mode: "sim" | "live";
};

type Props = {
  rows: IndicatorRow[];
  overlays: { bbands: boolean; ema20: boolean; ema50: boolean; ema200: boolean };
  tradeMarkers: TradeMarker[];
  onCrosshair: (row: IndicatorRow | null) => void;
};

function toTime(ts: string): Time {
  return Math.floor(parseApiTs(ts).getTime() / 1000) as Time;
}

function toEpochSeconds(ts: string): number {
  return Math.floor(parseApiTs(ts).getTime() / 1000);
}

function parseApiTs(ts: string): Date {
  // API candles are stored as UTC; if tz is omitted, force UTC interpretation.
  if (/Z$|[+-]\d{2}:\d{2}$/.test(ts)) {
    return new Date(ts);
  }
  return new Date(`${ts}Z`);
}

function inferStepSeconds(rows: IndicatorRow[]): number {
  if (rows.length < 2) return 60;
  const diffs: number[] = [];
  for (let i = 1; i < rows.length; i += 1) {
    const diff = Math.max(1, toEpochSeconds(rows[i].ts) - toEpochSeconds(rows[i - 1].ts));
    diffs.push(diff);
  }
  return Math.max(1, Math.min(...diffs));
}

function withWhitespaceGaps(rows: IndicatorRow[]): Array<{ time: Time; open?: number; high?: number; low?: number; close?: number; color?: string }> {
  if (rows.length === 0) return [];
  const step = inferStepSeconds(rows);
  const out: Array<{ time: Time; open?: number; high?: number; low?: number; close?: number; color?: string }> = [];

  for (let i = 0; i < rows.length; i += 1) {
    const r = rows[i];
    const t = toEpochSeconds(r.ts);
    out.push({
      time: t as Time,
      open: r.open,
      high: r.high,
      low: r.low,
      close: r.close,
      color: `rgba(${r.close >= r.open ? "34,197,94" : "239,68,68"},${candleHeat(r.volume, r.volume_sma)})`,
    });

    if (i === rows.length - 1) continue;
    const nextT = toEpochSeconds(rows[i + 1].ts);
    for (let missingT = t + step; missingT < nextT; missingT += step) {
      out.push({ time: missingT as Time });
    }
  }

  return out;
}

export default function CandleChart({ rows, overlays, tradeMarkers, onCrosshair }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbMidRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema50Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema200Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const markersApiRef = useRef<{ setMarkers: (markers: SeriesMarker<Time>[]) => void } | null>(null);
  const rowByTimeRef = useRef<Map<number, IndicatorRow>>(new Map());
  const didFitOnceRef = useRef(false);

  const normalizedRows = useMemo(() => {
    const sorted = [...rows].sort((a, b) => toEpochSeconds(a.ts) - toEpochSeconds(b.ts));
    const deduped: IndicatorRow[] = [];
    for (const row of sorted) {
      if (deduped.length === 0) {
        deduped.push(row);
        continue;
      }
      const prev = deduped[deduped.length - 1];
      if (toEpochSeconds(prev.ts) === toEpochSeconds(row.ts)) {
        deduped[deduped.length - 1] = row;
      } else {
        deduped.push(row);
      }
    }
    return deduped;
  }, [rows]);

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

    const bbLower = chart.addSeries(LineSeries, { color: "#1d4ed8", lineWidth: 1 });
    const bbMid = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1 });
    const bbUpper = chart.addSeries(LineSeries, { color: "#1d4ed8", lineWidth: 1 });
    const ema20 = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1 });
    const ema50 = chart.addSeries(LineSeries, { color: "#eab308", lineWidth: 1 });
    const ema200 = chart.addSeries(LineSeries, { color: "#a855f7", lineWidth: 1 });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    bbLowerRef.current = bbLower;
    bbMidRef.current = bbMid;
    bbUpperRef.current = bbUpper;
    ema20Ref.current = ema20;
    ema50Ref.current = ema50;
    ema200Ref.current = ema200;
    markersApiRef.current = createSeriesMarkers(candleSeries, []);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) {
        onCrosshair(null);
        return;
      }
      onCrosshair(rowByTimeRef.current.get(Number(param.time)) ?? null);
    });

    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 800, height: 520 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      bbLowerRef.current = null;
      bbMidRef.current = null;
      bbUpperRef.current = null;
      ema20Ref.current = null;
      ema50Ref.current = null;
      ema200Ref.current = null;
      markersApiRef.current = null;
      didFitOnceRef.current = false;
    };
  }, [onCrosshair]);

  useEffect(() => {
    rowByTimeRef.current = new Map(normalizedRows.map((r) => [toEpochSeconds(r.ts), r]));

    const candleSeries = candleSeriesRef.current;
    if (!candleSeries) return;
    candleSeries.setData(withWhitespaceGaps(normalizedRows));

    if (!didFitOnceRef.current && normalizedRows.length > 0) {
      chartRef.current?.timeScale().fitContent();
      didFitOnceRef.current = true;
    }
  }, [normalizedRows]);

  useEffect(() => {
    const setLine = (series: ISeriesApi<"Line"> | null, key: keyof IndicatorRow, enabled: boolean) => {
      if (!series) return;
      if (!enabled) {
        series.setData([]);
        return;
      }
      series.setData(
        normalizedRows
          .filter((r) => typeof r[key] === "number")
          .map((r) => ({ time: toTime(r.ts), value: Number(r[key]) }))
      );
    };

    setLine(bbLowerRef.current, "bb_lower", overlays.bbands);
    setLine(bbMidRef.current, "bb_mid", overlays.bbands);
    setLine(bbUpperRef.current, "bb_upper", overlays.bbands);
    setLine(ema20Ref.current, "ema20", overlays.ema20);
    setLine(ema50Ref.current, "ema50", overlays.ema50);
    setLine(ema200Ref.current, "ema200", overlays.ema200);
  }, [normalizedRows, overlays]);

  useEffect(() => {
    const markers = tradeMarkers
      .map((m) => {
        const modeTag = m.mode === "sim" ? "S" : "R";
        if (m.kind === "long_opened") {
          return {
            time: toTime(m.ts),
            position: "belowBar" as const,
            shape: "arrowUp" as const,
            color: "#22c55e",
            text: `LO-${modeTag}`,
          };
        }
        if (m.kind === "long_closed") {
          return {
            time: toTime(m.ts),
            position: "aboveBar" as const,
            shape: "circle" as const,
            color: "#3b82f6",
            text: `LC-${modeTag}`,
          };
        }
        if (m.kind === "short_opened") {
          return {
            time: toTime(m.ts),
            position: "aboveBar" as const,
            shape: "arrowDown" as const,
            color: "#ef4444",
            text: `SO-${modeTag}`,
          };
        }
        return {
          time: toTime(m.ts),
          position: "belowBar" as const,
          shape: "circle" as const,
          color: "#a855f7",
          text: `SC-${modeTag}`,
        };
      })
      .sort((a, b) => Number(a.time) - Number(b.time)) as SeriesMarker<Time>[];

    markersApiRef.current?.setMarkers(markers);
  }, [tradeMarkers]);

  return <div ref={ref} style={{ width: "100%", height: 520 }} />;
}
