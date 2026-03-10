from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mdtas.api.auth import require_read_access, require_write_access
from mdtas.api.schemas import (
    AssetEngineLogOut,
    AssetControlOut,
    AssetControlUpdate,
    ClosedTradeOut,
    ClosedTradesResponse,
    AssetValueBalanceOut,
    AssetValueBalanceRequest,
    OpenPositionOut,
    RiskPolicyOut,
    RiskPolicyUpdate,
    TraderConfigReloadStatusOut,
)
from mdtas.config import get_config
from mdtas.db.session import get_session
from mdtas.db.trading_repo import TradingRepository
from mdtas.trading.execution import CcxtExecutionAdapter, SymbolExecutionConstraints, round_down_to_step
from mdtas.trading.runtime_1m_simple import Simple1mParamResolver
from mdtas.trading.runtime import AssetParamResolver
from mdtas.trading.runtime_5m_simple import Simple5mParamResolver

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


def _split_symbol(symbol: str) -> tuple[str, str]:
    if "/" not in symbol:
        raise HTTPException(status_code=422, detail=f"Unsupported symbol format: {symbol}")
    base, quote = symbol.split("/", 1)
    if not base or not quote:
        raise HTTPException(status_code=422, detail=f"Unsupported symbol format: {symbol}")
    return base, quote


def _price_from_ticker(ticker: dict) -> float:
    for key in ("last", "close", "bid", "ask"):
        value = ticker.get(key)
        if value is not None:
            price = float(value)
            if price > 0:
                return price
    raise HTTPException(status_code=503, detail="No usable market price in ticker")


def _build_live_adapter(cfg, runtime_cfg) -> CcxtExecutionAdapter:
    return CcxtExecutionAdapter(
        venue=cfg.providers.ccxt.venue,
        rate_limit=cfg.providers.ccxt.rate_limit,
        api_key=cfg.providers.ccxt.api_key,
        api_secret=cfg.providers.ccxt.api_secret,
        api_password=cfg.providers.ccxt.api_password,
        sandbox=cfg.providers.ccxt.sandbox,
        live_trading_enabled=runtime_cfg.live_trading_enabled,
        live_allow_short=runtime_cfg.live_allow_short,
        live_max_order_notional_usd=runtime_cfg.live_max_order_notional_usd,
        live_allowed_symbols=runtime_cfg.live_allowed_symbols,
        live_require_explicit_env_ack=runtime_cfg.live_require_explicit_env_ack,
        live_ack_env_var_name=runtime_cfg.live_ack_env_var_name,
        live_ack_env_var_value=runtime_cfg.live_ack_env_var_value,
    )


def _constraints_for_symbol(runtime_cfg, symbol: str) -> SymbolExecutionConstraints:
    c = runtime_cfg.per_asset_constraints.get(symbol, runtime_cfg.default_constraints)
    return SymbolExecutionConstraints(
        min_notional_usd=float(c.min_notional_usd),
        qty_step=float(c.qty_step),
        price_tick=float(c.price_tick) if c.price_tick is not None else None,
        fee_bps=float(c.fee_bps),
    )


def _runtime_config_for_timeframe(cfg, timeframe: str):
    if timeframe == cfg.trading_1m.runtime_timeframe:
        return cfg.trading_1m
    if timeframe == cfg.trading_5m.runtime_timeframe:
        return cfg.trading_5m
    return cfg.trading


def _live_balance_snapshot(*, cfg, runtime_cfg, adapter: CcxtExecutionAdapter, symbol: str, trade_side: str) -> dict[str, float | str | bool]:
    base_ccy, quote_ccy = _split_symbol(symbol)
    balance = adapter.exchange.fetch_balance()
    ticker = adapter.exchange.fetch_ticker(symbol)
    px = _price_from_ticker(ticker)

    base_free = float((balance.get(base_ccy) or {}).get("free") or 0.0)
    quote_free = float((balance.get(quote_ccy) or {}).get("free") or 0.0)
    base_value = base_free * px
    quote_value = quote_free
    total_value = base_value + quote_value
    base_ratio = (base_value / total_value) if total_value > 0 else None

    constraints = _constraints_for_symbol(runtime_cfg, symbol)
    target_notional = float(runtime_cfg.position_size_usd)
    if runtime_cfg.live_max_order_notional_usd > 0:
        target_notional = min(target_notional, float(runtime_cfg.live_max_order_notional_usd))
    required_notional = max(float(constraints.min_notional_usd), target_notional)
    required_base_qty = (required_notional / px) if px > 0 else 0.0

    can_long = quote_free >= (required_notional * 1.01)
    can_short = base_free >= (required_base_qty * 1.001)
    long_needed = trade_side in {"long_only", "long_short"}
    short_needed = trade_side in {"short_only", "long_short"}

    if (long_needed and not can_long) or (short_needed and not can_short):
        status = "insufficient"
    elif trade_side == "long_short" and base_ratio is not None and abs(base_ratio - 0.5) > 0.15:
        status = "imbalanced"
    else:
        status = "ok"

    note_parts: list[str] = []
    if long_needed and not can_long:
        note_parts.append(f"need_quote>={required_notional:.4f}")
    if short_needed and not can_short:
        note_parts.append(f"need_base>={required_base_qty:.8f}")
    if not note_parts and trade_side == "long_short" and base_ratio is not None:
        note_parts.append(f"base_ratio={base_ratio:.3f}")

    return {
        "status": status,
        "can_long": bool(can_long),
        "can_short": bool(can_short),
        "base_free": float(base_free),
        "quote_free": float(quote_free),
        "price": float(px),
        "required_notional": float(required_notional),
        "required_base_qty": float(required_base_qty),
        "base_value_ratio": float(base_ratio) if base_ratio is not None else 0.0,
        "note": ", ".join(note_parts) if note_parts else "ok",
    }


