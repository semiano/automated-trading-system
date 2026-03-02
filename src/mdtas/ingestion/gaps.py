from __future__ import annotations

from datetime import datetime

import pandas as pd

from mdtas.db.repo import GapDTO
from mdtas.utils.timeframes import timeframe_to_timedelta


def detect_gaps(df: pd.DataFrame, timeframe: str) -> list[GapDTO]:
    if df.empty:
        return []
    delta = timeframe_to_timedelta(timeframe)
    series = pd.to_datetime(df["ts"]).sort_values().reset_index(drop=True)
    gaps: list[GapDTO] = []
    for i in range(1, len(series)):
        expected = series.iloc[i - 1] + delta
        current = series.iloc[i]
        if current > expected:
            start_missing = expected.to_pydatetime().replace(tzinfo=None)
            end_missing = (current - delta).to_pydatetime().replace(tzinfo=None)
            gaps.append(GapDTO(start_ts=start_missing, end_ts=end_missing))
    return gaps


def gap_ranges_to_windows(gaps: list[GapDTO]) -> list[tuple[datetime, datetime]]:
    return [(g.start_ts, g.end_ts) for g in gaps]
