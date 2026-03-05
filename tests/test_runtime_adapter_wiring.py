from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from mdtas.config import AppConfig
from mdtas.trading.execution import Fill, SymbolExecutionConstraints
from mdtas.trading.runtime import TradingRuntime


@dataclass
class _Control:
    enabled: bool = True
    execution_mode: str = "sim"
    trade_side: str = "long_only"
    soft_risk_limit_usd: float = 1000.0


@dataclass
class _Position:
    symbol: str = "XRP/USDT"
    venue: str = "coinbase"
    timeframe: str = "1m"
    execution_mode: str = "sim"
    trade_side: str = "long"
    entry_price: float = 100.0
    qty: float = 1.0
    entry_fee: float = 0.1
    stop_price: float | None = 99.0
    take_profit_price: float | None = 110.0
    hold_bars: int = 0


@dataclass
class _Trade:
    symbol: str
    timeframe: str
    trade_side: str
    net_pnl: float
    exit_ts: datetime


class _Repo:
    def __init__(self) -> None:
        self.open_calls: list[dict] = []
        self.close_calls: list[dict] = []
        self._open_position = None

    def mark_asset_run(self, **kwargs):
        return _Control()

    def set_asset_state(self, **kwargs):
        return None

    def get_open_position(self, symbol, venue, timeframe, execution_mode):
        return self._open_position

    def current_open_risk_usd(self, **kwargs):
        return 0.0

    def open_position(self, **kwargs):
        self.open_calls.append(kwargs)

    def close_position(self, **kwargs):
        self.close_calls.append(kwargs)
        return _Trade(
            symbol=kwargs["position"].symbol,
            timeframe=kwargs["position"].timeframe,
            trade_side=kwargs["position"].trade_side,
            net_pnl=1.0,
            exit_ts=kwargs["exit_ts"],
        )

    def touch_position(self, position, hold_bars, last_price):
        return None


class _CandleRepo:
    def get_candles(self, **kwargs):
        now = datetime.utcnow().replace(microsecond=0)
        ts = [now - timedelta(minutes=i) for i in range(60)][::-1]
        return pd.DataFrame(
            {
                "ts": ts,
                "open": [100.0] * 60,
                "high": [101.0] * 60,
                "low": [99.0] * 60,
                "close": [100.2] * 60,
                "volume": [1.0] * 60,
            }
        )


def _mock_compute_for_entry(frame, indicators, params):
    now = datetime.utcnow().replace(microsecond=0)
    return pd.DataFrame(
        [
            {
                "ts": now - timedelta(minutes=1),
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.4,
                "rsi": 20.0,
                "atr": 1.0,
                "ema20": 100.0,
                "ema50": 99.5,
            },
            {
                "ts": now,
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.3,
                "rsi": 25.0,
                "atr": 1.0,
                "ema20": 100.0,
                "ema50": 99.5,
            },
        ]
    )


def _mock_compute_for_exit(frame, indicators, params):
    now = datetime.utcnow().replace(microsecond=0)
    return pd.DataFrame(
        [
            {
                "ts": now - timedelta(minutes=1),
                "open": 100.0,
                "high": 100.8,
                "low": 99.6,
                "close": 100.2,
                "rsi": 40.0,
                "atr": 1.0,
                "ema20": 100.0,
                "ema50": 99.5,
            },
            {
                "ts": now,
                "open": 98.5,
                "high": 99.2,
                "low": 98.0,
                "close": 98.8,
                "rsi": 45.0,
                "atr": 1.0,
                "ema20": 99.9,
                "ema50": 99.4,
            },
        ]
    )


class _ExecutorSpy:
    def __init__(self):
        self.entry_called = False
        self.exit_called = False

    def submit_entry(self, *, symbol, raw_price, qty, trade_side, constraints: SymbolExecutionConstraints):
        self.entry_called = True
        return Fill(side="buy", price=101.0, qty=qty, notional_usd=101.0 * qty, fee_usd=0.2)

    def submit_exit(self, *, symbol, raw_price, qty, trade_side, constraints: SymbolExecutionConstraints):
        self.exit_called = True
        return Fill(side="sell", price=98.5, qty=qty, notional_usd=98.5 * qty, fee_usd=0.2)


def test_runtime_entry_uses_adapter(monkeypatch):
    monkeypatch.setattr("mdtas.trading.runtime.compute", _mock_compute_for_entry)
    monkeypatch.setattr(TradingRuntime, "_entry_diagnostics_long", lambda self, prev, params: (True, "forced_long"))
    monkeypatch.setattr(TradingRuntime, "_entry_diagnostics_short", lambda self, prev, params: (False, "forced_short"))

    cfg = AppConfig()
    cfg.trading.position_size_usd = 100.0
    repo = _Repo()
    runtime = TradingRuntime(cfg=cfg, candle_repo=_CandleRepo(), trading_repo=repo)
    spy = _ExecutorSpy()
    runtime.execution = spy

    runtime.evaluate_symbol("XRP/USDT", "coinbase")

    assert spy.entry_called is True
    assert len(repo.open_calls) == 1
    assert repo.open_calls[0]["entry_price"] == 101.0
    assert repo.open_calls[0]["entry_fee"] == 0.2


def test_runtime_exit_uses_adapter_and_gap_open(monkeypatch):
    monkeypatch.setattr("mdtas.trading.runtime.compute", _mock_compute_for_exit)

    cfg = AppConfig()
    repo = _Repo()
    repo._open_position = _Position(stop_price=99.0, take_profit_price=110.0, trade_side="long")
    runtime = TradingRuntime(cfg=cfg, candle_repo=_CandleRepo(), trading_repo=repo)
    spy = _ExecutorSpy()
    runtime.execution = spy

    runtime.evaluate_symbol("XRP/USDT", "coinbase")

    assert spy.exit_called is True
    assert len(repo.close_calls) == 1
    assert repo.close_calls[0]["exit_price"] == 98.5
    assert repo.close_calls[0]["exit_fee"] == 0.2
