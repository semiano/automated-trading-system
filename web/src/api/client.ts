import type { Candle, Gap, IndicatorRow } from "./types";

const BASE = "http://localhost:8000/api/v1";

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
