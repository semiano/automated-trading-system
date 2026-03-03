const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
function qs(params) {
    const out = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== "") {
            out.set(k, String(v));
        }
    });
    return out.toString();
}
export async function fetchSymbols() {
    const response = await fetch(`${BASE}/symbols`);
    if (!response.ok)
        throw new Error("Failed to fetch symbols");
    const body = (await response.json());
    return body.symbols;
}
export async function fetchCandles(args) {
    const response = await fetch(`${BASE}/candles?${qs(args)}`);
    if (!response.ok)
        throw new Error("Failed to fetch candles");
    return (await response.json());
}
export async function fetchIndicators(args) {
    const response = await fetch(`${BASE}/indicators?${qs(args)}`);
    if (!response.ok)
        throw new Error("Failed to fetch indicators");
    const body = (await response.json());
    return body.rows;
}
export async function fetchGaps(args) {
    const response = await fetch(`${BASE}/gaps?${qs(args)}`);
    if (!response.ok)
        throw new Error("Failed to fetch gaps");
    return (await response.json());
}
export async function fetchOpenPositions(args) {
    const response = await fetch(`${BASE}/positions/open?${qs(args)}`);
    if (!response.ok)
        throw new Error("Failed to fetch open positions");
    return (await response.json());
}
export async function fetchClosedTrades(args) {
    const response = await fetch(`${BASE}/trades/closed?${qs(args)}`);
    if (!response.ok)
        throw new Error("Failed to fetch closed trades");
    return (await response.json());
}
export async function fetchAssetControls() {
    const response = await fetch(`${BASE}/control-plane/assets`);
    if (!response.ok)
        throw new Error("Failed to fetch asset controls");
    return (await response.json());
}
export async function updateAssetControl(args) {
    const response = await fetch(`${BASE}/control-plane/assets/${encodeURIComponent(args.symbol)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            enabled: args.enabled,
            execution_mode: args.execution_mode,
            trade_side: args.trade_side,
            soft_risk_limit_usd: args.soft_risk_limit_usd,
        }),
    });
    if (!response.ok)
        throw new Error("Failed to update asset control");
    return (await response.json());
}
export async function fetchAssetLogs(args) {
    const response = await fetch(`${BASE}/control-plane/assets/${encodeURIComponent(args.symbol)}/logs?${qs({ limit: args.limit ?? 100 })}`);
    if (!response.ok)
        throw new Error("Failed to fetch asset logs");
    return (await response.json());
}
