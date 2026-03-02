from __future__ import annotations

import numpy as np
import pandas as pd


def compute_bollinger(df: pd.DataFrame, length: int = 20, stdev: float = 2.0) -> pd.DataFrame:
    close = df["close"].astype(float)
    mid = close.rolling(window=length, min_periods=length).mean()
    sigma = close.rolling(window=length, min_periods=length).std(ddof=0)
    upper = mid + (sigma * stdev)
    lower = mid - (sigma * stdev)
    width = (upper - lower) / mid.replace(0, np.nan)
    percent_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {
            "bb_lower": lower,
            "bb_mid": mid,
            "bb_upper": upper,
            "bb_width": width,
            "bb_percent_b": percent_b,
        }
    )
