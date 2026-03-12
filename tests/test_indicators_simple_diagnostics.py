from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from mdtas.api.routes_indicators import _append_simple_engine_diagnostics


def test_append_simple_engine_diagnostics_populates_expected_columns() -> None:
    base = datetime(2026, 1, 1)
    rows = []
    price = 100.0
    for i in range(120):
        price += 0.05
        rows.append(
            {
                "ts": base + timedelta(minutes=i),
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "bb_mid": price,
                "bb_lower": price - 1.0,
                "bb_upper": price + 1.0,
                "ema12": price - 0.05,
                "ema55": price - 0.08,
            }
        )
    frame = pd.DataFrame(rows)

    out = _append_simple_engine_diagnostics(
        frame,
        ema_fast=12,
        ema_slow=55,
        slope_lookback_bars=3,
        slope_flatten_factor=0.9,
        entry_deviation=1.0,
    )

    for field in [
        "bb_deviation",
        "entry_deviation",
        "slope_now",
        "slope_lookback",
        "flatten_ratio",
        "long_rounding",
        "short_rounding",
        "long_entry_signal",
        "short_entry_signal",
    ]:
        assert field in out.columns

    # A mature sample should have computed diagnostics available.
    sample = out.iloc[-1]
    assert sample["bb_deviation"] is not None
    assert sample["slope_now"] is not None
    assert sample["slope_lookback"] is not None
    assert sample["flatten_ratio"] is not None
    assert bool(sample["long_rounding"]) is True
    assert bool(sample["short_rounding"]) is True
