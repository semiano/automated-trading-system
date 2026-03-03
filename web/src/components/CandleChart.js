import { jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
import { createChart, createSeriesMarkers, CandlestickSeries, LineSeries, } from "lightweight-charts";
import { candleHeat } from "../utils/volumeProfile";
function toTime(ts) {
    return Math.floor(new Date(ts).getTime() / 1000);
}
function toEpochSeconds(ts) {
    return Math.floor(new Date(ts).getTime() / 1000);
}
function inferStepSeconds(rows) {
    if (rows.length < 2)
        return 60;
    const diffs = [];
    for (let i = 1; i < rows.length; i += 1) {
        const diff = Math.max(1, toEpochSeconds(rows[i].ts) - toEpochSeconds(rows[i - 1].ts));
        diffs.push(diff);
    }
    return Math.max(1, Math.min(...diffs));
}
function withWhitespaceGaps(rows) {
    if (rows.length === 0)
        return [];
    const step = inferStepSeconds(rows);
    const out = [];
    for (let i = 0; i < rows.length; i += 1) {
        const r = rows[i];
        const t = toEpochSeconds(r.ts);
        out.push({
            time: t,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            color: `rgba(${r.close >= r.open ? "34,197,94" : "239,68,68"},${candleHeat(r.volume, r.volume_sma)})`,
        });
        if (i === rows.length - 1)
            continue;
        const nextT = toEpochSeconds(rows[i + 1].ts);
        for (let missingT = t + step; missingT < nextT; missingT += step) {
            out.push({ time: missingT });
        }
    }
    return out;
}
export default function CandleChart({ rows, overlays, tradeMarkers, onCrosshair }) {
    const ref = useRef(null);
    useEffect(() => {
        if (!ref.current)
            return;
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
        candleSeries.setData(withWhitespaceGaps(rows));
        const markers = tradeMarkers
            .map((m) => {
            const modeTag = m.mode === "sim" ? "S" : "R";
            if (m.kind === "long_opened") {
                return {
                    time: toTime(m.ts),
                    position: "belowBar",
                    shape: "arrowUp",
                    color: "#22c55e",
                    text: `LO-${modeTag}`,
                };
            }
            if (m.kind === "long_closed") {
                return {
                    time: toTime(m.ts),
                    position: "aboveBar",
                    shape: "circle",
                    color: "#3b82f6",
                    text: `LC-${modeTag}`,
                };
            }
            if (m.kind === "short_opened") {
                return {
                    time: toTime(m.ts),
                    position: "aboveBar",
                    shape: "arrowDown",
                    color: "#ef4444",
                    text: `SO-${modeTag}`,
                };
            }
            return {
                time: toTime(m.ts),
                position: "belowBar",
                shape: "circle",
                color: "#a855f7",
                text: `SC-${modeTag}`,
            };
        })
            .sort((a, b) => Number(a.time) - Number(b.time));
        createSeriesMarkers(candleSeries, markers);
        const setLine = (series, key, enabled) => {
            if (!enabled) {
                series.setData([]);
                return;
            }
            series.setData(rows
                .filter((r) => typeof r[key] === "number")
                .map((r) => ({ time: toTime(r.ts), value: Number(r[key]) })));
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
    }, [rows, overlays, tradeMarkers, onCrosshair]);
    return _jsx("div", { ref: ref, style: { width: "100%", height: 520 } });
}
