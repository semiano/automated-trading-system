import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { fetchAssetControls, fetchCandles, fetchClosedTrades, fetchGaps, fetchIndicators, fetchOpenPositions, fetchSymbols, updateAssetControl } from "./api/client";
import ChartLayout from "./components/ChartLayout";
import HeaderBar from "./components/HeaderBar";
import PortfolioPage from "./components/PortfolioPage";
import SelectedAssetLivePanel from "./components/SelectedAssetLivePanel";
import SymbolTimeframePicker from "./components/SymbolTimeframePicker";
import { useStore } from "./state/store";
import { toIsoDate } from "./utils/formatting";
import { buildIndicatorsArg } from "./utils/indicators";
export default function App() {
    const { symbol, timeframe, venue, rangeDays, overlays, panels, setSymbol, setTimeframe, setRangeDays, toggleOverlay, togglePanel, } = useStore();
    const [symbols, setSymbols] = useState(["BTC/USDT", "ETH/USDT"]);
    const [rows, setRows] = useState([]);
    const [gaps, setGaps] = useState([]);
    const [crosshair, setCrosshair] = useState(null);
    const [view, setView] = useState("chart");
    const [openPositions, setOpenPositions] = useState([]);
    const [closedTrades, setClosedTrades] = useState([]);
    const [totalNetPnl, setTotalNetPnl] = useState(0);
    const [assetControls, setAssetControls] = useState([]);
    const [chartOpenPositions, setChartOpenPositions] = useState([]);
    const [chartClosedTrades, setChartClosedTrades] = useState([]);
    const [pnlMode, setPnlMode] = useState("sim");
    const activeSymbols = useMemo(() => {
        if (assetControls.length > 0) {
            return assetControls.map((row) => row.symbol);
        }
        return symbols;
    }, [assetControls, symbols]);
    const symbolStatus = useMemo(() => {
        const out = {};
        for (const row of assetControls) {
            out[row.symbol] = row.last_evaluated_state === "stale_data" || row.last_evaluated_state === "runtime_tf_missing" ? "stale" : "ok";
        }
        return out;
    }, [assetControls]);
    const selectedAssetControl = useMemo(() => assetControls.find((row) => row.symbol === symbol), [assetControls, symbol]);
    const selectedAssetOpenPositions = useMemo(() => chartOpenPositions.filter((row) => row.symbol === symbol), [chartOpenPositions, symbol]);
    const timeRange = useMemo(() => {
        const end = new Date();
        const start = new Date(end.getTime() - rangeDays * 24 * 60 * 60 * 1000);
        return { start: toIsoDate(start), end: toIsoDate(end) };
    }, [rangeDays]);
    const indicatorsArg = useMemo(() => buildIndicatorsArg({
        bbands: overlays.bbands,
        ema20: overlays.ema20,
        ema50: overlays.ema50,
        ema200: overlays.ema200,
        rsi: panels.rsi,
        atr: panels.atr,
        bbWidth: panels.bbWidth,
    }), [overlays, panels]);
    useEffect(() => {
        fetchSymbols().then(setSymbols).catch(() => undefined);
    }, []);
    useEffect(() => {
        if (activeSymbols.length === 0)
            return;
        if (!activeSymbols.includes(symbol)) {
            setSymbol(activeSymbols[0]);
        }
    }, [activeSymbols, symbol, setSymbol]);
    useEffect(() => {
        const loadPortfolio = () => {
            fetchOpenPositions({ venue, timeframe: "1m" })
                .then(setOpenPositions)
                .catch(() => setOpenPositions([]));
            fetchClosedTrades({ venue, timeframe: "1m", execution_mode: pnlMode, limit: 1000 })
                .then((payload) => {
                setClosedTrades(payload.rows);
                setTotalNetPnl(payload.total_net_pnl);
            })
                .catch(() => {
                setClosedTrades([]);
                setTotalNetPnl(0);
            });
            fetchAssetControls()
                .then(setAssetControls)
                .catch(() => setAssetControls([]));
        };
        loadPortfolio();
        const timer = window.setInterval(loadPortfolio, 8000);
        return () => window.clearInterval(timer);
    }, [venue, pnlMode]);
    const refreshAssetControls = async () => {
        const rows = await fetchAssetControls();
        setAssetControls(rows);
    };
    const saveAssetControl = async (payload) => {
        await updateAssetControl(payload);
        await refreshAssetControls();
    };
    useEffect(() => {
        fetchCandles({
            symbol,
            timeframe,
            venue,
            start: timeRange.start,
            end: timeRange.end,
            limit: 20000,
        })
            .then((candles) => {
            fetchIndicators({ symbol, timeframe, venue, start: timeRange.start, end: timeRange.end, indicators: indicatorsArg })
                .then((indicatorRows) => {
                if (indicatorRows.length) {
                    setRows(indicatorRows);
                }
                else {
                    setRows(candles);
                }
            })
                .catch(() => setRows(candles));
        })
            .catch(() => setRows([]));
        fetchGaps({ symbol, timeframe, venue, start: timeRange.start, end: timeRange.end })
            .then(setGaps)
            .catch(() => setGaps([]));
        fetchOpenPositions({ symbol, venue, timeframe })
            .then(setChartOpenPositions)
            .catch(() => setChartOpenPositions([]));
        fetchClosedTrades({ symbol, venue, timeframe, limit: 1500 })
            .then((payload) => setChartClosedTrades(payload.rows))
            .catch(() => setChartClosedTrades([]));
    }, [symbol, timeframe, venue, timeRange.start, timeRange.end, indicatorsArg]);
    return (_jsxs("div", { children: [_jsx(HeaderBar, { view: view, onView: setView }), view === "chart" ? (_jsxs(_Fragment, { children: [_jsx(SymbolTimeframePicker, { symbols: activeSymbols, symbol: symbol, timeframe: timeframe, rangeDays: rangeDays, symbolStatus: symbolStatus, onSymbol: setSymbol, onTimeframe: setTimeframe, onRangeDays: setRangeDays }), _jsx(SelectedAssetLivePanel, { symbol: symbol, assetControl: selectedAssetControl, openPositions: selectedAssetOpenPositions }), _jsxs("div", { style: { display: "flex", gap: 12, padding: "8px 12px", borderBottom: "1px solid #22262f", fontSize: 12 }, children: [_jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: overlays.bbands, onChange: () => toggleOverlay("bbands") }), " Bollinger"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: overlays.ema20, onChange: () => toggleOverlay("ema20") }), " EMA20"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: overlays.ema50, onChange: () => toggleOverlay("ema50") }), " EMA50"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: overlays.ema200, onChange: () => toggleOverlay("ema200") }), " EMA200"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: panels.rsi, onChange: () => togglePanel("rsi") }), " RSI"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: panels.atr, onChange: () => togglePanel("atr") }), " ATR"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: panels.bbWidth, onChange: () => togglePanel("bbWidth") }), " BB Width"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: panels.volumeProfile, onChange: () => togglePanel("volumeProfile") }), " Volume Profile"] })] }), _jsx(ChartLayout, { rows: rows, gaps: gaps, overlays: overlays, panels: panels, openPositions: chartOpenPositions, closedTrades: chartClosedTrades, crosshair: crosshair, setCrosshair: setCrosshair })] })) : (_jsx(PortfolioPage, { openPositions: openPositions, closedTrades: closedTrades, totalNetPnl: totalNetPnl, assetControls: assetControls, pnlMode: pnlMode, onPnlMode: setPnlMode, onSaveAssetControl: saveAssetControl }))] }));
}
