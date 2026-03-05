import pytest

from mdtas.trading.execution import CcxtExecutionAdapter, SymbolExecutionConstraints


class _FakeExchange:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.sandbox_enabled = False
        self.orders = []

    def set_sandbox_mode(self, enabled):
        self.sandbox_enabled = bool(enabled)

    def load_markets(self):
        return None

    def create_order(self, symbol, type, side, amount, price=None, **kwargs):
        self.orders.append(
            {
                "symbol": symbol,
                "type": type,
                "side": side,
                "amount": amount,
                "price": price,
            }
        )
        return {
            "filled": amount,
            "average": 1.0,
            "cost": float(amount),
            "fee": {"cost": 0.01},
        }


def _build_adapter(monkeypatch, *, set_ack_env=True, **overrides):
    import mdtas.trading.execution as execution_mod

    monkeypatch.setattr(execution_mod.ccxt, "binance", _FakeExchange)
    if set_ack_env:
        monkeypatch.setenv("MDTAS_ENABLE_LIVE_TRADING", "YES_I_ACKNOWLEDGE_LIVE_TRADING_RISK")
    defaults = {
        "venue": "binance",
        "rate_limit": True,
        "api_key": "k",
        "api_secret": "s",
        "api_password": None,
        "sandbox": True,
        "live_trading_enabled": True,
        "live_allow_short": True,
        "live_max_order_notional_usd": 10.0,
        "live_allowed_symbols": ["XRP/USDT"],
        "live_require_explicit_env_ack": True,
        "live_ack_env_var_name": "MDTAS_ENABLE_LIVE_TRADING",
        "live_ack_env_var_value": "YES_I_ACKNOWLEDGE_LIVE_TRADING_RISK",
    }
    defaults.update(overrides)
    return CcxtExecutionAdapter(**defaults)


def test_live_adapter_requires_ack_env(monkeypatch):
    monkeypatch.delenv("MDTAS_ENABLE_LIVE_TRADING", raising=False)
    with pytest.raises(ValueError):
        _build_adapter(monkeypatch, set_ack_env=False)


def test_live_adapter_long_entry_and_exit_use_market_sides(monkeypatch):
    adapter = _build_adapter(monkeypatch)
    constraints = SymbolExecutionConstraints(fee_bps=0.0)

    entry = adapter.submit_entry(
        symbol="XRP/USDT",
        raw_price=1.0,
        qty=10.0,
        trade_side="long",
        constraints=constraints,
    )
    exit_fill = adapter.submit_exit(
        symbol="XRP/USDT",
        raw_price=1.0,
        qty=10.0,
        trade_side="long",
        constraints=constraints,
    )

    assert adapter.exchange.orders[0]["type"] == "market"
    assert adapter.exchange.orders[0]["side"] == "buy"
    assert adapter.exchange.orders[1]["side"] == "sell"
    assert entry.notional_usd == 10.0
    assert exit_fill.notional_usd == 10.0


def test_live_adapter_short_entry_and_exit_use_market_sides(monkeypatch):
    adapter = _build_adapter(monkeypatch, live_allow_short=True)
    constraints = SymbolExecutionConstraints(fee_bps=0.0)

    entry = adapter.submit_entry(
        symbol="XRP/USDT",
        raw_price=1.0,
        qty=10.0,
        trade_side="short",
        constraints=constraints,
    )
    exit_fill = adapter.submit_exit(
        symbol="XRP/USDT",
        raw_price=1.0,
        qty=10.0,
        trade_side="short",
        constraints=constraints,
    )

    assert adapter.exchange.orders[0]["side"] == "sell"
    assert adapter.exchange.orders[1]["side"] == "buy"
    assert entry.notional_usd == 10.0
    assert exit_fill.notional_usd == 10.0


def test_live_adapter_blocks_short_when_disabled(monkeypatch):
    adapter = _build_adapter(monkeypatch, live_allow_short=False)
    constraints = SymbolExecutionConstraints(fee_bps=0.0)

    with pytest.raises(ValueError):
        adapter.submit_entry(
            symbol="XRP/USDT",
            raw_price=1.0,
            qty=10.0,
            trade_side="short",
            constraints=constraints,
        )


def test_live_adapter_blocks_notional_above_cap(monkeypatch):
    adapter = _build_adapter(monkeypatch, live_max_order_notional_usd=10.0)
    constraints = SymbolExecutionConstraints(fee_bps=0.0)

    with pytest.raises(ValueError):
        adapter.submit_entry(
            symbol="XRP/USDT",
            raw_price=1.5,
            qty=10.0,
            trade_side="long",
            constraints=constraints,
        )


def test_live_adapter_blocks_symbol_not_allowed(monkeypatch):
    adapter = _build_adapter(monkeypatch, live_allowed_symbols=["XRP/USDT"])
    constraints = SymbolExecutionConstraints(fee_bps=0.0)

    with pytest.raises(ValueError):
        adapter.submit_entry(
            symbol="HBAR/USDT",
            raw_price=1.0,
            qty=10.0,
            trade_side="long",
            constraints=constraints,
        )
