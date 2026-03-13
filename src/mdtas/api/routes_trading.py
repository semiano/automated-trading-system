from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

import ccxt
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mdtas.api.auth import require_read_access, require_write_access
from mdtas.api.schemas import (
    AssetEngineLogOut,
    AssetControlOut,
    AssetControlUpdate,
    PortfolioBalanceAssetOut,
    PortfolioBalancesOut,
    AssetTuningUpdate,
    AssetTuningVersionOut,
    ClosedTradeOut,
    ClosedTradesResponse,
    AssetValueBalanceOut,
    AssetValueBalanceRequest,
    SimWalletAugmentOut,
    SimWalletAugmentRequest,
    OpenPositionOut,
    RiskPolicyOut,
    RiskPolicyUpdate,
    LiveReadinessOut,
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
_SIMPLE_TUNING_FIELDS = {
    "bb_length",
    "bb_stdev",
    "atr_length",
    "ema_fast",
    "ema_slow",
    "bb_entry_deviation",
    "bb_exit_deviation",
    "slope_lookback_bars",
    "slope_flatten_factor",
    "stop_atr",
    "take_profit_atr",
    "max_hold_bars",
    "min_hold_bars",
    "max_take_profit_pct",
}


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


_USD_EQUIV_QUOTES = {"USD", "USDT", "USDC", "BUSD", "DAI", "FDUSD", "USDP"}


def _usd_price_for_currency(*, adapter: CcxtExecutionAdapter, currency: str) -> float | None:
    return _usd_price_for_exchange_currency(exchange=adapter.exchange, currency=currency)


def _usd_price_for_exchange_currency(*, exchange: Any, currency: str) -> float | None:
    ccy = currency.upper()
    if ccy in _USD_EQUIV_QUOTES:
        return 1.0

    for market in (f"{ccy}/USDT", f"{ccy}/USD"):
        try:
            ticker = exchange.fetch_ticker(market)
            return _price_from_ticker(ticker)
        except Exception:  # noqa: BLE001
            continue

    for market in (f"USDT/{ccy}", f"USD/{ccy}"):
        try:
            ticker = exchange.fetch_ticker(market)
            px = _price_from_ticker(ticker)
            if px > 0:
                return 1.0 / px
        except Exception:  # noqa: BLE001
            continue

    return None


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


def _build_readonly_exchange(cfg) -> Any:
    venue_name = cfg.providers.ccxt.venue
    venue_cls = getattr(ccxt, venue_name, None)
    if venue_cls is None:
        raise HTTPException(status_code=422, detail=f"Unsupported ccxt venue: {venue_name}")

    kwargs: dict[str, object] = {
        "enableRateLimit": bool(cfg.providers.ccxt.rate_limit),
    }
    if cfg.providers.ccxt.api_key:
        kwargs["apiKey"] = cfg.providers.ccxt.api_key
    if cfg.providers.ccxt.api_secret:
        kwargs["secret"] = cfg.providers.ccxt.api_secret
    if cfg.providers.ccxt.api_password:
        kwargs["password"] = cfg.providers.ccxt.api_password

    exchange = venue_cls(kwargs)
    if bool(cfg.providers.ccxt.sandbox) and hasattr(exchange, "set_sandbox_mode"):
        exchange.set_sandbox_mode(True)
    exchange.load_markets()
    return exchange


def _constraints_for_symbol(runtime_cfg, symbol: str) -> SymbolExecutionConstraints:
    c = runtime_cfg.per_asset_constraints.get(symbol, runtime_cfg.default_constraints)
    return SymbolExecutionConstraints(
        min_notional_usd=float(c.min_notional_usd),
        qty_step=float(c.qty_step),
        price_tick=float(c.price_tick) if c.price_tick is not None else None,
        fee_bps=float(c.fee_bps),
    )


def _leg_slippage(
    *,
    trade_side: str,
    leg: str,
    spot_price: float | None,
    fill_price: float,
    qty: float,
) -> tuple[float | None, float | None]:
    if spot_price is None:
        return None, None
    spot = float(spot_price)
    if spot <= 0:
        return None, None

    fill = float(fill_price)
    if leg == "entry":
        # Positive means adverse slippage (costlier entry from trader perspective).
        signed = (fill - spot) if trade_side == "long" else (spot - fill)
    else:
        # Positive means adverse slippage (worse exit from trader perspective).
        signed = (spot - fill) if trade_side == "long" else (fill - spot)

    bps = (signed / spot) * 10000.0
    usd = signed * float(qty)
    return float(bps), float(usd)


def _runtime_config_for_timeframe(cfg, timeframe: str):
    if timeframe == cfg.trading_1m.runtime_timeframe:
        return cfg.trading_1m
    if timeframe == cfg.trading_5m.runtime_timeframe:
        return cfg.trading_5m
    return cfg.trading


def _runtime_configs(cfg) -> list[Any]:
    return [cfg.trading_1m, cfg.trading_5m, cfg.trading]


def _control_plane_timeframes(cfg) -> list[str]:
    ordered = [
        cfg.trading_1m.runtime_timeframe,
        cfg.trading_5m.runtime_timeframe,
        cfg.trading.runtime_timeframe,
    ]
    # Always include 1h for XRP/USD
    if "1h" not in ordered:
        ordered.append("1h")
    out: list[str] = []
    for tf in ordered:
        if tf and tf not in out:
            out.append(tf)
    return out


def _merged_simple_tuning_params(*, base: dict[str, float | int], override: dict[str, float | int] | None) -> dict[str, float | int]:
    out = dict(base)
    if not override:
        return out
    for key, value in override.items():
        if key in _SIMPLE_TUNING_FIELDS:
            out[key] = value
    return out


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

    payload_rows: list[ClosedTradeOut] = []
    for item in rows:
        qty = float(item.qty)
        entry_spot = float(item.entry_spot_price) if item.entry_spot_price is not None else None
        exit_spot = float(item.exit_spot_price) if item.exit_spot_price is not None else None
        entry_slip_bps, entry_slip_usd = _leg_slippage(
            trade_side=item.trade_side,
            leg="entry",
            spot_price=entry_spot,
            fill_price=float(item.entry_price),
            qty=qty,
        )
        exit_slip_bps, exit_slip_usd = _leg_slippage(
            trade_side=item.trade_side,
            leg="exit",
            spot_price=exit_spot,
            fill_price=float(item.exit_price),
            qty=qty,
        )
        total_slippage_usd = None
        if entry_slip_usd is not None or exit_slip_usd is not None:
            total_slippage_usd = float((entry_slip_usd or 0.0) + (exit_slip_usd or 0.0))

        payload_rows.append(
            ClosedTradeOut(
                id=item.id,
                symbol=item.symbol,
                venue=item.venue,
                timeframe=item.timeframe,
                execution_mode=item.execution_mode,
                trade_side=item.trade_side,
                entry_ts=item.entry_ts,
                exit_ts=item.exit_ts,
                entry_spot_price=entry_spot,
                exit_spot_price=exit_spot,
                entry_price=float(item.entry_price),
                exit_price=float(item.exit_price),
                entry_slippage_bps=entry_slip_bps,
                entry_slippage_usd=entry_slip_usd,
                exit_slippage_bps=exit_slip_bps,
                exit_slippage_usd=exit_slip_usd,
                total_slippage_usd=total_slippage_usd,
                qty=qty,
                gross_pnl=float(item.gross_pnl),
                fees=float(item.fees),
                net_pnl=float(item.net_pnl),
                return_pct=float(item.return_pct),
                exit_reason=item.exit_reason,
                hold_bars_at_exit=int(item.hold_bars_at_exit) if item.hold_bars_at_exit is not None else None,
            )
        )

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
    if timeframe is not None and timeframe not in _control_plane_timeframes(cfg):
        raise HTTPException(status_code=422, detail=f"Unsupported timeframe: {timeframe}")
    requested_timeframes = [timeframe] if timeframe else _control_plane_timeframes(cfg)

    # Always include 1h for XRP/USD if it exists in the DB
    from mdtas.db.session import SessionLocal
    db_session = SessionLocal()
    try:
        repo_direct = TradingRepository(db_session)
        ac = repo_direct.get_or_create_asset_control(
            symbol="XRP/USD",
            timeframe="1h",
            default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
            default_execution_mode="sim",
            default_trade_side="long_short",
            default_enabled=True,
        )
        if "1h" not in requested_timeframes:
            requested_timeframes.append("1h")
        if "XRP/USD" not in cfg.symbols:
            cfg.symbols.append("XRP/USD")
    finally:
        db_session.close()
    base_resolver = AssetParamResolver(cfg)
    simple_1m_resolver = Simple1mParamResolver(cfg)
    simple_5m_resolver = Simple5mParamResolver(cfg)
    live_adapters: dict[str, CcxtExecutionAdapter | None] = {}
    live_adapter_errors: dict[str, str | None] = {}
    for tf in requested_timeframes:
        runtime_cfg = _runtime_config_for_timeframe(cfg, tf)
        if runtime_cfg.execution_adapter == "real":
            try:
                live_adapters[tf] = _build_live_adapter(cfg, runtime_cfg)
                live_adapter_errors[tf] = None
            except Exception as exc:  # noqa: BLE001
                live_adapters[tf] = None
                live_adapter_errors[tf] = str(exc)
        else:
            live_adapters[tf] = None
            live_adapter_errors[tf] = None

    items = repo.list_asset_controls(
        symbols=cfg.symbols,
        timeframes=requested_timeframes,
        default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
        default_execution_mode="sim",
        default_trade_side="long_only",
    )
    # Always include all asset controls for XRP/USD
    for ac in repo.list_all_asset_controls_for_symbol("XRP/USD"):
        if ac not in items:
            items.append(ac)

    out: list[AssetControlOut] = []
    for item in items:
        requested_timeframe = item.timeframe
        runtime_cfg = _runtime_config_for_timeframe(cfg, requested_timeframe)
        risk = repo.current_open_risk_usd(
            symbol=item.symbol,
            venue=cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock",
            timeframe=requested_timeframe,
            execution_mode=item.execution_mode,
        )
        base_params = base_resolver.for_symbol(item.symbol)
        simple_1m_params = simple_1m_resolver.for_symbol(item.symbol)
        simple_params = simple_5m_resolver.for_symbol(item.symbol)
        tuning_version = repo.latest_asset_tuning_version(symbol=item.symbol, timeframe=requested_timeframe)
        tuning_override = tuning_version.params_json if tuning_version is not None else None
        live_balance = None
        if item.execution_mode == "live":
            live_adapter = live_adapters.get(requested_timeframe)
            live_adapter_error = live_adapter_errors.get(requested_timeframe)
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
            tuning_params_base = {
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
                "min_hold_bars": simple_1m_params.min_hold_bars,
                "max_take_profit_pct": simple_1m_params.max_take_profit_pct,
                "min_hold_bars_before_signal_exit": cfg.trading_1m.min_hold_bars_before_signal_exit,
                "cooldown_bars_after_exit": cfg.trading_1m.cooldown_bars_after_exit,
                "cooldown_bars_after_stop": cfg.trading_1m.cooldown_bars_after_stop,
                "max_entries_per_hour": cfg.trading_1m.max_entries_per_hour,
                "max_entries_per_day": cfg.trading_1m.max_entries_per_day,
                "htf_rsi_timeframe": cfg.trading_1m.htf_rsi_timeframe,
            }
            tuning_params = _merged_simple_tuning_params(base=tuning_params_base, override=tuning_override)
            bb_entry_mode = "range_revert"
        elif requested_timeframe == cfg.trading_5m.runtime_timeframe:
            tuning_params_base = {
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
                "min_hold_bars": simple_params.min_hold_bars,
                "max_take_profit_pct": simple_params.max_take_profit_pct,
                "min_hold_bars_before_signal_exit": cfg.trading_5m.min_hold_bars_before_signal_exit,
                "cooldown_bars_after_exit": cfg.trading_5m.cooldown_bars_after_exit,
                "cooldown_bars_after_stop": cfg.trading_5m.cooldown_bars_after_stop,
                "max_entries_per_hour": cfg.trading_5m.max_entries_per_hour,
                "max_entries_per_day": cfg.trading_5m.max_entries_per_day,
                "htf_rsi_timeframe": cfg.trading_5m.htf_rsi_timeframe,
            }
            tuning_params = _merged_simple_tuning_params(base=tuning_params_base, override=tuning_override)
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
                "min_hold_bars": base_params.min_hold_bars,
                "max_take_profit_pct": base_params.max_take_profit_pct,
                "min_entry_atr_pct": cfg.trading.min_entry_atr_pct,
                "min_hold_bars_before_signal_exit": cfg.trading.min_hold_bars_before_signal_exit,
                "htf_rsi_timeframe": cfg.trading.htf_rsi_timeframe,
                "htf_rsi_length": cfg.trading.htf_rsi_length,
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
                tuning_version=tuning_version.version if tuning_version is not None else None,
                tuning_note=tuning_version.note if tuning_version is not None else None,
                tuning_source=tuning_version.source if tuning_version is not None else None,
                tuning_updated_by=tuning_version.updated_by if tuning_version is not None else None,
                tuning_updated_at=tuning_version.created_at if tuning_version is not None else None,
            )
        )
    return out


