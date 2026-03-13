from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CandleOut(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class GapOut(BaseModel):
    start_ts: datetime
    end_ts: datetime


class BackfillRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    venue: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    lookback_days: int | None = None


class BackfillResult(BaseModel):
    symbol: str
    timeframe: str
    venue: str
    inserted: int
    remaining_gaps: int


class OpenPositionOut(BaseModel):
    id: int
    symbol: str
    venue: str
    timeframe: str
    execution_mode: str
    trade_side: str
    entry_ts: datetime
    entry_price: float
    qty: float
    stop_price: float | None
    take_profit_price: float | None
    hold_bars: int
    last_price: float | None
    unrealized_pnl: float | None
    unrealized_return_pct: float | None


class ClosedTradeOut(BaseModel):
    id: int
    symbol: str
    venue: str
    timeframe: str
    execution_mode: str
    trade_side: str
    entry_ts: datetime
    exit_ts: datetime
    entry_spot_price: float | None = None
    exit_spot_price: float | None = None
    entry_price: float
    exit_price: float
    entry_slippage_bps: float | None = None
    entry_slippage_usd: float | None = None
    exit_slippage_bps: float | None = None
    exit_slippage_usd: float | None = None
    total_slippage_usd: float | None = None
    qty: float
    gross_pnl: float
    fees: float
    net_pnl: float
    return_pct: float
    exit_reason: str
    hold_bars_at_exit: int | None = None


class ClosedTradesResponse(BaseModel):
    count: int
    total_net_pnl: float
    total_gross_pnl: float
    rows: list[ClosedTradeOut]


class RiskLimitOut(BaseModel):
    soft_limit_usd: float
    current_risk_usd: float
    remaining_risk_usd: float
    open_positions: int


class RiskLimitUpdate(BaseModel):
    soft_limit_usd: float = Field(ge=0.0)


class RiskPolicyOut(BaseModel):
    risk_budget_policy: str
    portfolio_soft_risk_limit_usd: float


class TraderConfigReloadStatusOut(BaseModel):
    last_status: str | None
    last_event_ts: datetime | None
    last_event_note: str | None
    last_success_ts: datetime | None
    last_failure_ts: datetime | None


class LiveReadinessOut(BaseModel):
    venue: str
    sandbox: bool
    api_key_present: bool
    api_secret_present: bool
    real_adapter_enabled_any: bool
    live_order_enabled_any: bool
    live_ack_required_any: bool
    live_ack_satisfied_any: bool
    balance_readable: bool
    balance_error: str | None = None
    note: str | None = None


class RiskPolicyUpdate(BaseModel):
    risk_budget_policy: str | None = None
    portfolio_soft_risk_limit_usd: float | None = Field(default=None, ge=0.0)


class AssetControlOut(BaseModel):
    symbol: str
    timeframe: str
    enabled: bool
    execution_mode: str
    trade_side: str
    bb_entry_mode: str
    soft_risk_limit_usd: float
    current_risk_usd: float
    last_run_ts: datetime | None
    next_run_ts: datetime | None
    last_evaluated_state: str | None
    last_evaluated_note: str | None
    tuning_params: dict[str, float | int | str | bool]
    tuning_version: int | None = None
    tuning_note: str | None = None
    tuning_source: str | None = None
    tuning_updated_by: str | None = None
    tuning_updated_at: datetime | None = None
    live_balance: dict[str, float | str | bool] | None = None


class AssetControlUpdate(BaseModel):
    enabled: bool | None = None
    execution_mode: str | None = None
    trade_side: str | None = None
    soft_risk_limit_usd: float | None = Field(default=None, ge=0.0)


class AssetTuningUpdate(BaseModel):
    bb_length: int | None = Field(default=None, ge=2)
    bb_stdev: float | None = Field(default=None, gt=0.0)
    atr_length: int | None = Field(default=None, ge=2)
    ema_fast: int | None = Field(default=None, ge=2)
    ema_slow: int | None = Field(default=None, ge=2)
    bb_entry_deviation: float | None = Field(default=None, ge=0.0)
    bb_exit_deviation: float | None = Field(default=None, ge=0.0)
    slope_lookback_bars: int | None = Field(default=None, ge=1)
    slope_flatten_factor: float | None = Field(default=None, ge=0.0)
    stop_atr: float | None = Field(default=None, gt=0.0)
    take_profit_atr: float | None = Field(default=None, gt=0.0)
    max_hold_bars: int | None = Field(default=None, ge=1)
    min_hold_bars: int | None = Field(default=None, ge=0)
    max_take_profit_pct: float | None = Field(default=None, ge=0.0)
    note: str | None = Field(default=None, max_length=512)
    source: str | None = Field(default=None, max_length=64)
    updated_by: str | None = Field(default=None, max_length=128)


class AssetTuningVersionOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    version: int
    params_json: dict[str, float | int]
    note: str | None
    source: str | None
    updated_by: str | None
    is_active: bool
    created_at: datetime


class AssetEngineLogOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    state: str
    note: str | None
    created_at: datetime


class AssetValueBalanceRequest(BaseModel):
    target_base_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    tolerance_bps: float = Field(default=25.0, ge=0.0)


class AssetValueBalanceOut(BaseModel):
    symbol: str
    action: str
    order_side: str | None
    qty: float
    raw_price: float | None
    fill_price: float | None
    fill_notional_usd: float | None
    fee_usd: float | None
    pre_base_qty: float
    pre_quote_qty: float
    post_base_qty: float
    post_quote_qty: float
    base_value_ratio_before: float | None
    base_value_ratio_after: float | None
    note: str


class SimWalletAugmentRequest(BaseModel):
    bucket: str = Field(default="cash")
    amount_usd: float = Field(ge=0.0)


class SimWalletAugmentOut(BaseModel):
    symbol: str
    bucket: str
    amount_usd: float
    cash_adjustment_usd: float
    asset_adjustment_usd: float
    note: str


class ModeSwitchRequest(BaseModel):
    from_mode: str
    target_mode: str
    force_close_open_positions: bool = True
    venue: str | None = None


class ModeSwitchOut(BaseModel):
    from_mode: str
    target_mode: str
    attempted_force_close: int
    closed_count: int
    switched_controls: int
    note: str


class CatchupStatusOut(BaseModel):
    symbol: str
    timeframe: str
    venue: str
    latest_ts: datetime | None
    target_end_ts: datetime
    attempted_start_ts: datetime | None
    attempted_end_ts: datetime | None
    bars_behind_before_jump: int
    bars_attempted_this_cycle: int
    remaining_after_attempt_bars: int
    catchup_progress_pct: float
    unresolved_gap_count: int
    unresolved_gap_bars_estimate: int
    last_gap_scan_ts: datetime | None
    is_caught_up: bool


class PortfolioBalanceAssetOut(BaseModel):
    asset: str
    free: float
    usd_price: float | None = None
    value_usd: float


class PortfolioBalancesOut(BaseModel):
    mode: str
    as_of: datetime
    total_value_usd: float
    cash_value_usd: float
    asset_value_usd: float
    cash_ratio: float
    asset_ratio: float
    note: str | None = None
    assets: list[PortfolioBalanceAssetOut]
