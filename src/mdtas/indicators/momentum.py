from __future__ import annotations

import numpy as np
import pandas as pd


def _pivot_flags(close: pd.Series, left_bars: int, right_bars: int) -> tuple[pd.Series, pd.Series]:
    values = close.astype(float).to_numpy()
    n = len(values)
    lows = np.zeros(n, dtype=bool)
    highs = np.zeros(n, dtype=bool)

    start = max(int(left_bars), 0)
    end = max(n - max(int(right_bars), 0), 0)
    for i in range(start, end):
        center = values[i]
        if not np.isfinite(center):
            continue

        left_window = values[i - left_bars : i] if left_bars > 0 else np.array([], dtype=float)
        right_window = values[i + 1 : i + 1 + right_bars] if right_bars > 0 else np.array([], dtype=float)
        if left_window.size and not np.all(np.isfinite(left_window)):
            continue
        if right_window.size and not np.all(np.isfinite(right_window)):
            continue

        left_min = float(left_window.min()) if left_window.size else center
        right_min = float(right_window.min()) if right_window.size else center
        left_max = float(left_window.max()) if left_window.size else center
        right_max = float(right_window.max()) if right_window.size else center

        # Use strictness on the right side to avoid duplicate pivots on flat ranges.
        lows[i] = center <= left_min and center < right_min
        highs[i] = center >= left_max and center > right_max

    index = close.index
    return pd.Series(lows, index=index), pd.Series(highs, index=index)


def compute_momentum_swing(
    df: pd.DataFrame,
    *,
    pivot_left_bars: int = 2,
    pivot_right_bars: int = 2,
    lookback_bars: int = 8,
    roc_length: int = 5,
    min_roc: float = 0.002,
) -> pd.DataFrame:
    close = df["close"].astype(float)
    roc = close.pct_change(periods=max(int(roc_length), 1))

    pivot_low, pivot_high = _pivot_flags(
        close,
        left_bars=max(int(pivot_left_bars), 0),
        right_bars=max(int(pivot_right_bars), 0),
    )

    idx = pd.Series(np.arange(len(close), dtype=float), index=close.index)
    last_pivot_low = idx.where(pivot_low).ffill()
    last_pivot_high = idx.where(pivot_high).ffill()

    bars_since_low = idx - last_pivot_low
    bars_since_high = idx - last_pivot_high

    lookback = max(int(lookback_bars), 0)
    recent_low = bars_since_low.notna() & (bars_since_low >= 0) & (bars_since_low <= lookback)
    recent_high = bars_since_high.notna() & (bars_since_high >= 0) & (bars_since_high <= lookback)

    momentum_up = roc >= float(min_roc)
    momentum_down = roc <= -float(min_roc)

    swing_long_ready = recent_low & momentum_up
    swing_short_ready = recent_high & momentum_down

    return pd.DataFrame(
        {
            "mom_roc": roc,
            "swing_pivot_low": pivot_low,
            "swing_pivot_high": pivot_high,
            "swing_long_ready": swing_long_ready,
            "swing_short_ready": swing_short_ready,
        }
    )
