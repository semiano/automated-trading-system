from __future__ import annotations

from datetime import datetime, timedelta, timezone

_TIMEFRAME_TO_DELTA = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    if timeframe not in _TIMEFRAME_TO_DELTA:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return _TIMEFRAME_TO_DELTA[timeframe]


def align_to_candle_close(ts: datetime, timeframe: str) -> datetime:
    delta = timeframe_to_timedelta(timeframe)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_utc = ts.astimezone(timezone.utc)
    epoch_seconds = int(ts_utc.timestamp())
    step_seconds = int(delta.total_seconds())
    close_seconds = ((epoch_seconds // step_seconds) + 1) * step_seconds
    return datetime.fromtimestamp(close_seconds, tz=timezone.utc).replace(tzinfo=None)


def inclusive_range(start: datetime, end: datetime, timeframe: str) -> list[datetime]:
    delta = timeframe_to_timedelta(timeframe)
    out: list[datetime] = []
    cursor = start
    while cursor <= end:
        out.append(cursor)
        cursor = cursor + delta
    return out
