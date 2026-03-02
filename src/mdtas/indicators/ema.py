from __future__ import annotations

import pandas as pd


def compute_ema(df: pd.DataFrame, length: int) -> pd.Series:
    return df["close"].astype(float).ewm(span=length, adjust=False, min_periods=length).mean()
