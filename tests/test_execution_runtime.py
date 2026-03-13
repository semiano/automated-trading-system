from mdtas.config import AppConfig
from mdtas.trading.execution import (
    PaperExecutionAdapter,
    SymbolExecutionConstraints,
    apply_slippage,
    gap_aware_raw_exit_price,
)
from mdtas.trading.runtime import TradingRuntime
import pandas as pd


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

    def get_or_create_sim_wallet_balance(self, symbol):
        class _Row:
            cash_adjustment_usd = 0.0
            asset_adjustment_usd = 0.0

        return _Row()

    def realized_net_pnl_by_symbol(self, execution_mode=None):
        return {}

    def list_open_positions(self, **kwargs):
        return []


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


def test_range_revert_bb_threshold_long_short():
    cfg = AppConfig()
    cfg.trading.bb_entry_mode = "range_revert"
    cfg.trading.bb_range_threshold_pct = 0.8

    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=_DummyTradingRepo())
    params = runtime.params_resolver.for_symbol("XRP/USDT")

    long_pass_row = pd.Series(
        {
            "rsi": params.rsi_entry - 1.0,
            "atr": 0.01,
            "close": 18.0,
            f"ema{params.ema_fast}": 17.0,
            "bb_lower": 10.0,
            "bb_upper": 20.0,
        }
    )
    long_fail_row = pd.Series(
        {
            "rsi": params.rsi_entry - 1.0,
            "atr": 0.01,
            "close": 18.5,
            f"ema{params.ema_fast}": 17.0,
            "bb_lower": 10.0,
            "bb_upper": 20.0,
        }
    )

    short_pass_row = pd.Series(
        {
            "rsi": params.rsi_exit + 1.0,
            "atr": 0.01,
            "close": 12.0,
            f"ema{params.ema_fast}": 13.0,
            "bb_lower": 10.0,
            "bb_upper": 20.0,
        }
    )
    short_fail_row = pd.Series(
        {
            "rsi": params.rsi_exit + 1.0,
            "atr": 0.01,
            "close": 11.5,
            f"ema{params.ema_fast}": 13.0,
            "bb_lower": 10.0,
            "bb_upper": 20.0,
        }
    )

    long_pass, _ = runtime._entry_diagnostics_long(long_pass_row, params, "range_revert")
    long_fail, _ = runtime._entry_diagnostics_long(long_fail_row, params, "range_revert")
    short_pass, _ = runtime._entry_diagnostics_short(short_pass_row, params, "range_revert")
    short_fail, _ = runtime._entry_diagnostics_short(short_fail_row, params, "range_revert")

    assert long_pass is True
    assert long_fail is False
    assert short_pass is True
    assert short_fail is False


def test_momentum_swing_gates_long_short_entries():
    cfg = AppConfig()
    cfg.trading.bb_entry_mode = "off"
    cfg.trading.momentum_swing_enabled = True

    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=_DummyTradingRepo())
    params = runtime.params_resolver.for_symbol("XRP/USDT")

    long_pass_row = pd.Series(
        {
            "rsi": params.rsi_entry - 1.0,
            "atr": 0.01,
            "close": 18.0,
            f"ema{params.ema_fast}": 17.0,
            "swing_long_ready": True,
            "mom_roc": 0.01,
        }
    )
    long_fail_row = pd.Series(
        {
            "rsi": params.rsi_entry - 1.0,
            "atr": 0.01,
            "close": 18.0,
            f"ema{params.ema_fast}": 17.0,
            "swing_long_ready": False,
            "mom_roc": 0.01,
        }
    )

    short_pass_row = pd.Series(
        {
            "rsi": params.rsi_exit + 1.0,
            "atr": 0.01,
            "close": 12.0,
            f"ema{params.ema_fast}": 13.0,
            "swing_short_ready": True,
            "mom_roc": -0.01,
        }
    )
    short_fail_row = pd.Series(
        {
            "rsi": params.rsi_exit + 1.0,
            "atr": 0.01,
            "close": 12.0,
            f"ema{params.ema_fast}": 13.0,
            "swing_short_ready": False,
            "mom_roc": -0.01,
        }
    )

    long_pass, _ = runtime._entry_diagnostics_long(long_pass_row, params, "off")
    long_fail, _ = runtime._entry_diagnostics_long(long_fail_row, params, "off")
    short_pass, _ = runtime._entry_diagnostics_short(short_pass_row, params, "off")
    short_fail, _ = runtime._entry_diagnostics_short(short_fail_row, params, "off")

    assert long_pass is True
    assert long_fail is False
    assert short_pass is True
    assert short_fail is False


