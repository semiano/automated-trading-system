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
  mom_roc?: number | null;
  swing_pivot_low?: boolean | null;
  swing_pivot_high?: boolean | null;
  swing_long_ready?: boolean | null;
  swing_short_ready?: boolean | null;
};

export type Gap = {
  start_ts: string;
  end_ts: string;
};

export type OpenPosition = {
  id: number;
  symbol: string;
  venue: string;
  timeframe: string;
  execution_mode: "sim" | "live";
  trade_side: "long" | "short";
  entry_ts: string;
  entry_price: number;
  qty: number;
  stop_price?: number | null;
  take_profit_price?: number | null;
  hold_bars: number;
  last_price?: number | null;
  unrealized_pnl?: number | null;
  unrealized_return_pct?: number | null;
};

export type ClosedTrade = {
  id: number;
  symbol: string;
  venue: string;
  timeframe: string;
  execution_mode: "sim" | "live";
  trade_side: "long" | "short";
  entry_ts: string;
  exit_ts: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  gross_pnl: number;
  fees: number;
  net_pnl: number;
  return_pct: number;
  exit_reason: string;
};

export type ClosedTradesResponse = {
  count: number;
  total_net_pnl: number;
  total_gross_pnl: number;
  rows: ClosedTrade[];
};

export type PortfolioRiskLimit = {
  soft_limit_usd: number;
  current_risk_usd: number;
  remaining_risk_usd: number;
  open_positions: number;
};

export type AssetControl = {
  symbol: string;
  enabled: boolean;
  execution_mode: "sim" | "live";
  trade_side: "long_only" | "long_short" | "short_only";
  bb_entry_mode: "off" | "touch_revert" | "range_revert";
  soft_risk_limit_usd: number;
  current_risk_usd: number;
  last_run_ts?: string | null;
  next_run_ts?: string | null;
  last_evaluated_state?: string | null;
  last_evaluated_note?: string | null;
  tuning_params: Record<string, number>;
};

export type AssetEngineLog = {
  id: number;
  symbol: string;
  state: string;
  note?: string | null;
  created_at: string;
};

export type RiskPolicySettings = {
  risk_budget_policy: "per_symbol" | "portfolio";
  portfolio_soft_risk_limit_usd: number;
};

export type CatchupStatusRow = {
  symbol: string;
  timeframe: string;
  venue: string;
  latest_ts?: string | null;
  target_end_ts: string;
  attempted_start_ts?: string | null;
  attempted_end_ts?: string | null;
  bars_behind_before_jump: number;
  bars_attempted_this_cycle: number;
  remaining_after_attempt_bars: number;
  catchup_progress_pct: number;
  unresolved_gap_count: number;
  unresolved_gap_bars_estimate: number;
  last_gap_scan_ts?: string | null;
  is_caught_up: boolean;
};