@router.get("/control-plane/portfolio/balances", response_model=PortfolioBalancesOut)
def get_portfolio_balances(
    mode: str = Query(default="sim"),
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
    execution_mode = _validate_mode(mode)
    if execution_mode is None:
        execution_mode = "sim"

    cfg = get_config()
    now = datetime.now(timezone.utc)

    if execution_mode == "live":
        try:
            exchange = _build_readonly_exchange(cfg)
            balance = exchange.fetch_balance()
        except Exception as exc:  # noqa: BLE001
            return PortfolioBalancesOut(
                mode="live",
                as_of=now,
                total_value_usd=0.0,
                cash_value_usd=0.0,
                asset_value_usd=0.0,
                cash_ratio=0.0,
                asset_ratio=0.0,
                note=f"Live balance unavailable: {exc}",
                assets=[],
            )

        currencies: set[str] = set()
        for symbol in cfg.symbols:
            base_ccy, quote_ccy = _split_symbol(symbol)
            currencies.add(base_ccy)
            currencies.add(quote_ccy)

        rows: list[PortfolioBalanceAssetOut] = []
        cash_value = 0.0
        asset_value = 0.0

        valuation_warnings: list[str] = []
        for ccy in sorted(currencies):
            free_qty = float((balance.get(ccy) or {}).get("free") or 0.0)
            if free_qty <= 0:
                continue
            usd_px = None
            try:
                usd_px = _usd_price_for_exchange_currency(exchange=exchange, currency=ccy)
            except Exception as exc:  # noqa: BLE001
                valuation_warnings.append(f"{ccy}:{exc}")
            value_usd = float(free_qty * usd_px) if usd_px is not None else 0.0
            if ccy in _USD_EQUIV_QUOTES:
                cash_value += value_usd
            else:
                asset_value += value_usd
            rows.append(
                PortfolioBalanceAssetOut(
                    asset=ccy,
                    free=float(free_qty),
                    usd_price=float(usd_px) if usd_px is not None else None,
                    value_usd=float(value_usd),
                )
            )

        total_value = cash_value + asset_value
        cash_ratio = (cash_value / total_value) if total_value > 0 else 0.0
        asset_ratio = (asset_value / total_value) if total_value > 0 else 0.0
        return PortfolioBalancesOut(
            mode="live",
            as_of=now,
            total_value_usd=float(total_value),
            cash_value_usd=float(cash_value),
            asset_value_usd=float(asset_value),
            cash_ratio=float(cash_ratio),
            asset_ratio=float(asset_ratio),
            note=(
                "Exchange free balances valued in USD; unsupported currency pairs are valued at 0."
                if not valuation_warnings
                else "Exchange balances loaded with partial valuation errors; some assets may be valued at 0."
            ),
            assets=rows,
        )

    controls = repo.list_asset_controls(
        symbols=cfg.symbols,
        timeframes=_control_plane_timeframes(cfg),
        default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
        default_execution_mode="sim",
        default_trade_side="long_only",
    )

    per_symbol_budget: dict[str, float] = {}

    for row in controls:
        if row.execution_mode != "sim":
            continue
        symbol_budget = per_symbol_budget.get(row.symbol, 0.0) + float(row.soft_risk_limit_usd)
        per_symbol_budget[row.symbol] = symbol_budget

    realized_by_symbol = repo.realized_net_pnl_by_symbol(execution_mode="sim")
    open_positions = repo.list_open_positions(execution_mode="sim")
    open_long_notional_by_symbol: dict[str, float] = {}
    open_short_notional_by_symbol: dict[str, float] = {}
    unrealized_by_symbol: dict[str, float] = {}
    for item in open_positions:
        mark_price = float(item.last_price) if item.last_price is not None else float(item.entry_price)
        qty = float(item.qty)
        notional = abs(mark_price * qty)
        if item.trade_side == "short":
            open_short_notional_by_symbol[item.symbol] = open_short_notional_by_symbol.get(item.symbol, 0.0) + notional
        else:
            open_long_notional_by_symbol[item.symbol] = open_long_notional_by_symbol.get(item.symbol, 0.0) + notional

        if item.trade_side == "short":
            gross = (float(item.entry_price) - mark_price) * qty
        else:
            gross = (mark_price - float(item.entry_price)) * qty
        unrealized_net = float(gross) - float(item.entry_fee)
        unrealized_by_symbol[item.symbol] = unrealized_by_symbol.get(item.symbol, 0.0) + unrealized_net

    wallet_adjustments = {row.symbol: row for row in repo.list_sim_wallet_balances()}

    cash_value = 0.0
    asset_value = 0.0
    rows: list[PortfolioBalanceAssetOut] = []
    symbols = sorted(
        set(cfg.symbols)
        | set(per_symbol_budget.keys())
        | set(realized_by_symbol.keys())
        | set(open_long_notional_by_symbol.keys())
        | set(open_short_notional_by_symbol.keys())
        | set(wallet_adjustments.keys())
    )
    for symbol in symbols:
        budget = float(max(per_symbol_budget.get(symbol, 0.0), 0.0))
        realized = float(realized_by_symbol.get(symbol, 0.0))
        unrealized = float(unrealized_by_symbol.get(symbol, 0.0))
        open_long_notional = float(open_long_notional_by_symbol.get(symbol, 0.0))
        open_short_notional = float(open_short_notional_by_symbol.get(symbol, 0.0))
        wallet_row = wallet_adjustments.get(symbol)
        cash_adjustment = float(wallet_row.cash_adjustment_usd) if wallet_row is not None else 0.0
        asset_adjustment = float(wallet_row.asset_adjustment_usd) if wallet_row is not None else 0.0

        equity = max(budget + realized + unrealized, 0.0)
        baseline_asset = equity * 0.5
        baseline_cash = equity * 0.5
        available = max(baseline_cash - open_long_notional + open_short_notional + cash_adjustment, 0.0)
        asset_leg = max(baseline_asset + open_long_notional - open_short_notional + asset_adjustment, 0.0)

        cash_value += available
        asset_value += asset_leg
        rows.append(
            PortfolioBalanceAssetOut(
                asset=symbol,
                free=float(available),
                usd_price=1.0,
                value_usd=float(available + asset_leg),
            )
        )

    total_value = cash_value + asset_value
    cash_ratio = (cash_value / total_value) if total_value > 0 else 0.0
    asset_ratio = (asset_value / total_value) if total_value > 0 else 0.0
    return PortfolioBalancesOut(
        mode="sim",
        as_of=now,
        total_value_usd=float(total_value),
        cash_value_usd=float(cash_value),
        asset_value_usd=float(asset_value),
        cash_ratio=float(cash_ratio),
        asset_ratio=float(asset_ratio),
        note=(
            "Sim balances are trade-aware and side-aware: long entries consume cash, short entries consume asset inventory; "
            "manual SIM wallet adjustments are included per symbol."
        ),
        assets=rows,
    )


@router.post("/control-plane/assets/{symbol:path}/sim-wallet/augment", response_model=SimWalletAugmentOut)
def augment_sim_wallet_balance(
    symbol: str,
    payload: SimWalletAugmentRequest,
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
    cfg = get_config()
    if symbol not in cfg.symbols:
        raise HTTPException(status_code=422, detail=f"Unknown symbol: {symbol}")

    bucket = (payload.bucket or "").strip().lower()
    if bucket not in {"cash", "asset"}:
        raise HTTPException(status_code=422, detail="bucket must be one of: cash, asset")

    amount = float(payload.amount_usd)
    row = repo.augment_sim_wallet_balance(symbol=symbol, bucket=bucket, amount_usd=amount)
    return SimWalletAugmentOut(
        symbol=symbol,
        bucket=bucket,
        amount_usd=amount,
        cash_adjustment_usd=float(row.cash_adjustment_usd),
        asset_adjustment_usd=float(row.asset_adjustment_usd),
        note="SIM wallet balance updated",
    )


@router.put("/control-plane/assets/{symbol:path}", response_model=AssetControlOut)
def update_asset_control(
    symbol: str,
    payload: AssetControlUpdate,
    timeframe: str = Query(...),
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
    cfg = get_config()
    if symbol not in cfg.symbols:
        raise HTTPException(status_code=422, detail=f"Unknown symbol: {symbol}")
    if timeframe not in _control_plane_timeframes(cfg):
        raise HTTPException(status_code=422, detail=f"Unsupported timeframe: {timeframe}")

    mode = payload.execution_mode
    if mode is not None:
        _validate_mode(mode)
    trade_side = payload.trade_side
    if trade_side is not None:
        _validate_trade_side(trade_side)

    item = repo.update_asset_control(
        symbol=symbol,
        timeframe=timeframe,
        default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
        enabled=payload.enabled,
        execution_mode=mode,
        trade_side=trade_side,
        soft_risk_limit_usd=payload.soft_risk_limit_usd,
    )

    refreshed = list_asset_controls(timeframe=timeframe, _auth=None, repo=repo)
    for row in refreshed:
        if row.symbol == symbol and row.timeframe == timeframe:
            return row

    raise HTTPException(status_code=500, detail="Updated control row not found")


@router.put("/control-plane/asset-tuning/{symbol:path}", response_model=AssetControlOut)
def update_asset_tuning(
    symbol: str,
    payload: AssetTuningUpdate,
    timeframe: str = Query(...),
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
    cfg = get_config()
    if symbol not in cfg.symbols:
        raise HTTPException(status_code=422, detail=f"Unknown symbol: {symbol}")
    if timeframe not in _control_plane_timeframes(cfg):
        raise HTTPException(status_code=422, detail=f"Unsupported timeframe: {timeframe}")

    meta_note = payload.note
    meta_source = payload.source
    meta_updated_by = payload.updated_by
    updates = payload.model_dump(exclude_none=True, exclude={"note", "source", "updated_by"})
    if not updates:
        raise HTTPException(status_code=422, detail="No tuning fields provided")

    unsupported = sorted(set(updates) - _SIMPLE_TUNING_FIELDS)
    if unsupported:
        raise HTTPException(status_code=422, detail=f"Unsupported tuning fields: {', '.join(unsupported)}")

    if timeframe == cfg.trading_1m.runtime_timeframe:
        base_params = Simple1mParamResolver(cfg).for_symbol(symbol)
        merged = _merged_simple_tuning_params(
            base={
                "bb_length": base_params.bb_length,
                "bb_stdev": base_params.bb_stdev,
                "atr_length": base_params.atr_length,
                "ema_fast": base_params.ema_fast,
                "ema_slow": base_params.ema_slow,
                "bb_entry_deviation": base_params.bb_entry_deviation,
                "bb_exit_deviation": base_params.bb_exit_deviation,
                "slope_lookback_bars": base_params.slope_lookback_bars,
                "slope_flatten_factor": base_params.slope_flatten_factor,
                "stop_atr": base_params.stop_atr,
                "take_profit_atr": base_params.take_profit_atr,
                "max_hold_bars": base_params.max_hold_bars,
                "min_hold_bars": base_params.min_hold_bars,
                "max_take_profit_pct": base_params.max_take_profit_pct,
            },
            override={k: updates[k] for k in updates if k in _SIMPLE_TUNING_FIELDS},
        )
    elif timeframe == cfg.trading_5m.runtime_timeframe:
        base_params = Simple5mParamResolver(cfg).for_symbol(symbol)
        merged = _merged_simple_tuning_params(
            base={
                "bb_length": base_params.bb_length,
                "bb_stdev": base_params.bb_stdev,
                "atr_length": base_params.atr_length,
                "ema_fast": base_params.ema_fast,
                "ema_slow": base_params.ema_slow,
                "bb_entry_deviation": base_params.bb_entry_deviation,
                "bb_exit_deviation": base_params.bb_exit_deviation,
                "slope_lookback_bars": base_params.slope_lookback_bars,
                "slope_flatten_factor": base_params.slope_flatten_factor,
                "stop_atr": base_params.stop_atr,
                "take_profit_atr": base_params.take_profit_atr,
                "max_hold_bars": base_params.max_hold_bars,
                "min_hold_bars": base_params.min_hold_bars,
                "max_take_profit_pct": base_params.max_take_profit_pct,
            },
            override={k: updates[k] for k in updates if k in _SIMPLE_TUNING_FIELDS},
        )
    else:
        raise HTTPException(status_code=422, detail=f"Tuning updates are unsupported for timeframe: {timeframe}")

    repo.create_asset_tuning_version(
        symbol=symbol,
        timeframe=timeframe,
        params_json=merged,
        note=meta_note,
        source=meta_source,
        updated_by=meta_updated_by,
    )

    refreshed = list_asset_controls(timeframe=timeframe, _auth=None, repo=repo)
    for row in refreshed:
        if row.symbol == symbol and row.timeframe == timeframe:
            return row

    raise HTTPException(status_code=500, detail="Updated control row not found")


@router.get("/control-plane/asset-tuning/{symbol:path}", response_model=list[AssetTuningVersionOut])
def list_asset_tuning_versions(
    symbol: str,
    timeframe: str = Query(...),
    limit: int = Query(default=25, ge=1, le=200),
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
    cfg = get_config()
    if symbol not in cfg.symbols:
        raise HTTPException(status_code=422, detail=f"Unknown symbol: {symbol}")
    if timeframe not in _control_plane_timeframes(cfg):
        raise HTTPException(status_code=422, detail=f"Unsupported timeframe: {timeframe}")

    rows = repo.list_asset_tuning_versions(symbol=symbol, timeframe=timeframe, limit=limit)
    return [
        AssetTuningVersionOut(
            id=row.id,
            symbol=row.symbol,
            timeframe=row.timeframe,
            version=row.version,
            params_json=row.params_json,
            note=row.note,
            source=row.source,
            updated_by=row.updated_by,
            is_active=bool(row.is_active),
            created_at=row.created_at,
        )
        for row in rows
    ]


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
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=2000),
    _auth: None = Depends(require_write_access),
    repo: TradingRepository = Depends(get_repo),
):
    rows = repo.list_asset_logs(symbol=symbol, timeframe=timeframe, limit=limit)
    return [
        AssetEngineLogOut(
            id=item.id,
            symbol=item.symbol,
            timeframe=item.timeframe,
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


@router.get("/control-plane/live-readiness", response_model=LiveReadinessOut)
def get_live_readiness(_auth: None = Depends(require_write_access)):
    cfg = get_config()
    runtimes = _runtime_configs(cfg)

    real_adapter_enabled_any = any(rt.execution_adapter == "real" for rt in runtimes)
    live_order_enabled_any = any(rt.execution_adapter == "real" and bool(rt.live_trading_enabled) for rt in runtimes)
    live_ack_required_any = any(rt.execution_adapter == "real" and bool(rt.live_require_explicit_env_ack) for rt in runtimes)
    live_ack_satisfied_any = True
    for rt in runtimes:
        if rt.execution_adapter != "real" or not bool(rt.live_require_explicit_env_ack):
            continue
        env_val = os.getenv(rt.live_ack_env_var_name, "")
        if env_val != rt.live_ack_env_var_value:
            live_ack_satisfied_any = False
            break

    api_key_present = bool(cfg.providers.ccxt.api_key)
    api_secret_present = bool(cfg.providers.ccxt.api_secret)

    balance_readable = False
    balance_error = None
    try:
        exchange = _build_readonly_exchange(cfg)
        exchange.fetch_balance()
        balance_readable = True
    except Exception as exc:  # noqa: BLE001
        balance_error = str(exc)

    note = None
    if not api_key_present or not api_secret_present:
        note = "Exchange API credentials missing in environment."
    elif not balance_readable:
        note = "Credentials found but exchange balance query failed."
    elif real_adapter_enabled_any and not live_order_enabled_any:
        note = "Readiness is good for balance checks; live order routing is still disabled by config."
    elif not real_adapter_enabled_any:
        note = "Balance checks are available; no runtime is currently configured for real execution."
    else:
        note = "Live readiness checks passed."

    return LiveReadinessOut(
        venue=cfg.providers.ccxt.venue,
        sandbox=bool(cfg.providers.ccxt.sandbox),
        api_key_present=api_key_present,
        api_secret_present=api_secret_present,
        real_adapter_enabled_any=real_adapter_enabled_any,
        live_order_enabled_any=live_order_enabled_any,
        live_ack_required_any=live_ack_required_any,
        live_ack_satisfied_any=live_ack_satisfied_any,
        balance_readable=balance_readable,
        balance_error=balance_error,
        note=note,
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
