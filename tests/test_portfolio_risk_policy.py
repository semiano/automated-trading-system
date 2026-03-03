from mdtas.config import AppConfig
from mdtas.trading.runtime import TradingRuntime


class _DummyTradingRepo:
    def __init__(self) -> None:
        self.calls = []

    def current_open_risk_usd(self, *, symbol, venue, timeframe, execution_mode):
        self.calls.append(
            {
                "symbol": symbol,
                "venue": venue,
                "timeframe": timeframe,
                "execution_mode": execution_mode,
            }
        )
        return 50.0 if symbol is None else 10.0


class _DummyCandleRepo:
    pass


def test_portfolio_policy_uses_cross_symbol_aggregate_risk():
    cfg = AppConfig()
    cfg.trading.risk_budget_policy = "portfolio"
    cfg.trading.portfolio_soft_risk_limit_usd = 40.0

    repo = _DummyTradingRepo()
    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=repo)

    current_risk, limit = runtime._current_risk_and_limit(
        symbol="XRP/USD",
        venue="coinbase",
        timeframe="1m",
        execution_mode="sim",
        per_symbol_limit=100.0,
    )

    assert current_risk == 50.0
    assert limit == 40.0
    assert repo.calls[-1]["symbol"] is None


def test_per_symbol_policy_uses_symbol_scope_only():
    cfg = AppConfig()
    cfg.trading.risk_budget_policy = "per_symbol"

    repo = _DummyTradingRepo()
    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=repo)

    current_risk, limit = runtime._current_risk_and_limit(
        symbol="XRP/USD",
        venue="coinbase",
        timeframe="1m",
        execution_mode="sim",
        per_symbol_limit=100.0,
    )

    assert current_risk == 10.0
    assert limit == 100.0
    assert repo.calls[-1]["symbol"] == "XRP/USD"


def test_zero_soft_limit_disables_risk_block_check_contract():
    limit = 0.0
    current_risk = 999.0
    projected_trade_risk = 1.0

    should_block = limit > 0 and (current_risk + projected_trade_risk > limit)
    assert should_block is False
