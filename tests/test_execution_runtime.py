from mdtas.config import AppConfig
from mdtas.trading.execution import (
    PaperExecutionAdapter,
    SymbolExecutionConstraints,
    apply_slippage,
    gap_aware_raw_exit_price,
)
from mdtas.trading.runtime import TradingRuntime


def test_apply_slippage_buy_sell_semantics():
    assert apply_slippage(100.0, side="buy", slip=0.001) == 100.1
    assert apply_slippage(100.0, side="sell", slip=0.001) == 99.9


def test_paper_adapter_entry_exit_side_semantics():
    adapter = PaperExecutionAdapter(slippage_bps=10.0)
    constraints = SymbolExecutionConstraints(fee_bps=0.0)

    long_entry = adapter.submit_entry(symbol="XRP/USDT", raw_price=100.0, qty=1.0, trade_side="long", constraints=constraints)
    long_exit = adapter.submit_exit(symbol="XRP/USDT", raw_price=100.0, qty=1.0, trade_side="long", constraints=constraints)
    short_entry = adapter.submit_entry(symbol="XRP/USDT", raw_price=100.0, qty=1.0, trade_side="short", constraints=constraints)
    short_exit = adapter.submit_exit(symbol="XRP/USDT", raw_price=100.0, qty=1.0, trade_side="short", constraints=constraints)

    assert long_entry.side == "buy"
    assert long_exit.side == "sell"
    assert short_entry.side == "sell"
    assert short_exit.side == "buy"

    assert long_entry.price > 100.0
    assert long_exit.price < 100.0
    assert short_entry.price < 100.0
    assert short_exit.price > 100.0


def test_gap_aware_stop_and_take_profit():
    long_stop_gap = gap_aware_raw_exit_price(
        trade_side="long",
        reason="stop",
        bar_open=95.0,
        stop_price=98.0,
        take_profit_price=110.0,
    )
    short_stop_gap = gap_aware_raw_exit_price(
        trade_side="short",
        reason="stop",
        bar_open=105.0,
        stop_price=102.0,
        take_profit_price=90.0,
    )
    long_tp_gap = gap_aware_raw_exit_price(
        trade_side="long",
        reason="take_profit",
        bar_open=112.0,
        stop_price=95.0,
        take_profit_price=110.0,
    )
    short_tp_gap = gap_aware_raw_exit_price(
        trade_side="short",
        reason="take_profit",
        bar_open=88.0,
        stop_price=105.0,
        take_profit_price=90.0,
    )

    assert long_stop_gap == 95.0
    assert short_stop_gap == 105.0
    assert long_tp_gap == 112.0
    assert short_tp_gap == 88.0


class _DummyTradingRepo:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def current_open_risk_usd(self, *, symbol, venue, timeframe, execution_mode):
        self.calls.append(
            {
                "symbol": symbol,
                "venue": venue,
                "timeframe": timeframe,
                "execution_mode": execution_mode,
            }
        )
        return 42.0 if symbol is None else 7.0


class _DummyCandleRepo:
    pass


def test_runtime_risk_policy_portfolio_uses_global_scope():
    cfg = AppConfig()
    cfg.trading.risk_budget_policy = "portfolio"
    cfg.trading.portfolio_soft_risk_limit_usd = 123.0

    repo = _DummyTradingRepo()
    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=repo)

    current, limit = runtime._current_risk_and_limit(
        symbol="XRP/USD",
        venue="coinbase",
        timeframe="1m",
        execution_mode="sim",
        per_symbol_limit=11.0,
    )

    assert current == 42.0
    assert limit == 123.0
    assert repo.calls[-1]["symbol"] is None


def test_runtime_risk_policy_per_symbol_uses_symbol_scope():
    cfg = AppConfig()
    cfg.trading.risk_budget_policy = "per_symbol"

    repo = _DummyTradingRepo()
    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=repo)

    current, limit = runtime._current_risk_and_limit(
        symbol="XRP/USD",
        venue="coinbase",
        timeframe="1m",
        execution_mode="sim",
        per_symbol_limit=55.0,
    )

    assert current == 7.0
    assert limit == 55.0
    assert repo.calls[-1]["symbol"] == "XRP/USD"
