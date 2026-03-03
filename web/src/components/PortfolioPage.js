import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchAssetLogs } from "../api/client";
import { num } from "../utils/formatting";
function toPoints(values, width, height) {
    if (values.length === 0)
        return "";
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const span = Math.max(maxV - minV, 1e-9);
    return values
        .map((v, i) => {
        const x = values.length === 1 ? width / 2 : (i / (values.length - 1)) * width;
        const y = height - ((v - minV) / span) * height;
        return `${x},${y}`;
    })
        .join(" ");
}
export default function PortfolioPage({ openPositions, closedTrades, totalNetPnl, assetControls, pnlMode, onPnlMode, onSaveAssetControl }) {
    const [draftLimits, setDraftLimits] = useState({});
    const [saving, setSaving] = useState(false);
    const [logSymbol, setLogSymbol] = useState(null);
    const [logRows, setLogRows] = useState([]);
    const [logsLoading, setLogsLoading] = useState(false);
    const [nowMs, setNowMs] = useState(() => Date.now());
    const [flashUntil, setFlashUntil] = useState({});
    const prevSignalsRef = useRef({});
    useEffect(() => {
        const next = {};
        for (const row of assetControls) {
            next[row.symbol] = String(row.soft_risk_limit_usd);
        }
        setDraftLimits(next);
    }, [assetControls]);
    useEffect(() => {
        const timer = window.setInterval(() => {
            setNowMs(Date.now());
        }, 1000);
        return () => window.clearInterval(timer);
    }, []);
    useEffect(() => {
        const now = Date.now();
        const nextSignals = {};
        const flashUpdates = {};
        for (const row of assetControls) {
            const signal = {
                lastRun: row.last_run_ts ?? "",
                nextRun: row.next_run_ts ?? "",
                risk: row.current_risk_usd,
            };
            const prev = prevSignalsRef.current[row.symbol];
            if (prev) {
                if (prev.lastRun !== signal.lastRun)
                    flashUpdates[`${row.symbol}:last`] = now + 900;
                if (prev.nextRun !== signal.nextRun)
                    flashUpdates[`${row.symbol}:next`] = now + 900;
                if (prev.risk !== signal.risk)
                    flashUpdates[`${row.symbol}:risk`] = now + 900;
            }
            nextSignals[row.symbol] = signal;
        }
        prevSignalsRef.current = nextSignals;
        if (Object.keys(flashUpdates).length > 0) {
            setFlashUntil((prev) => ({ ...prev, ...flashUpdates }));
        }
    }, [assetControls]);
    const cellPulseStyle = (key) => ({
        display: "inline-block",
        opacity: flashUntil[key] && flashUntil[key] > nowMs ? 0.45 : 1,
        transition: "opacity 650ms ease",
    });
    const parseApiTimestamp = (value) => {
        if (!value)
            return null;
        const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
        const parsed = new Date(normalized);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    };
    const formatCountdown = (nextRunTs) => {
        const target = parseApiTimestamp(nextRunTs);
        if (!target)
            return "-";
        const targetMs = target.getTime();
        const remaining = Math.ceil((targetMs - nowMs) / 1000);
        if (!Number.isFinite(remaining))
            return "-";
        return remaining > 0 ? `${remaining}s` : "due";
    };
    const cumulative = useMemo(() => {
        const ordered = [...closedTrades].reverse();
        let running = 0;
        return ordered.map((trade) => {
            running += trade.net_pnl;
            return running;
        });
    }, [closedTrades]);
    const pnlPoints = useMemo(() => toPoints(cumulative, 860, 160), [cumulative]);
    return (_jsxs("div", { style: { padding: 12, display: "grid", gap: 14 }, children: [_jsxs("div", { style: { display: "flex", gap: 12, fontSize: 13 }, children: [_jsxs("strong", { children: ["Open Positions: ", openPositions.length] }), _jsxs("strong", { children: ["Closed Trades: ", closedTrades.length] }), _jsxs("strong", { children: ["Total Net P&L: ", num(totalNetPnl, 4)] })] }), _jsxs("section", { style: { border: "1px solid #22262f", borderRadius: 6 }, children: [_jsx("div", { style: { padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }, children: "Control Plane" }), _jsx("div", { style: { overflowX: "auto" }, children: _jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12 }, children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Asset" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Run/Pause" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Mode" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Side" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Soft Risk" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Current Risk" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Last Run" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Next Run" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Tuning Params" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Logs" })] }) }), _jsx("tbody", { children: assetControls.map((row) => (_jsxs("tr", { style: { borderTop: "1px solid #1b1f29" }, children: [_jsx("td", { style: { padding: 8 }, children: row.symbol }), _jsx("td", { style: { padding: 8 }, children: _jsxs("div", { style: { display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }, children: [_jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                                setSaving(true);
                                                                try {
                                                                    await onSaveAssetControl({ symbol: row.symbol, enabled: true });
                                                                }
                                                                finally {
                                                                    setSaving(false);
                                                                }
                                                            }, style: {
                                                                padding: "3px 8px",
                                                                border: "none",
                                                                borderRight: "1px solid #2d3340",
                                                                background: row.enabled ? "#2f5f3a" : "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                            }, children: "Run" }), _jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                                setSaving(true);
                                                                try {
                                                                    await onSaveAssetControl({ symbol: row.symbol, enabled: false });
                                                                }
                                                                finally {
                                                                    setSaving(false);
                                                                }
                                                            }, style: {
                                                                padding: "3px 8px",
                                                                border: "none",
                                                                background: !row.enabled ? "#5f2f2f" : "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                            }, children: "Pause" })] }) }), _jsx("td", { style: { padding: 8 }, children: _jsxs("div", { style: { display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }, children: [_jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                                setSaving(true);
                                                                try {
                                                                    await onSaveAssetControl({ symbol: row.symbol, trade_side: "long_only" });
                                                                }
                                                                finally {
                                                                    setSaving(false);
                                                                }
                                                            }, style: {
                                                                padding: "3px 8px",
                                                                border: "none",
                                                                borderRight: "1px solid #2d3340",
                                                                background: row.trade_side === "long_only" ? "#2d3340" : "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                            }, children: "Long" }), _jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                                setSaving(true);
                                                                try {
                                                                    await onSaveAssetControl({ symbol: row.symbol, trade_side: "long_short" });
                                                                }
                                                                finally {
                                                                    setSaving(false);
                                                                }
                                                            }, style: {
                                                                padding: "3px 8px",
                                                                border: "none",
                                                                borderRight: "1px solid #2d3340",
                                                                background: row.trade_side === "long_short" ? "#2d3340" : "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                            }, children: "Both" }), _jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                                setSaving(true);
                                                                try {
                                                                    await onSaveAssetControl({ symbol: row.symbol, trade_side: "short_only" });
                                                                }
                                                                finally {
                                                                    setSaving(false);
                                                                }
                                                            }, style: {
                                                                padding: "3px 8px",
                                                                border: "none",
                                                                background: row.trade_side === "short_only" ? "#2d3340" : "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                            }, children: "Short" })] }) }), _jsx("td", { style: { padding: 8 }, children: _jsxs("div", { style: { display: "inline-flex", border: "1px solid #2d3340", borderRadius: 6, overflow: "hidden" }, children: [_jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                                setSaving(true);
                                                                try {
                                                                    await onSaveAssetControl({ symbol: row.symbol, execution_mode: "sim" });
                                                                }
                                                                finally {
                                                                    setSaving(false);
                                                                }
                                                            }, style: {
                                                                padding: "3px 8px",
                                                                border: "none",
                                                                borderRight: "1px solid #2d3340",
                                                                background: row.execution_mode === "sim" ? "#2d3340" : "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                            }, children: "Sim" }), _jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                                setSaving(true);
                                                                try {
                                                                    await onSaveAssetControl({ symbol: row.symbol, execution_mode: "live" });
                                                                }
                                                                finally {
                                                                    setSaving(false);
                                                                }
                                                            }, style: {
                                                                padding: "3px 8px",
                                                                border: "none",
                                                                background: row.execution_mode === "live" ? "#2d3340" : "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                            }, children: "Active" })] }) }), _jsxs("td", { style: { textAlign: "right", padding: 8 }, children: [_jsx("input", { type: "number", min: 0, step: 1, value: draftLimits[row.symbol] ?? String(row.soft_risk_limit_usd), onChange: (e) => setDraftLimits((prev) => ({ ...prev, [row.symbol]: e.target.value })), style: { width: 90, padding: "3px 6px", background: "#0f131c", color: "inherit", border: "1px solid #2d3340", borderRadius: 4 } }), _jsx("button", { type: "button", disabled: saving, onClick: async () => {
                                                            const parsed = Number(draftLimits[row.symbol]);
                                                            if (!Number.isFinite(parsed) || parsed < 0)
                                                                return;
                                                            setSaving(true);
                                                            try {
                                                                await onSaveAssetControl({ symbol: row.symbol, soft_risk_limit_usd: parsed });
                                                            }
                                                            finally {
                                                                setSaving(false);
                                                            }
                                                        }, style: { marginLeft: 6, padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "#2d3340", color: "inherit", cursor: "pointer" }, children: "Set" })] }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: _jsx("span", { style: cellPulseStyle(`${row.symbol}:risk`), children: num(row.current_risk_usd, 4) }) }), _jsxs("td", { style: { padding: 8 }, children: [_jsx("span", { style: cellPulseStyle(`${row.symbol}:last`), children: parseApiTimestamp(row.last_run_ts)?.toLocaleString() ?? "-" }), _jsx("span", { style: { color: "#9ca3af", marginLeft: 6 }, children: row.last_evaluated_state ? `(${row.last_evaluated_state})` : "" })] }), _jsx("td", { style: { padding: 8 }, children: _jsx("span", { style: cellPulseStyle(`${row.symbol}:next`), children: formatCountdown(row.next_run_ts) }) }), _jsx("td", { style: { padding: 8, maxWidth: 360, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }, children: Object.entries(row.tuning_params).map(([k, v]) => `${k}=${v}`).join(", ") }), _jsx("td", { style: { padding: 8 }, children: _jsx("button", { type: "button", onClick: async () => {
                                                        setLogSymbol(row.symbol);
                                                        setLogsLoading(true);
                                                        try {
                                                            const logs = await fetchAssetLogs({ symbol: row.symbol, limit: 200 });
                                                            setLogRows(logs);
                                                        }
                                                        finally {
                                                            setLogsLoading(false);
                                                        }
                                                    }, style: { padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "#2d3340", color: "inherit", cursor: "pointer" }, children: "View Logs" }) })] }, row.symbol))) })] }) })] }), logSymbol && (_jsx("div", { style: {
                    position: "fixed",
                    inset: 0,
                    background: "rgba(0,0,0,0.55)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    zIndex: 50,
                }, onClick: () => setLogSymbol(null), children: _jsxs("div", { onClick: (e) => e.stopPropagation(), style: {
                        width: "min(980px, 92vw)",
                        maxHeight: "78vh",
                        overflow: "hidden",
                        background: "#0f131c",
                        border: "1px solid #2d3340",
                        borderRadius: 8,
                        display: "grid",
                        gridTemplateRows: "auto 1fr",
                    }, children: [_jsxs("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", borderBottom: "1px solid #2d3340" }, children: [_jsxs("strong", { children: ["Runtime Logs \u2014 ", logSymbol] }), _jsx("button", { type: "button", onClick: () => setLogSymbol(null), style: { padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: "transparent", color: "inherit", cursor: "pointer" }, children: "Close" })] }), _jsx("div", { style: { overflow: "auto" }, children: logsLoading ? (_jsx("div", { style: { padding: 12, fontSize: 12 }, children: "Loading logs..." })) : logRows.length === 0 ? (_jsx("div", { style: { padding: 12, fontSize: 12 }, children: "No logs available." })) : (_jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12 }, children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Timestamp" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "State" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Note" })] }) }), _jsx("tbody", { children: logRows.map((row) => (_jsxs("tr", { style: { borderTop: "1px solid #1b1f29" }, children: [_jsx("td", { style: { padding: 8 }, children: new Date(row.created_at).toLocaleString() }), _jsx("td", { style: { padding: 8 }, children: row.state }), _jsx("td", { style: { padding: 8 }, children: row.note ?? "-" })] }, row.id))) })] })) })] }) })), _jsxs("section", { style: { border: "1px solid #22262f", borderRadius: 6 }, children: [_jsx("div", { style: { padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }, children: "Open Positions" }), _jsx("div", { style: { overflowX: "auto" }, children: _jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12 }, children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Symbol" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Side" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Entry" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Last" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Qty" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Unrealized P&L" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Unrealized %" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Hold Bars" })] }) }), _jsx("tbody", { children: openPositions.length === 0 ? (_jsx("tr", { children: _jsx("td", { style: { padding: 8 }, colSpan: 8, children: "No open positions." }) })) : (openPositions.map((row) => (_jsxs("tr", { style: { borderTop: "1px solid #1b1f29" }, children: [_jsx("td", { style: { padding: 8 }, children: row.symbol }), _jsx("td", { style: { padding: 8 }, children: row.trade_side === "short" ? "Short" : "Long" }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.entry_price, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.last_price, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.qty, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.unrealized_pnl, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.unrealized_return_pct, 3) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: row.hold_bars })] }, row.id)))) })] }) })] }), _jsxs("section", { style: { border: "1px solid #22262f", borderRadius: 6 }, children: [_jsxs("div", { style: { padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600, display: "flex", justifyContent: "space-between" }, children: [_jsx("span", { children: "Historical Net P&L" }), _jsxs("div", { style: { display: "flex", gap: 8 }, children: [_jsx("button", { type: "button", onClick: () => onPnlMode("sim"), style: { padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: pnlMode === "sim" ? "#2d3340" : "transparent", color: "inherit", cursor: "pointer" }, children: "Sim" }), _jsx("button", { type: "button", onClick: () => onPnlMode("live"), style: { padding: "3px 8px", borderRadius: 4, border: "1px solid #2d3340", background: pnlMode === "live" ? "#2d3340" : "transparent", color: "inherit", cursor: "pointer" }, children: "Real" })] })] }), _jsx("div", { style: { padding: 10 }, children: cumulative.length === 0 ? (_jsx("div", { style: { fontSize: 12 }, children: "No closed trades yet." })) : (_jsx("svg", { width: "100%", viewBox: "0 0 860 170", style: { display: "block", background: "#0f131c", borderRadius: 6 }, children: _jsx("polyline", { points: pnlPoints, fill: "none", stroke: "#4ea1ff", strokeWidth: 2 }) })) })] }), _jsxs("section", { style: { border: "1px solid #22262f", borderRadius: 6 }, children: [_jsx("div", { style: { padding: "8px 10px", borderBottom: "1px solid #22262f", fontWeight: 600 }, children: "Closed Trades" }), _jsx("div", { style: { overflowX: "auto" }, children: _jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12 }, children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Exit Time" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Symbol" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Mode" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Side" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Entry" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Exit" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Qty" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Net P&L" }), _jsx("th", { style: { textAlign: "right", padding: 8 }, children: "Return %" }), _jsx("th", { style: { textAlign: "left", padding: 8 }, children: "Reason" })] }) }), _jsx("tbody", { children: closedTrades.length === 0 ? (_jsx("tr", { children: _jsx("td", { style: { padding: 8 }, colSpan: 10, children: "No closed trades." }) })) : (closedTrades.map((row) => (_jsxs("tr", { style: { borderTop: "1px solid #1b1f29" }, children: [_jsx("td", { style: { padding: 8 }, children: new Date(row.exit_ts).toLocaleString() }), _jsx("td", { style: { padding: 8 }, children: row.symbol }), _jsx("td", { style: { padding: 8 }, children: row.execution_mode === "sim" ? "Sim" : "Real" }), _jsx("td", { style: { padding: 8 }, children: row.trade_side === "short" ? "Short" : "Long" }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.entry_price, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.exit_price, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.qty, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.net_pnl, 6) }), _jsx("td", { style: { textAlign: "right", padding: 8 }, children: num(row.return_pct, 3) }), _jsx("td", { style: { padding: 8 }, children: row.exit_reason })] }, row.id)))) })] }) })] })] }));
}
