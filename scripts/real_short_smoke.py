from __future__ import annotations

from mdtas.config import get_config
from mdtas.trading.execution import CcxtExecutionAdapter, SymbolExecutionConstraints, round_down_to_step


def main() -> int:
    cfg = get_config()
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

    symbol = "BTC/USD"
    ticker = adapter.exchange.fetch_ticker(symbol)
    price = float(ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask"))
    balance = adapter.exchange.fetch_balance()
    btc = balance.get("BTC") or {}
    free_btc = float(btc.get("free") or 0.0)

    constraints_cfg = cfg.trading.per_asset_constraints.get(symbol, cfg.trading.default_constraints)
    qty_step = float(constraints_cfg.qty_step)

    max_qty_by_cap = float(cfg.trading.live_max_order_notional_usd) / price
    qty = min(free_btc * 0.99, max_qty_by_cap * 0.99)
    qty = round_down_to_step(qty, qty_step)

    print(f"symbol={symbol} price={price:.8f} free_btc={free_btc:.8f} qty={qty:.8f}")

    if qty <= 0:
        print("short_test=skipped insufficient BTC free balance for a capped short-entry sell")
        return 2

    constraints = SymbolExecutionConstraints()
    short_entry = adapter.submit_entry(
        symbol=symbol,
        raw_price=price,
        qty=qty,
        trade_side="short",
        constraints=constraints,
    )
    print(f"short_entry=ok side={short_entry.side} qty={short_entry.qty:.8f} notional={short_entry.notional_usd:.8f}")

    short_exit = adapter.submit_exit(
        symbol=symbol,
        raw_price=price,
        qty=float(short_entry.qty),
        trade_side="short",
        constraints=constraints,
    )
    print(f"short_exit=ok side={short_exit.side} qty={short_exit.qty:.8f} notional={short_exit.notional_usd:.8f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
