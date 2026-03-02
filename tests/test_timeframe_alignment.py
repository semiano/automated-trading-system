from datetime import datetime

from mdtas.utils.timeframes import align_to_candle_close


def test_timeframe_alignment_5m():
    ts = datetime(2026, 1, 1, 0, 2, 14)
    aligned = align_to_candle_close(ts, "5m")
    assert aligned == datetime(2026, 1, 1, 0, 5, 0)
