import type { AssetControl, AssetEngineLog, Candle, CatchupStatusRow, ClosedTradesResponse, Gap, IndicatorRow, OpenPosition, RiskPolicySettings } from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";
export const API_BASE_URL = BASE;

function qs(params: Record<string, string | number | undefined>) {
  const out = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== "") {
      out.set(k, String(v));
    }
  });
  return out.toString();
}

export async function fetchSymbols(): Promise<string[]> {
  const response = await fetch(`${BASE}/symbols`);
  if (!response.ok) throw new Error("Failed to fetch symbols");
  const body = (await response.json()) as { symbols: string[] };
  return body.symbols;
}

export async function fetchCandles(args: {
  symbol: string;
  timeframe: string;
  venue: string;
  start?: string;
  end?: string;
  limit?: number;
}): Promise<Candle[]> {
  const response = await fetch(`${BASE}/candles?${qs(args)}`);
  if (!response.ok) throw new Error("Failed to fetch candles");
  return (await response.json()) as Candle[];
}

export async function fetchIndicators(args: {
  symbol: string;
  timeframe: string;
  venue: string;
  start?: string;
  end?: string;
  indicators: string;
}): Promise<IndicatorRow[]> {
  const response = await fetch(`${BASE}/indicators?${qs(args)}`);
  if (!response.ok) throw new Error("Failed to fetch indicators");
  const body = (await response.json()) as { rows: IndicatorRow[] };
  return body.rows;
}

export async function fetchGaps(args: {
  symbol: string;
  timeframe: string;
  venue: string;
  start?: string;
  end?: string;
}): Promise<Gap[]> {
  const response = await fetch(`${BASE}/gaps?${qs(args)}`);
  if (!response.ok) throw new Error("Failed to fetch gaps");
  return (await response.json()) as Gap[];
}

export async function fetchOpenPositions(args: {
  symbol?: string;
  venue?: string;
  timeframe?: string;
  execution_mode?: "sim" | "live";
}): Promise<OpenPosition[]> {
  const response = await fetch(`${BASE}/positions/open?${qs(args)}`);
  if (!response.ok) throw new Error("Failed to fetch open positions");
  return (await response.json()) as OpenPosition[];
}

export async function fetchClosedTrades(args: {
  symbol?: string;
  venue?: string;
  timeframe?: string;
  execution_mode?: "sim" | "live";
  limit?: number;
}): Promise<ClosedTradesResponse> {
  const response = await fetch(`${BASE}/trades/closed?${qs(args)}`);
  if (!response.ok) throw new Error("Failed to fetch closed trades");
  return (await response.json()) as ClosedTradesResponse;
}

export async function fetchAssetControls(): Promise<AssetControl[]> {
  const response = await fetch(`${BASE}/control-plane/assets`);
  if (!response.ok) throw new Error("Failed to fetch asset controls");
  return (await response.json()) as AssetControl[];
}

export async function updateAssetControl(args: {
  symbol: string;
  enabled?: boolean;
  execution_mode?: "sim" | "live";
  trade_side?: "long_only" | "long_short" | "short_only";
  soft_risk_limit_usd?: number;
}): Promise<AssetControl> {
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
  if (!response.ok) throw new Error("Failed to update asset control");
  return (await response.json()) as AssetControl;
}

export async function fetchAssetLogs(args: { symbol: string; limit?: number }): Promise<AssetEngineLog[]> {
  const response = await fetch(`${BASE}/control-plane/assets/${encodeURIComponent(args.symbol)}/logs?${qs({ limit: args.limit ?? 100 })}`);
  if (!response.ok) throw new Error("Failed to fetch asset logs");
  return (await response.json()) as AssetEngineLog[];
}

export async function fetchRiskPolicySettings(): Promise<RiskPolicySettings> {
  const response = await fetch(`${BASE}/control-plane/risk-policy`);
  if (!response.ok) throw new Error("Failed to fetch risk policy settings");
  return (await response.json()) as RiskPolicySettings;
}

export async function updateRiskPolicySettings(args: {
  risk_budget_policy?: "per_symbol" | "portfolio";
  portfolio_soft_risk_limit_usd?: number;
}): Promise<RiskPolicySettings> {
  const response = await fetch(`${BASE}/control-plane/risk-policy`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      risk_budget_policy: args.risk_budget_policy,
      portfolio_soft_risk_limit_usd: args.portfolio_soft_risk_limit_usd,
    }),
  });
  if (!response.ok) throw new Error("Failed to update risk policy settings");
  return (await response.json()) as RiskPolicySettings;
}

export async function fetchCatchupStatus(args: {
  symbol?: string;
  timeframe?: string;
  venue?: string;
} = {}): Promise<CatchupStatusRow[]> {
  const response = await fetch(`${BASE}/ingestion/catchup-status?${qs(args)}`);
  if (!response.ok) throw new Error("Failed to fetch ingestion catchup status");
  return (await response.json()) as CatchupStatusRow[];
}
