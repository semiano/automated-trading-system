from __future__ import annotations

import numpy as np
import pandas as pd


def compute_rolling_vwap(df: pd.DataFrame, window: int = 20) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical_price * df["volume"]
    rolling_pv = pv.rolling(window=window, min_periods=window).sum()
    rolling_volume = df["volume"].rolling(window=window, min_periods=window).sum()
    return rolling_pv / rolling_volume.replace(0, np.nan)
