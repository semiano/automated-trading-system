from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("symbol", "venue", "timeframe", "ts", name="uq_candle_key"),
        Index("idx_candle_symbol_timeframe_ts", "symbol", "timeframe", "ts"),
    )


class IndicatorSeries(Base):
    __tablename__ = "indicator_series"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    indicator_key: Mapped[str] = mapped_column(String(64), index=True)
    v1: Mapped[float | None] = mapped_column(Float, nullable=True)
    v2: Mapped[float | None] = mapped_column(Float, nullable=True)
    v3: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "venue",
            "timeframe",
            "ts",
            "indicator_key",
            name="uq_indicator_series_key",
        ),
    )


class UnresolvedGap(Base):
    __tablename__ = "unresolved_gaps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    noted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )
