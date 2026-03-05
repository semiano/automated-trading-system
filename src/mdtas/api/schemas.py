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
    entry_price: float
    exit_price: float
    qty: float
    gross_pnl: float
    fees: float
    net_pnl: float
    return_pct: float
    exit_reason: str


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


class RiskPolicyUpdate(BaseModel):
    risk_budget_policy: str | None = None
    portfolio_soft_risk_limit_usd: float | None = Field(default=None, ge=0.0)


class AssetControlOut(BaseModel):
    symbol: str
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
    tuning_params: dict[str, float | int]


class AssetControlUpdate(BaseModel):
    enabled: bool | None = None
    execution_mode: str | None = None
    trade_side: str | None = None
    soft_risk_limit_usd: float | None = Field(default=None, ge=0.0)


class AssetEngineLogOut(BaseModel):
    id: int
    symbol: str
    state: str
    note: str | None
    created_at: datetime


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