def test_min_entry_atr_pct_blocks_low_volatility_entries():
    cfg = AppConfig()
    cfg.trading.bb_entry_mode = "off"
    cfg.trading.momentum_swing_enabled = False
    cfg.trading.min_entry_atr_pct = 0.12

    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=_DummyTradingRepo())
    params = runtime.params_resolver.for_symbol("XRP/USDT")

    low_vol_long_row = pd.Series(
        {
            "rsi": params.rsi_entry - 1.0,
            "atr": 0.001,
            "close": 1.50,
            f"ema{params.ema_fast}": 1.40,
        }
    )
    low_vol_short_row = pd.Series(
        {
            "rsi": params.rsi_exit + 1.0,
            "atr": 0.001,
            "close": 1.30,
            f"ema{params.ema_fast}": 1.40,
        }
    )

    long_ok, _ = runtime._entry_diagnostics_long(low_vol_long_row, params, "off")
    short_ok, _ = runtime._entry_diagnostics_short(low_vol_short_row, params, "off")

    assert long_ok is False
    assert short_ok is False


def test_min_entry_atr_pct_allows_high_volatility_entries():
    cfg = AppConfig()
    cfg.trading.bb_entry_mode = "off"
    cfg.trading.momentum_swing_enabled = False
    cfg.trading.min_entry_atr_pct = 0.12

    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=_DummyTradingRepo())
    params = runtime.params_resolver.for_symbol("XRP/USDT")

    high_vol_long_row = pd.Series(
        {
            "rsi": params.rsi_entry - 1.0,
            "atr": 0.003,
            "close": 1.50,
            f"ema{params.ema_fast}": 1.40,
        }
    )
    high_vol_short_row = pd.Series(
        {
            "rsi": params.rsi_exit + 1.0,
            "atr": 0.003,
            "close": 1.30,
            f"ema{params.ema_fast}": 1.40,
        }
    )

    long_ok, _ = runtime._entry_diagnostics_long(high_vol_long_row, params, "off")
    short_ok, _ = runtime._entry_diagnostics_short(high_vol_short_row, params, "off")

    assert long_ok is True
    assert short_ok is True


def test_dynamic_volatility_override_allows_low_atr_long_when_below_band_is_extreme():
    cfg = AppConfig()
    cfg.trading.bb_entry_mode = "off"
    cfg.trading.momentum_swing_enabled = False
    cfg.trading.min_entry_atr_pct = 0.12
    cfg.trading.dynamic_volatility_bb_override_enabled = True
    cfg.trading.dynamic_volatility_extreme_bb_width_ratio = 1.2

    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=_DummyTradingRepo())
    params = runtime.params_resolver.for_symbol("XRP/USDT")

    row = pd.Series(
        {
            "rsi": params.rsi_entry - 2.0,
            "atr": 0.001,
            "close": 1.17,
            f"ema{params.ema_fast}": 1.10,
            "bb_lower": 1.30,
            "bb_upper": 1.40,
        }
    )

    long_ok, note = runtime._entry_diagnostics_long(row, params, "off")

    assert long_ok is True
    assert "dyn_vol_long_outside_ratio" in note


def test_dynamic_volatility_override_allows_low_atr_short_when_above_band_is_extreme():
    cfg = AppConfig()
    cfg.trading.bb_entry_mode = "off"
    cfg.trading.momentum_swing_enabled = False
    cfg.trading.min_entry_atr_pct = 0.12
    cfg.trading.dynamic_volatility_bb_override_enabled = True
    cfg.trading.dynamic_volatility_extreme_bb_width_ratio = 1.2

    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=_DummyTradingRepo())
    params = runtime.params_resolver.for_symbol("XRP/USDT")

    row = pd.Series(
        {
            "rsi": params.rsi_exit + 2.0,
            "atr": 0.001,
            "close": 1.53,
            f"ema{params.ema_fast}": 1.60,
            "bb_lower": 1.30,
            "bb_upper": 1.40,
        }
    )

    short_ok, note = runtime._entry_diagnostics_short(row, params, "off")

    assert short_ok is True
    assert "dyn_vol_short_outside_ratio" in note


def test_sim_wallet_available_usd_is_side_aware_with_adjustments():
    cfg = AppConfig()
    repo = _DummyTradingRepo()

    class _Pos:
        def __init__(self, side: str, entry_price: float, last_price: float, qty: float, entry_fee: float) -> None:
            self.trade_side = side
            self.entry_price = entry_price
            self.last_price = last_price
            self.qty = qty
            self.entry_fee = entry_fee

    class _Row:
        cash_adjustment_usd = 20.0
        asset_adjustment_usd = 10.0

    repo.realized_net_pnl_by_symbol = lambda execution_mode=None: {"XRP/USDT": 5.0}
    repo.list_open_positions = lambda **kwargs: [
        _Pos("long", entry_price=10.0, last_price=10.0, qty=3.0, entry_fee=0.0),
        _Pos("short", entry_price=10.0, last_price=10.0, qty=1.0, entry_fee=0.0),
    ]
    repo.get_or_create_sim_wallet_balance = lambda symbol: _Row()

    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=repo)
    cash_available, asset_available = runtime._sim_wallet_available_usd(
        symbol="XRP/USDT",
        venue="coinbase",
        timeframe="1m",
        soft_risk_limit_usd=100.0,
    )

    assert cash_available == 52.5
    assert asset_available == 82.5
