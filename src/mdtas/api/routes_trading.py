from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mdtas.api.schemas import (
    AssetEngineLogOut,
    AssetControlOut,
    AssetControlUpdate,
    ClosedTradeOut,
    ClosedTradesResponse,
    OpenPositionOut,
    RiskPolicyOut,
    RiskPolicyUpdate,
    TraderConfigReloadStatusOut,
)
from mdtas.config import get_config
from mdtas.db.session import get_session
from mdtas.db.trading_repo import TradingRepository
from mdtas.trading.runtime import AssetParamResolver

router = APIRouter(tags=["trading"])
SYSTEM_TRADER_SYMBOL = "__SYSTEM__/TRADER"


def get_repo(session: Session = Depends(get_session)):
    try:
        yield TradingRepository(session)
    finally:
        session.close()


def _validate_mode(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in {"sim", "live"}:
        raise HTTPException(status_code=422, detail="execution_mode must be one of: sim, live")
    return value


def _validate_trade_side(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in {"long_only", "long_short", "short_only"}:
        raise HTTPException(status_code=422, detail="trade_side must be one of: long_only, long_short, short_only")
    return value


def _validate_risk_policy(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in {"per_symbol", "portfolio"}:
        raise HTTPException(status_code=422, detail="risk_budget_policy must be one of: per_symbol, portfolio")
    return value


@router.get("/positions/open", response_model=list[OpenPositionOut])
def open_positions(
    symbol: str | None = None,
    venue: str | None = None,
    timeframe: str | None = None,
    execution_mode: str | None = None,
    repo: TradingRepository = Depends(get_repo),
):
    mode = _validate_mode(execution_mode)
    items = repo.list_open_positions(symbol=symbol, venue=venue, timeframe=timeframe, execution_mode=mode)
    out: list[OpenPositionOut] = []
    for item in items:
        unrealized_pnl = None
        unrealized_return_pct = None
        if item.last_price is not None:
            if item.trade_side == "short":
                gross = (float(item.entry_price) - float(item.last_price)) * float(item.qty)
            else:
                gross = (float(item.last_price) - float(item.entry_price)) * float(item.qty)
            unrealized_pnl = gross - float(item.entry_fee)
            notional = float(item.entry_price) * float(item.qty)
            unrealized_return_pct = (unrealized_pnl / notional) * 100.0 if notional > 0 else 0.0

        out.append(
            OpenPositionOut(
                id=item.id,
                symbol=item.symbol,
                venue=item.venue,
                timeframe=item.timeframe,
                execution_mode=item.execution_mode,
                trade_side=item.trade_side,
                entry_ts=item.entry_ts,
                entry_price=float(item.entry_price),
                qty=float(item.qty),
                stop_price=float(item.stop_price) if item.stop_price is not None else None,
                take_profit_price=float(item.take_profit_price) if item.take_profit_price is not None else None,
                hold_bars=int(item.hold_bars),
                last_price=float(item.last_price) if item.last_price is not None else None,
                unrealized_pnl=unrealized_pnl,
                unrealized_return_pct=unrealized_return_pct,
            )
        )
    return out


@router.get("/trades/closed", response_model=ClosedTradesResponse)
def closed_trades(
    symbol: str | None = None,
    venue: str | None = None,
    timeframe: str | None = None,
    execution_mode: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    repo: TradingRepository = Depends(get_repo),
):
    mode = _validate_mode(execution_mode)
    rows = repo.list_closed_trades(symbol=symbol, venue=venue, timeframe=timeframe, execution_mode=mode, limit=limit)

    payload_rows = [
        ClosedTradeOut(
            id=item.id,
            symbol=item.symbol,
            venue=item.venue,
            timeframe=item.timeframe,
            execution_mode=item.execution_mode,
            trade_side=item.trade_side,
            entry_ts=item.entry_ts,
            exit_ts=item.exit_ts,
            entry_price=float(item.entry_price),
            exit_price=float(item.exit_price),
            qty=float(item.qty),
            gross_pnl=float(item.gross_pnl),
            fees=float(item.fees),
            net_pnl=float(item.net_pnl),
            return_pct=float(item.return_pct),
            exit_reason=item.exit_reason,
        )
        for item in rows
    ]

    return ClosedTradesResponse(
        count=len(payload_rows),
        total_net_pnl=float(sum(item.net_pnl for item in payload_rows)),
        total_gross_pnl=float(sum(item.gross_pnl for item in payload_rows)),
        rows=payload_rows,
    )


@router.get("/control-plane/assets", response_model=list[AssetControlOut])
def list_asset_controls(
    repo: TradingRepository = Depends(get_repo),
):
    cfg = get_config()
    resolver = AssetParamResolver(cfg)
    items = repo.list_asset_controls(
        symbols=cfg.symbols,
        default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
        default_execution_mode="sim",
        default_trade_side="long_only",
    )

    out: list[AssetControlOut] = []
    for item in items:
        risk = repo.current_open_risk_usd(
            symbol=item.symbol,
            venue=cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock",
            timeframe=cfg.trading.runtime_timeframe,
            execution_mode=item.execution_mode,
        )
        params = resolver.for_symbol(item.symbol)
        out.append(
            AssetControlOut(
                symbol=item.symbol,
                enabled=bool(item.enabled),
                execution_mode=item.execution_mode,
                trade_side=item.trade_side,
                bb_entry_mode=cfg.trading.bb_entry_mode,
                soft_risk_limit_usd=float(item.soft_risk_limit_usd),
                current_risk_usd=float(risk),
                last_run_ts=item.last_run_ts,
                next_run_ts=item.next_run_ts,
                last_evaluated_state=item.last_evaluated_state,
                last_evaluated_note=item.last_evaluated_note,
                tuning_params={
                    "rsi_length": params.rsi_length,
                    "atr_length": params.atr_length,
                    "ema_fast": params.ema_fast,
                    "ema_slow": params.ema_slow,
                    "rsi_entry": params.rsi_entry,
                    "rsi_exit": params.rsi_exit,
                    "stop_atr": params.stop_atr,
                    "take_profit_atr": params.take_profit_atr,
                    "max_hold_bars": params.max_hold_bars,
                    "min_entry_atr_pct": cfg.trading.min_entry_atr_pct,
                    "min_hold_bars_before_signal_exit": cfg.trading.min_hold_bars_before_signal_exit,
                },
            )
        )
    return out


@router.put("/control-plane/assets/{symbol:path}", response_model=AssetControlOut)
def update_asset_control(
    symbol: str,
    payload: AssetControlUpdate,
    repo: TradingRepository = Depends(get_repo),
):
    cfg = get_config()
    if symbol not in cfg.symbols:
        raise HTTPException(status_code=422, detail=f"Unknown symbol: {symbol}")

    mode = payload.execution_mode
    if mode is not None:
        _validate_mode(mode)
    trade_side = payload.trade_side
    if trade_side is not None:
        _validate_trade_side(trade_side)

    item = repo.update_asset_control(
        symbol=symbol,
        default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
        enabled=payload.enabled,
        execution_mode=mode,
        trade_side=trade_side,
        soft_risk_limit_usd=payload.soft_risk_limit_usd,
    )

    resolver = AssetParamResolver(cfg)
    params = resolver.for_symbol(item.symbol)
    risk = repo.current_open_risk_usd(
        symbol=item.symbol,
        venue=cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock",
        timeframe=cfg.trading.runtime_timeframe,
        execution_mode=item.execution_mode,
    )

    return AssetControlOut(
        symbol=item.symbol,
        enabled=bool(item.enabled),
        execution_mode=item.execution_mode,
        trade_side=item.trade_side,
        bb_entry_mode=cfg.trading.bb_entry_mode,
        soft_risk_limit_usd=float(item.soft_risk_limit_usd),
        current_risk_usd=float(risk),
        last_run_ts=item.last_run_ts,
        next_run_ts=item.next_run_ts,
        last_evaluated_state=item.last_evaluated_state,
        last_evaluated_note=item.last_evaluated_note,
        tuning_params={
            "rsi_length": params.rsi_length,
            "atr_length": params.atr_length,
            "ema_fast": params.ema_fast,
            "ema_slow": params.ema_slow,
            "rsi_entry": params.rsi_entry,
            "rsi_exit": params.rsi_exit,
            "stop_atr": params.stop_atr,
            "take_profit_atr": params.take_profit_atr,
            "max_hold_bars": params.max_hold_bars,
            "min_entry_atr_pct": cfg.trading.min_entry_atr_pct,
            "min_hold_bars_before_signal_exit": cfg.trading.min_hold_bars_before_signal_exit,
        },
    )


@router.get("/control-plane/assets/{symbol:path}/logs", response_model=list[AssetEngineLogOut])
def list_asset_logs(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=2000),
    repo: TradingRepository = Depends(get_repo),
):
    rows = repo.list_asset_logs(symbol=symbol, limit=limit)
    return [
        AssetEngineLogOut(
            id=item.id,
            symbol=item.symbol,
            state=item.state,
            note=item.note,
            created_at=item.created_at,
        )
        for item in rows
    ]


@router.get("/control-plane/risk-policy", response_model=RiskPolicyOut)
def get_risk_policy_settings():
    cfg = get_config()
    return RiskPolicyOut(
        risk_budget_policy=cfg.trading.risk_budget_policy,
        portfolio_soft_risk_limit_usd=float(cfg.trading.portfolio_soft_risk_limit_usd),
    )


@router.put("/control-plane/risk-policy", response_model=RiskPolicyOut)
def update_risk_policy_settings(payload: RiskPolicyUpdate):
    cfg = get_config()
    policy = _validate_risk_policy(payload.risk_budget_policy)
    if policy is not None:
        cfg.trading.risk_budget_policy = policy
    if payload.portfolio_soft_risk_limit_usd is not None:
        cfg.trading.portfolio_soft_risk_limit_usd = float(payload.portfolio_soft_risk_limit_usd)
    return RiskPolicyOut(
        risk_budget_policy=cfg.trading.risk_budget_policy,
        portfolio_soft_risk_limit_usd=float(cfg.trading.portfolio_soft_risk_limit_usd),
    )


@router.get("/control-plane/trader/reload-status", response_model=TraderConfigReloadStatusOut)
def get_trader_reload_status(repo: TradingRepository = Depends(get_repo)):
    last_event = repo.latest_engine_event(
        symbol=SYSTEM_TRADER_SYMBOL,
        states=("config_reloaded", "config_reload_failed"),
    )
    last_success = repo.latest_engine_event(symbol=SYSTEM_TRADER_SYMBOL, states=("config_reloaded",))
    last_failure = repo.latest_engine_event(symbol=SYSTEM_TRADER_SYMBOL, states=("config_reload_failed",))

    status = None
    if last_event is not None:
        status = "ok" if last_event.state == "config_reloaded" else "error"

    return TraderConfigReloadStatusOut(
        last_status=status,
        last_event_ts=last_event.created_at if last_event is not None else None,
        last_event_note=last_event.note if last_event is not None else None,
        last_success_ts=last_success.created_at if last_success is not None else None,
        last_failure_ts=last_failure.created_at if last_failure is not None else None,
    )
