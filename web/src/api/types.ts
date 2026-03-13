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
  bb_deviation?: number | null;
  entry_deviation?: number | null;
  slope_now?: number | null;
  slope_lookback?: number | null;
  flatten_ratio?: number | null;
  long_rounding?: boolean | null;
  short_rounding?: boolean | null;
  long_entry_signal?: boolean | null;
  short_entry_signal?: boolean | null;
  engine_ema_fast?: number | null;
  engine_ema_slow?: number | null;
  engine_slope_lookback_bars?: number | null;
  engine_diag_status?: string | null;
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
  entry_spot_price?: number | null;
  exit_spot_price?: number | null;
  entry_price: number;
  exit_price: number;
  entry_slippage_bps?: number | null;
  entry_slippage_usd?: number | null;
  exit_slippage_bps?: number | null;
  exit_slippage_usd?: number | null;
  total_slippage_usd?: number | null;
  qty: number;
  gross_pnl: number;
  fees: number;
  net_pnl: number;
  return_pct: number;
  exit_reason: string;
  hold_bars_at_exit?: number | null;
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
  timeframe: string;
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
  tuning_params: Record<string, number | string | boolean>;
  tuning_version?: number | null;
  tuning_note?: string | null;
  tuning_source?: string | null;
  tuning_updated_by?: string | null;
  tuning_updated_at?: string | null;
  live_balance?: {
    status: string;
    can_long?: boolean;
    can_short?: boolean;
    base_free?: number;
    quote_free?: number;
    price?: number;
    required_notional?: number;
    required_base_qty?: number;
    base_value_ratio?: number;
    note?: string;
  } | null;
};

export type AssetTuningVersion = {
  id: number;
  symbol: string;
  timeframe: string;
  version: number;
  params_json: Record<string, number>;
  note?: string | null;
  source?: string | null;
  updated_by?: string | null;
  is_active: boolean;
  created_at: string;
};

export type AssetValueBalanceResponse = {
  symbol: string;
  action: string;
  order_side?: string | null;
  qty: number;
  raw_price?: number | null;
  fill_price?: number | null;
  fill_notional_usd?: number | null;
  fee_usd?: number | null;
  pre_base_qty: number;
  pre_quote_qty: number;
  post_base_qty: number;
  post_quote_qty: number;
  base_value_ratio_before?: number | null;
  base_value_ratio_after?: number | null;
  note: string;
};

export type AssetEngineLog = {
  id: number;
  symbol: string;
  timeframe: string;
  state: string;
  note?: string | null;
  created_at: string;
};

export type RiskPolicySettings = {
  risk_budget_policy: "per_symbol" | "portfolio";
  portfolio_soft_risk_limit_usd: number;
};

export type PortfolioBalanceAsset = {
  asset: string;
  free: number;
  usd_price?: number | null;
  value_usd: number;
};

export type PortfolioBalancesSnapshot = {
  mode: "sim" | "live";
  as_of: string;
  total_value_usd: number;
  cash_value_usd: number;
  asset_value_usd: number;
  cash_ratio: number;
  asset_ratio: number;
  note?: string | null;
  assets: PortfolioBalanceAsset[];
};

export type SimWalletAugmentResponse = {
  symbol: string;
  bucket: "cash" | "asset";
  amount_usd: number;
  cash_adjustment_usd: number;
  asset_adjustment_usd: number;
  note: string;
};

export type ModeSwitchResponse = {
  from_mode: "sim" | "live";
  target_mode: "sim" | "live";
  attempted_force_close: number;
  closed_count: number;
  switched_controls: number;
  note: string;
};

export type LiveReadiness = {
  venue: string;
  sandbox: boolean;
  api_key_present: boolean;
  api_secret_present: boolean;
  real_adapter_enabled_any: boolean;
  live_order_enabled_any: boolean;
  live_ack_required_any: boolean;
  live_ack_satisfied_any: boolean;
  balance_readable: boolean;
  balance_error?: string | null;
  note?: string | null;
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
