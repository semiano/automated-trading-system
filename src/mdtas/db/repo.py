from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from mdtas.db.models import Candle, UnresolvedGap


@dataclass(slots=True)
class CandleDTO:
    symbol: str
    venue: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    ingested_at: datetime


@dataclass(slots=True)
class GapDTO:
    start_ts: datetime
    end_ts: datetime


class CandleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_latest_candle_ts(self, symbol: str, timeframe: str, venue: str) -> datetime | None:
        return self.session.scalar(
            select(func.max(Candle.ts)).where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.venue == venue,
            )
        )

    def upsert_candles(self, candles: list[CandleDTO]) -> int:
        if not candles:
            return 0
        inserted = 0
        for candle in candles:
            existing = self.session.scalar(
                select(Candle).where(
                    Candle.symbol == candle.symbol,
                    Candle.venue == candle.venue,
                    Candle.timeframe == candle.timeframe,
                    Candle.ts == candle.ts,
                )
            )
            if existing:
                existing.open = candle.open
                existing.high = candle.high
                existing.low = candle.low
                existing.close = candle.close
                existing.volume = candle.volume
                existing.ingested_at = candle.ingested_at
            else:
                self.session.add(
                    Candle(
                        symbol=candle.symbol,
                        venue=candle.venue,
                        timeframe=candle.timeframe,
                        ts=candle.ts,
                        open=candle.open,
                        high=candle.high,
                        low=candle.low,
                        close=candle.close,
                        volume=candle.volume,
                        ingested_at=candle.ingested_at,
                    )
                )
                inserted += 1

        self.session.commit()
        return inserted

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        venue: str,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        latest: bool = False,
    ) -> pd.DataFrame:
        clauses = [
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
            Candle.venue == venue,
        ]
        if start:
            clauses.append(Candle.ts >= start)
        if end:
            clauses.append(Candle.ts <= end)

        order = Candle.ts.desc() if latest else Candle.ts.asc()
        stmt = select(Candle).where(and_(*clauses)).order_by(order).limit(limit)

        rows = self.session.scalars(stmt).all()
        if not rows:
            return pd.DataFrame(
                columns=["ts", "open", "high", "low", "close", "volume", "symbol", "venue", "timeframe"]
            )

        if latest:
            rows.reverse()

        data = [
            {
                "ts": row.ts,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "symbol": row.symbol,
                "venue": row.venue,
                "timeframe": row.timeframe,
            }
            for row in rows
        ]
        return pd.DataFrame(data)

    def get_symbols(self) -> list[str]:
        rows = self.session.execute(select(Candle.symbol).distinct().order_by(Candle.symbol.asc()))
        return [r[0] for r in rows]

    def record_unresolved_gaps(
        self,
        symbol: str,
        timeframe: str,
        venue: str,
        gaps: list[GapDTO],
    ) -> None:
        self.session.execute(
            delete(UnresolvedGap).where(
                UnresolvedGap.symbol == symbol,
                UnresolvedGap.timeframe == timeframe,
                UnresolvedGap.venue == venue,
            )
        )
        for gap in gaps:
            self.session.add(
                UnresolvedGap(
                    symbol=symbol,
                    timeframe=timeframe,
                    venue=venue,
                    start_ts=gap.start_ts,
                    end_ts=gap.end_ts,
                )
            )
        self.session.commit()

    def get_unresolved_gaps(
        self,
        symbol: str,
        timeframe: str,
        venue: str,
        start: datetime | None,
        end: datetime | None,
    ) -> list[GapDTO]:
        clauses = [
            UnresolvedGap.symbol == symbol,
            UnresolvedGap.timeframe == timeframe,
            UnresolvedGap.venue == venue,
        ]
        if start:
            clauses.append(UnresolvedGap.end_ts >= start)
        if end:
            clauses.append(UnresolvedGap.start_ts <= end)

        rows = self.session.scalars(
            select(UnresolvedGap).where(and_(*clauses)).order_by(UnresolvedGap.start_ts.asc())
        ).all()
        return [GapDTO(start_ts=row.start_ts, end_ts=row.end_ts) for row in rows]
