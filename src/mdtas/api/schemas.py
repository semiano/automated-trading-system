from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CandleOut(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class GapOut(BaseModel):
    start_ts: datetime
    end_ts: datetime


class BackfillRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    venue: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    lookback_days: int | None = None


class BackfillResult(BaseModel):
    symbol: str
    timeframe: str
    venue: str
    inserted: int
    remaining_gaps: int
