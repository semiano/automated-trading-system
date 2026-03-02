export type Candle = {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type IndicatorRow = Candle & {
  bb_lower?: number | null;
  bb_mid?: number | null;
  bb_upper?: number | null;
  bb_width?: number | null;
  bb_percent_b?: number | null;
  rsi?: number | null;
  atr?: number | null;
  ema20?: number | null;
  ema50?: number | null;
  ema200?: number | null;
  volume_sma?: number | null;
  vwap?: number | null;
};

export type Gap = {
  start_ts: string;
  end_ts: string;
};
