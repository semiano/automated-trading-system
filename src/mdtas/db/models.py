from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint, func
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


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), index=True, default="sim")
    trade_side: Mapped[str] = mapped_column(String(16), index=True, default="long")
    status: Mapped[str] = mapped_column(String(16), index=True, default="open")
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    entry_fee: Mapped[float] = mapped_column(Float, default=0.0)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    hold_bars: Mapped[int] = mapped_column(Integer, default=0)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), onupdate=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    __table_args__ = (
        Index("idx_position_lookup", "symbol", "venue", "timeframe", "status"),
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), index=True, default="sim")
    trade_side: Mapped[str] = mapped_column(String(16), index=True, default="long")
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    exit_ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    gross_pnl: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float)
    net_pnl: Mapped[float] = mapped_column(Float)
    return_pct: Mapped[float] = mapped_column(Float)
    exit_reason: Mapped[str] = mapped_column(String(32), index=True)
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_trade_lookup", "symbol", "venue", "timeframe", "exit_ts"),
    )


class TradingControl(Base):
    __tablename__ = "trading_controls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    soft_risk_limit_usd: Mapped[float] = mapped_column(Float, default=150.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), onupdate=func.now(), nullable=False
    )


class AssetControl(Base):
    __tablename__ = "asset_controls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    execution_mode: Mapped[str] = mapped_column(String(16), default="sim")
    trade_side: Mapped[str] = mapped_column(String(16), default="long_only")
    soft_risk_limit_usd: Mapped[float] = mapped_column(Float, default=150.0)
    last_run_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    next_run_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_evaluated_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_evaluated_note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), onupdate=func.now(), nullable=False
    )


class AssetEngineLog(Base):
    __tablename__ = "asset_engine_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("idx_asset_engine_logs_symbol_ts", "symbol", "created_at"),
    )
