from datetime import datetime, timedelta

import pandas as pd

from mdtas.config import AppConfig
from mdtas.trading.regime import compute_htf_regime
from mdtas.trading.runtime import TradingRuntime


class _DummyCandleRepo:
    pass


class _DummyTradingRepo:
    pass



def _build_htf_frame(start: datetime, bars: int, close_fn):
    rows = []
    ts = start
    for i in range(bars):
        close = float(close_fn(i))
        rows.append(
            {
                "ts": ts,
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1.0,
            }
        )
        ts += timedelta(hours=1)
    return pd.DataFrame(rows)



def test_regime_bull_when_ema_fast_above_slow():
    cfg = AppConfig()
    cfg.trading.regime_trend_ema_fast = 50
    cfg.trading.regime_trend_ema_slow = 200

    frame = _build_htf_frame(
        start=datetime(2026, 1, 1, 0, 0, 0),
        bars=260,
        close_fn=lambda i: 100.0 + (i * 0.2),
    )

    regime = compute_htf_regime(frame, cfg)
    assert regime["trend_state"] == "bull"



def test_no_lookahead_alignment_uses_only_htf_le_ltf_ts():
    cfg = AppConfig()
    runtime = TradingRuntime(cfg=cfg, candle_repo=_DummyCandleRepo(), trading_repo=_DummyTradingRepo())

    frame = _build_htf_frame(
        start=datetime(2026, 1, 1, 0, 0, 0),
        bars=250,
        close_fn=lambda i: 300.0 - i if i < 220 else 50.0 + (i * 5.0),
    )

    decision_ts = frame.iloc[219]["ts"]
    aligned = runtime._select_htf_up_to(frame, decision_ts)

    assert len(aligned) == 220
    assert pd.to_datetime(aligned.iloc[-1]["ts"]).to_pydatetime().replace(tzinfo=None) <= decision_ts

    regime_aligned = compute_htf_regime(aligned, cfg)
    regime_full = compute_htf_regime(frame, cfg)

    assert regime_aligned["trend_state"] == "bear"
    assert regime_full["trend_state"] == "bull"
