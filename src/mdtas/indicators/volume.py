from __future__ import annotations

import pandas as pd


def compute_volume_sma(df: pd.DataFrame, length: int = 20) -> pd.Series:
    return df["volume"].astype(float).rolling(window=length, min_periods=length).mean()
