import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
import { createChart, HistogramSeries, LineSeries } from "lightweight-charts";
function VolumePanel({ rows }) {
    const ref = useRef(null);
    useEffect(() => {
        if (!ref.current)
            return;
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
        series.setData(rows.map((r) => ({
            time: Math.floor(new Date(r.ts).getTime() / 1000),
            value: r.volume,
            color: r.close >= r.open ? "#1f8f4c" : "#8f2d2d",
        })));
        chart.timeScale().fitContent();
        return () => chart.remove();
    }, [rows]);
    return (_jsxs("div", { style: { borderTop: "1px solid #22262f" }, children: [_jsx("div", { style: { padding: "4px 8px", fontSize: 12 }, children: "Volume" }), _jsx("div", { ref: ref })] }));
}
function Panel({ title, rows, keyName, color }) {
    const ref = useRef(null);
    useEffect(() => {
        if (!ref.current)
            return;
        const chart = createChart(ref.current, {
            layout: { background: { color: "#0f1115" }, textColor: "#9ca3af" },
            rightPriceScale: { borderColor: "#2f3542" },
            timeScale: { borderColor: "#2f3542", timeVisible: true },
            grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
            height: 150,
        });
        const series = chart.addSeries(LineSeries, { color, lineWidth: 2 });
        series.setData(rows
            .filter((r) => typeof r[keyName] === "number")
            .map((r) => ({ time: Math.floor(new Date(r.ts).getTime() / 1000), value: Number(r[keyName]) })));
        chart.timeScale().fitContent();
        return () => chart.remove();
    }, [rows, keyName, color]);
    return (_jsxs("div", { style: { borderTop: "1px solid #22262f" }, children: [_jsx("div", { style: { padding: "4px 8px", fontSize: 12 }, children: title }), _jsx("div", { ref: ref })] }));
}
export default function IndicatorPanels({ rows, showVolume, showRsi, showAtr, showBbWidth }) {
    return (_jsxs("div", { children: [showVolume && _jsx(VolumePanel, { rows: rows }), showRsi && _jsx(Panel, { title: "RSI", rows: rows, keyName: "rsi", color: "#38bdf8" }), showAtr && _jsx(Panel, { title: "ATR", rows: rows, keyName: "atr", color: "#f97316" }), showBbWidth && _jsx(Panel, { title: "BB Width", rows: rows, keyName: "bb_width", color: "#a78bfa" })] }));
}
