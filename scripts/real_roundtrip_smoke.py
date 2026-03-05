from __future__ import annotations

from mdtas.config import get_config
from mdtas.trading.execution import CcxtExecutionAdapter, SymbolExecutionConstraints


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
    qty = 0.00005
    constraints = SymbolExecutionConstraints()

    print(f"symbol={symbol} price={price:.8f} qty={qty:.8f}")

    long_entry = adapter.submit_entry(
        symbol=symbol,
        raw_price=price,
        qty=qty,
        trade_side="long",
        constraints=constraints,
    )
    print(f"long_entry=ok side={long_entry.side} qty={long_entry.qty:.8f} notional={long_entry.notional_usd:.8f}")

    long_exit = adapter.submit_exit(
        symbol=symbol,
        raw_price=price,
        qty=float(long_entry.qty),
        trade_side="long",
        constraints=constraints,
    )
    print(f"long_exit=ok side={long_exit.side} qty={long_exit.qty:.8f} notional={long_exit.notional_usd:.8f}")

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
