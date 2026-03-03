import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { useMemo } from "react";
import CandleChart from "./CandleChart";
import IndicatorPanels from "./IndicatorPanels";
import VolumeProfile from "./VolumeProfile";
import DataHealthPanel from "./DataHealthPanel";
import { buildVolumeProfile } from "../utils/volumeProfile";
import { num } from "../utils/formatting";
export default function ChartLayout({ rows, gaps, overlays, panels, openPositions, closedTrades, crosshair, setCrosshair }) {
    const profile = useMemo(() => buildVolumeProfile(rows), [rows]);
    const row = crosshair ?? rows[rows.length - 1] ?? null;
    const tradeMarkers = useMemo(() => {
        const openMarkers = openPositions.map((p) => ({
            ts: p.entry_ts,
            kind: p.trade_side === "short" ? "short_opened" : "long_opened",
            mode: p.execution_mode,
        }));
        const closedMarkers = closedTrades.flatMap((t) => [
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
    return (_jsxs("div", { style: { display: "grid", gridTemplateColumns: panels.volumeProfile ? "1fr 240px" : "1fr" }, children: [_jsxs("div", { children: [_jsxs("div", { style: { display: "flex", gap: 12, fontSize: 12, padding: "8px 10px", borderBottom: "1px solid #22262f" }, children: [_jsxs("span", { children: ["O ", num(row?.open)] }), _jsxs("span", { children: ["H ", num(row?.high)] }), _jsxs("span", { children: ["L ", num(row?.low)] }), _jsxs("span", { children: ["C ", num(row?.close)] }), _jsxs("span", { children: ["V ", num(row?.volume, 0)] }), _jsxs("span", { children: ["RSI ", num(row?.rsi)] }), _jsxs("span", { children: ["ATR ", num(row?.atr)] })] }), _jsxs("div", { style: { display: "flex", gap: 10, flexWrap: "wrap", fontSize: 11, padding: "6px 10px", borderBottom: "1px solid #22262f", color: "#9ca3af" }, children: [_jsx("span", { style: { color: "#22c55e" }, children: "\u2191 LO" }), _jsx("span", { style: { color: "#3b82f6" }, children: "\u25CF LC" }), _jsx("span", { style: { color: "#ef4444" }, children: "\u2193 SO" }), _jsx("span", { style: { color: "#a855f7" }, children: "\u25CF SC" }), _jsx("span", { children: "Suffix: S=Sim, R=Real" })] }), _jsx(CandleChart, { rows: rows, overlays: overlays, tradeMarkers: tradeMarkers, onCrosshair: setCrosshair }), _jsx(IndicatorPanels, { rows: rows, showVolume: true, showRsi: panels.rsi, showAtr: panels.atr, showBbWidth: panels.bbWidth }), _jsx(DataHealthPanel, { lastTs: rows[rows.length - 1]?.ts, gapCount: gaps.length, gaps: gaps })] }), panels.volumeProfile && _jsx(VolumeProfile, { bins: profile })] }));
}
