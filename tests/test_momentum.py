import pandas as pd

from mdtas.indicators.momentum import compute_momentum_swing


def test_momentum_swing_long_short_ready_flags():
    closes = [
        10.0,
        9.0,
        8.0,
        9.0,
        10.0,
        11.0,
        12.0,
        11.0,
        10.0,
        9.0,
        8.0,
    ]
    df = pd.DataFrame({"close": closes})

    out = compute_momentum_swing(
        df,
        pivot_left_bars=1,
        pivot_right_bars=1,
        lookback_bars=3,
        roc_length=1,
        min_roc=0.01,
    )

    # After the local bottom at index 2 and rebound, long readiness should appear.
    assert bool(out.iloc[3]["swing_long_ready"]) is True
    # After the local top at index 6 and decline, short readiness should appear.
    assert bool(out.iloc[8]["swing_short_ready"]) is True
