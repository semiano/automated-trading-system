from __future__ import annotations

import math
from datetime import datetime

from mdtas.db.repo import CandleDTO
from mdtas.providers.base import MarketDataProvider
from mdtas.utils.timeframes import inclusive_range, timeframe_to_timedelta


class MockProvider(MarketDataProvider):
    def __init__(self, venue: str = "mock") -> None:
        self.venue = venue

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_ts: datetime,
        end_ts: datetime,
        limit: int,
    ) -> list[CandleDTO]:
        points = inclusive_range(start_ts, end_ts, timeframe)
        points = points[:limit]
        seed = sum(ord(ch) for ch in f"{symbol}:{timeframe}")
        step_seconds = timeframe_to_timedelta(timeframe).total_seconds()

        candles: list[CandleDTO] = []
        base = 100.0 + (seed % 300)
        for idx, ts in enumerate(points):
            phase = ((idx + seed) * step_seconds) / 3600.0
            close = base + math.sin(phase / 3.0) * 5 + math.cos(phase / 8.0) * 2 + idx * 0.015
            open_ = close - math.sin(phase) * 0.8
            high = max(open_, close) + 0.6 + abs(math.sin(phase / 4.0))
            low = min(open_, close) - 0.6 - abs(math.cos(phase / 4.0))
            volume = 100 + abs(math.sin(phase / 2.0) * 45) + ((seed + idx) % 23)
            candles.append(
                CandleDTO(
                    symbol=symbol,
                    venue=self.venue,
                    timeframe=timeframe,
                    ts=ts,
                    open=float(open_),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=float(volume),
                    ingested_at=datetime.utcnow(),
                )
            )
        return candles