@router.get("/positions/open", response_model=list[OpenPositionOut])
def open_positions(
    symbol: str | None = None,
    venue: str | None = None,
    timeframe: str | None = None,
    execution_mode: str | None = None,
    _auth: None = Depends(require_read_access),
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
    _auth: None = Depends(require_read_access),
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
    timeframe: str | None = Query(default=None),
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
    cfg = get_config()
    requested_timeframe = timeframe or cfg.trading.runtime_timeframe
    runtime_cfg = _runtime_config_for_timeframe(cfg, requested_timeframe)
    base_resolver = AssetParamResolver(cfg)
    simple_1m_resolver = Simple1mParamResolver(cfg)
    simple_5m_resolver = Simple5mParamResolver(cfg)
    live_adapter: CcxtExecutionAdapter | None = None
    live_adapter_error: str | None = None
    if runtime_cfg.execution_adapter == "real":
        try:
            live_adapter = _build_live_adapter(cfg, runtime_cfg)
        except Exception as exc:  # noqa: BLE001
            live_adapter_error = str(exc)
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
            timeframe=requested_timeframe,
            execution_mode=item.execution_mode,
        )
        base_params = base_resolver.for_symbol(item.symbol)
        simple_1m_params = simple_1m_resolver.for_symbol(item.symbol)
        simple_params = simple_5m_resolver.for_symbol(item.symbol)
        live_balance = None
        if item.execution_mode == "live":
            if live_adapter is not None:
                try:
                    live_balance = _live_balance_snapshot(
                        cfg=cfg,
                        runtime_cfg=runtime_cfg,
                        adapter=live_adapter,
                        symbol=item.symbol,
                        trade_side=item.trade_side,
                    )
                except Exception as exc:  # noqa: BLE001
                    live_balance = {"status": "error", "note": str(exc)}
            elif live_adapter_error is not None:
                live_balance = {"status": "error", "note": live_adapter_error}

        if requested_timeframe == cfg.trading_1m.runtime_timeframe:
            tuning_params = {
                "bb_length": simple_1m_params.bb_length,
                "bb_stdev": simple_1m_params.bb_stdev,
                "atr_length": simple_1m_params.atr_length,
                "ema_fast": simple_1m_params.ema_fast,
                "ema_slow": simple_1m_params.ema_slow,
                "bb_entry_deviation": simple_1m_params.bb_entry_deviation,
                "bb_exit_deviation": simple_1m_params.bb_exit_deviation,
                "slope_lookback_bars": simple_1m_params.slope_lookback_bars,
                "slope_flatten_factor": simple_1m_params.slope_flatten_factor,
                "stop_atr": simple_1m_params.stop_atr,
                "take_profit_atr": simple_1m_params.take_profit_atr,
                "max_hold_bars": simple_1m_params.max_hold_bars,
                "min_hold_bars_before_signal_exit": cfg.trading_1m.min_hold_bars_before_signal_exit,
                "cooldown_bars_after_exit": cfg.trading_1m.cooldown_bars_after_exit,
                "cooldown_bars_after_stop": cfg.trading_1m.cooldown_bars_after_stop,
                "max_entries_per_hour": cfg.trading_1m.max_entries_per_hour,
                "max_entries_per_day": cfg.trading_1m.max_entries_per_day,
            }
            bb_entry_mode = "range_revert"
        elif requested_timeframe == cfg.trading_5m.runtime_timeframe:
            tuning_params = {
                "bb_length": simple_params.bb_length,
                "bb_stdev": simple_params.bb_stdev,
                "atr_length": simple_params.atr_length,
                "ema_fast": simple_params.ema_fast,
                "ema_slow": simple_params.ema_slow,
                "bb_entry_deviation": simple_params.bb_entry_deviation,
                "bb_exit_deviation": simple_params.bb_exit_deviation,
                "slope_lookback_bars": simple_params.slope_lookback_bars,
                "slope_flatten_factor": simple_params.slope_flatten_factor,
                "stop_atr": simple_params.stop_atr,
                "take_profit_atr": simple_params.take_profit_atr,
                "max_hold_bars": simple_params.max_hold_bars,
                "min_hold_bars_before_signal_exit": cfg.trading_5m.min_hold_bars_before_signal_exit,
                "cooldown_bars_after_exit": cfg.trading_5m.cooldown_bars_after_exit,
                "cooldown_bars_after_stop": cfg.trading_5m.cooldown_bars_after_stop,
                "max_entries_per_hour": cfg.trading_5m.max_entries_per_hour,
                "max_entries_per_day": cfg.trading_5m.max_entries_per_day,
            }
            bb_entry_mode = "range_revert"
        else:
            tuning_params = {
                "rsi_length": base_params.rsi_length,
                "atr_length": base_params.atr_length,
                "ema_fast": base_params.ema_fast,
                "ema_slow": base_params.ema_slow,
                "rsi_entry": base_params.rsi_entry,
                "rsi_exit": base_params.rsi_exit,
                "stop_atr": base_params.stop_atr,
                "take_profit_atr": base_params.take_profit_atr,
                "max_hold_bars": base_params.max_hold_bars,
                "min_entry_atr_pct": cfg.trading.min_entry_atr_pct,
                "min_hold_bars_before_signal_exit": cfg.trading.min_hold_bars_before_signal_exit,
            }
            bb_entry_mode = cfg.trading.bb_entry_mode

        out.append(
            AssetControlOut(
                symbol=item.symbol,
                timeframe=requested_timeframe,
                enabled=bool(item.enabled),
                execution_mode=item.execution_mode,
                trade_side=item.trade_side,
                bb_entry_mode=bb_entry_mode,
                soft_risk_limit_usd=float(item.soft_risk_limit_usd),
                current_risk_usd=float(risk),
                last_run_ts=item.last_run_ts,
                next_run_ts=item.next_run_ts,
                last_evaluated_state=item.last_evaluated_state,
                last_evaluated_note=item.last_evaluated_note,
                live_balance=live_balance,
                tuning_params=tuning_params,
            )
        )
    return out


