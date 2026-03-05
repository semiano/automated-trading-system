from __future__ import annotations

from mdtas.ingestion.trade_aggregator import Trade, TradeToCandleAggregator


def test_trade_aggregator_ohlcv_single_minute():
    aggregator = TradeToCandleAggregator()
    minute_start = (1_700_000_000_000 // 60_000) * 60_000

    assert aggregator.ingest_trade(Trade(ts=minute_start + 100, price=1.00, size=10.0, symbol="XRP/USDT")) == []
    assert aggregator.ingest_trade(Trade(ts=minute_start + 20_500, price=1.20, size=2.0, symbol="XRP/USDT")) == []
    assert aggregator.ingest_trade(Trade(ts=minute_start + 40_900, price=0.90, size=3.0, symbol="XRP/USDT")) == []

    emitted = aggregator.ingest_trade(Trade(ts=minute_start + 60_100, price=1.05, size=4.0, symbol="XRP/USDT"))
    assert len(emitted) == 1

    candle = emitted[0]
    assert candle.symbol == "XRP/USDT"
    assert candle.timeframe == "1m"
    assert candle.open == 1.00
    assert candle.high == 1.20
    assert candle.low == 0.90
    assert candle.close == 0.90
    assert candle.volume == 15.0


def test_trade_aggregator_close_timestamp_semantics():
    aggregator = TradeToCandleAggregator()
    first_trade_ts = 1_700_000_000_250

    aggregator.ingest_trade(Trade(ts=first_trade_ts, price=1.0, size=1.0, symbol="HBAR/USDT"))
    emitted = aggregator.ingest_trade(Trade(ts=1_700_000_060_000, price=1.1, size=1.0, symbol="HBAR/USDT"))

    assert len(emitted) == 1
    expected_close = (first_trade_ts // 60_000) * 60_000 + 60_000
    assert emitted[0].ts_close == expected_close


def test_trade_aggregator_no_synthetic_candles_for_empty_minutes():
    aggregator = TradeToCandleAggregator()
    minute_start = (1_700_000_000_000 // 60_000) * 60_000
    aggregator.ingest_trade(Trade(ts=minute_start, price=1.0, size=1.0, symbol="XRP/USDT"))

    emitted = aggregator.ingest_trade(Trade(ts=minute_start + 300_000, price=1.5, size=2.0, symbol="XRP/USDT"))
    assert len(emitted) == 1
    assert emitted[0].ts_close == minute_start + 60_000