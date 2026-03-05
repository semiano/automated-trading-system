from __future__ import annotations

from mdtas.ingestion.rollup import rollup_candles
from mdtas.ingestion.trade_aggregator import Candle


def _mk_1m(symbol: str, ts_close: int, open_: float, high: float, low: float, close: float, volume: float) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe="1m",
        ts_close=ts_close,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_rollup_5m_alignment_and_values():
    five_min_close = ((1_700_000_000_000 // 300_000) + 1) * 300_000
    close_values = [five_min_close - 240_000, five_min_close - 180_000, five_min_close - 120_000, five_min_close - 60_000, five_min_close]
    candles = [
        _mk_1m("XRP/USDT", close_values[0], 1.0, 1.1, 0.9, 1.0, 10.0),
        _mk_1m("XRP/USDT", close_values[1], 1.0, 1.2, 0.95, 1.1, 11.0),
        _mk_1m("XRP/USDT", close_values[2], 1.1, 1.3, 1.0, 1.2, 12.0),
        _mk_1m("XRP/USDT", close_values[3], 1.2, 1.25, 1.05, 1.15, 13.0),
        _mk_1m("XRP/USDT", close_values[4], 1.15, 1.4, 1.1, 1.3, 14.0),
    ]

    out = rollup_candles(candles, "5m")
    assert len(out) == 1
    row = out[0]
    assert row.ts_close == five_min_close
    assert row.open == 1.0
    assert row.high == 1.4
    assert row.low == 0.9
    assert row.close == 1.3
    assert row.volume == 60.0


def test_rollup_does_not_emit_partial_group():
    candles = [
        _mk_1m("HBAR/USDT", 1_700_000_060_000, 0.1, 0.11, 0.09, 0.1, 5.0),
        _mk_1m("HBAR/USDT", 1_700_000_120_000, 0.1, 0.12, 0.095, 0.11, 5.0),
        _mk_1m("HBAR/USDT", 1_700_000_240_000, 0.11, 0.12, 0.10, 0.105, 5.0),
        _mk_1m("HBAR/USDT", 1_700_000_300_000, 0.105, 0.13, 0.10, 0.12, 5.0),
    ]

    out = rollup_candles(candles, "5m")
    assert out == []