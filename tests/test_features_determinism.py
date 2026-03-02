from datetime import datetime, timedelta

import pandas as pd

from mdtas.indicators.engine import compute


def test_features_determinism():
    base = datetime(2026, 1, 1)
    df = pd.DataFrame(
        {
            "ts": [base + timedelta(minutes=i) for i in range(300)],
            "open": [100 + i * 0.1 for i in range(300)],
            "high": [101 + i * 0.1 for i in range(300)],
            "low": [99 + i * 0.1 for i in range(300)],
            "close": [100 + i * 0.1 for i in range(300)],
            "volume": [1000 + i for i in range(300)],
            "symbol": ["BTC/USDT"] * 300,
            "venue": ["mock"] * 300,
            "timeframe": ["1m"] * 300,
        }
    )
    req = ["bbands", "rsi", "atr", "ema20", "ema50", "ema200", "volume_sma", "vwap"]
    params = {
        "bollinger": {"length": 20, "stdev": 2.0},
        "rsi": {"length": 14},
        "atr": {"length": 14},
        "ema_lengths": [20, 50, 200],
        "volume_sma": 20,
    }
    a = compute(df, req, params)
    b = compute(df, req, params)
    assert a.fillna(-1).equals(b.fillna(-1))
