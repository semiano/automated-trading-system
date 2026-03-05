from __future__ import annotations

from typing import Any

import ccxt

from mdtas.config import get_config
from mdtas.trading.execution import CcxtExecutionAdapter, SymbolExecutionConstraints, round_down_to_step


def _price_from_ticker(ticker: dict[str, Any]) -> float:
    for key in ("last", "close", "bid", "ask"):
        value = ticker.get(key)
        if value is not None:
            price = float(value)
            if price > 0:
                return price
    raise ValueError("No usable price in ticker")


def main() -> int:
    cfg = get_config()
    print(f"provider={cfg.providers.default_provider}")
    print(f"venue={cfg.providers.ccxt.venue}")
    print(f"sandbox={cfg.providers.ccxt.sandbox}")
    print(f"execution_adapter={cfg.trading.execution_adapter}")
    print(f"live_trading_enabled={cfg.trading.live_trading_enabled}")

    adapter = CcxtExecutionAdapter(
        venue=cfg.providers.ccxt.venue,
        rate_limit=cfg.providers.ccxt.rate_limit,
        api_key=cfg.providers.ccxt.api_key,
        api_secret=cfg.providers.ccxt.api_secret,
        api_password=cfg.providers.ccxt.api_password,
        sandbox=cfg.providers.ccxt.sandbox,
        live_trading_enabled=cfg.trading.live_trading_enabled,
        live_allow_short=cfg.trading.live_allow_short,
        live_max_order_notional_usd=cfg.trading.live_max_order_notional_usd,
        live_allowed_symbols=cfg.trading.live_allowed_symbols,
        live_require_explicit_env_ack=cfg.trading.live_require_explicit_env_ack,
        live_ack_env_var_name=cfg.trading.live_ack_env_var_name,
        live_ack_env_var_value=cfg.trading.live_ack_env_var_value,
    )

    supported = [symbol for symbol in cfg.symbols if symbol in adapter.exchange.markets]
    if not supported:
        print("No configured symbols are supported on this venue in current mode.")
        return 2
    symbol = supported[0]
    constraints_cfg = cfg.trading.per_asset_constraints.get(symbol, cfg.trading.default_constraints)
    constraints = SymbolExecutionConstraints(
        min_notional_usd=float(constraints_cfg.min_notional_usd),
        qty_step=float(constraints_cfg.qty_step),
        price_tick=float(constraints_cfg.price_tick) if constraints_cfg.price_tick is not None else None,
        fee_bps=float(constraints_cfg.fee_bps),
    )

    ticker = adapter.exchange.fetch_ticker(symbol)
    raw_price = _price_from_ticker(ticker)
    target_notional = min(float(cfg.trading.live_max_order_notional_usd), 10.0)
    qty = target_notional / raw_price
    qty = round_down_to_step(qty, constraints.qty_step)
    if qty <= 0:
        print("Computed qty is zero after step rounding")
        return 3

    print(f"symbol={symbol}")
    print(f"raw_price={raw_price:.10f}")
    print(f"qty={qty:.10f}")
    print(f"target_notional={target_notional:.10f}")

    failures: list[str] = []

    def run_step(name: str, fn):
        try:
            fill = fn()
            print(f"{name}=ok side={fill.side} price={fill.price:.10f} qty={fill.qty:.10f} notional={fill.notional_usd:.10f} fee={fill.fee_usd:.10f}")
            return fill
        except ccxt.BaseError as exc:
            msg = f"{name}=ccxt_error {type(exc).__name__}: {exc}"
            print(msg)
            failures.append(msg)
            return None
        except Exception as exc:  # noqa: BLE001
            msg = f"{name}=error {type(exc).__name__}: {exc}"
            print(msg)
            failures.append(msg)
            return None

    long_entry = run_step(
        "long_entry",
        lambda: adapter.submit_entry(
            symbol=symbol,
            raw_price=raw_price,
            qty=qty,
            trade_side="long",
            constraints=constraints,
        ),
    )
    if long_entry is not None:
        run_step(
            "long_exit",
            lambda: adapter.submit_exit(
                symbol=symbol,
                raw_price=raw_price,
                qty=float(long_entry.qty),
                trade_side="long",
                constraints=constraints,
            ),
        )

    short_entry = run_step(
        "short_entry",
        lambda: adapter.submit_entry(
            symbol=symbol,
            raw_price=raw_price,
            qty=qty,
            trade_side="short",
            constraints=constraints,
        ),
    )
    if short_entry is not None:
        run_step(
            "short_exit",
            lambda: adapter.submit_exit(
                symbol=symbol,
                raw_price=raw_price,
                qty=float(short_entry.qty),
                trade_side="short",
                constraints=constraints,
            ),
        )

    try:
        adapter.submit_entry(
            symbol=symbol,
            raw_price=raw_price,
            qty=qty * 2.0,
            trade_side="long",
            constraints=constraints,
        )
        msg = "cap_guard_check=unexpected_success"
        print(msg)
        failures.append(msg)
    except ValueError as exc:
        print(f"cap_guard_check=ok blocked: {exc}")
    except ccxt.BaseError as exc:
        msg = f"cap_guard_check=ccxt_error {type(exc).__name__}: {exc}"
        print(msg)
        failures.append(msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"cap_guard_check=error {type(exc).__name__}: {exc}"
        print(msg)
        failures.append(msg)

    if failures:
        print(f"result=completed_with_failures count={len(failures)}")
        return 4

    print("result=all_operations_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