@router.put("/control-plane/assets/{symbol:path}", response_model=AssetControlOut)
def update_asset_control(
    symbol: str,
    payload: AssetControlUpdate,
    _auth: None = Depends(require_write_access),
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

    requested_timeframe = cfg.trading.runtime_timeframe
    runtime_cfg = _runtime_config_for_timeframe(cfg, requested_timeframe)
    resolver = AssetParamResolver(cfg)
    params = resolver.for_symbol(item.symbol)
    live_balance = None
    if item.execution_mode == "live" and cfg.trading.execution_adapter == "real":
        try:
            live_balance = _live_balance_snapshot(
                cfg=cfg,
                runtime_cfg=runtime_cfg,
                adapter=_build_live_adapter(cfg, runtime_cfg),
                symbol=item.symbol,
                trade_side=item.trade_side,
            )
        except Exception as exc:  # noqa: BLE001
            live_balance = {"status": "error", "note": str(exc)}
    risk = repo.current_open_risk_usd(
        symbol=item.symbol,
        venue=cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock",
        timeframe=cfg.trading.runtime_timeframe,
        execution_mode=item.execution_mode,
    )

    return AssetControlOut(
        symbol=item.symbol,
        timeframe=requested_timeframe,
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
        live_balance=live_balance,
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


@router.post("/control-plane/assets/{symbol:path}/value-balance", response_model=AssetValueBalanceOut)
def value_balance_asset(
    symbol: str,
    payload: AssetValueBalanceRequest,
    _auth: None = Depends(require_write_access),
):
    cfg = get_config()
    if symbol not in cfg.symbols:
        raise HTTPException(status_code=422, detail=f"Unknown symbol: {symbol}")
    if cfg.trading.execution_adapter != "real" or not cfg.trading.live_trading_enabled:
        raise HTTPException(status_code=409, detail="Value balance is only available for real trading mode")

    adapter = _build_live_adapter(cfg)
    constraints = _constraints_for_symbol(cfg, symbol)
    base_ccy, quote_ccy = _split_symbol(symbol)

    balance_before = adapter.exchange.fetch_balance()
    ticker = adapter.exchange.fetch_ticker(symbol)
    raw_price = _price_from_ticker(ticker)
    base_before = float((balance_before.get(base_ccy) or {}).get("free") or 0.0)
    quote_before = float((balance_before.get(quote_ccy) or {}).get("free") or 0.0)
    base_value_before = base_before * raw_price
    total_before = base_value_before + quote_before
    if total_before <= 0:
        raise HTTPException(status_code=409, detail="Cannot rebalance with zero combined base/quote value")

    ratio_before = base_value_before / total_before
    target_ratio = float(payload.target_base_ratio)
    tolerance = float(payload.tolerance_bps) / 10000.0
    delta_ratio = target_ratio - ratio_before
    if abs(delta_ratio) <= tolerance:
        return AssetValueBalanceOut(
            symbol=symbol,
            action="none",
            order_side=None,
            qty=0.0,
            raw_price=float(raw_price),
            fill_price=None,
            fill_notional_usd=None,
            fee_usd=None,
            pre_base_qty=float(base_before),
            pre_quote_qty=float(quote_before),
            post_base_qty=float(base_before),
            post_quote_qty=float(quote_before),
            base_value_ratio_before=float(ratio_before),
            base_value_ratio_after=float(ratio_before),
            note="already within tolerance",
        )

    target_base_value = total_before * target_ratio
    delta_base_value = target_base_value - base_value_before

    max_notional = float(cfg.trading.live_max_order_notional_usd)
    if max_notional <= 0:
        max_notional = abs(delta_base_value)

    order_side: str
    if delta_base_value > 0:
        spend = min(delta_base_value, quote_before * 0.98, max_notional)
        qty = round_down_to_step(spend / raw_price, constraints.qty_step)
        order_side = "buy"
        trade_side = "long"
    else:
        sell_notional = min(abs(delta_base_value), base_before * raw_price * 0.98, max_notional)
        qty = round_down_to_step(sell_notional / raw_price, constraints.qty_step)
        order_side = "sell"
        trade_side = "short"

    if qty <= 0:
        raise HTTPException(status_code=409, detail="Computed rebalance quantity is zero; increase balances or adjust constraints")

    if trade_side == "long":
        fill = adapter.submit_entry(
            symbol=symbol,
            raw_price=float(raw_price),
            qty=float(qty),
            trade_side="long",
            constraints=constraints,
        )
    else:
        fill = adapter.submit_entry(
            symbol=symbol,
            raw_price=float(raw_price),
            qty=float(qty),
            trade_side="short",
            constraints=constraints,
        )

    balance_after = adapter.exchange.fetch_balance()
    base_after = float((balance_after.get(base_ccy) or {}).get("free") or 0.0)
    quote_after = float((balance_after.get(quote_ccy) or {}).get("free") or 0.0)
    base_value_after = base_after * raw_price
    total_after = base_value_after + quote_after
    ratio_after = (base_value_after / total_after) if total_after > 0 else None

    return AssetValueBalanceOut(
        symbol=symbol,
        action="executed",
        order_side=order_side,
        qty=float(fill.qty),
        raw_price=float(raw_price),
        fill_price=float(fill.price),
        fill_notional_usd=float(fill.notional_usd),
        fee_usd=float(fill.fee_usd),
        pre_base_qty=float(base_before),
        pre_quote_qty=float(quote_before),
        post_base_qty=float(base_after),
        post_quote_qty=float(quote_after),
        base_value_ratio_before=float(ratio_before),
        base_value_ratio_after=float(ratio_after) if ratio_after is not None else None,
        note=f"target_ratio={target_ratio:.4f}, tolerance_bps={payload.tolerance_bps:.2f}",
    )


@router.get("/control-plane/assets/{symbol:path}/logs", response_model=list[AssetEngineLogOut])
def list_asset_logs(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=2000),
    _auth: None = Depends(require_write_access),
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
def get_risk_policy_settings(_auth: None = Depends(require_write_access)):
    cfg = get_config()
    return RiskPolicyOut(
        risk_budget_policy=cfg.trading.risk_budget_policy,
        portfolio_soft_risk_limit_usd=float(cfg.trading.portfolio_soft_risk_limit_usd),
    )


@router.put("/control-plane/risk-policy", response_model=RiskPolicyOut)
def update_risk_policy_settings(payload: RiskPolicyUpdate, _auth: None = Depends(require_write_access)):
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
def get_trader_reload_status(
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
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
