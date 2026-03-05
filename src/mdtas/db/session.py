from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from mdtas.config import get_db_url
from mdtas.db.models import Base


engine = create_engine(get_db_url(), future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        def _ensure_column(table: str, column: str, ddl: str) -> None:
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {r[1] for r in rows}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

        _ensure_column("positions", "execution_mode", "TEXT DEFAULT 'sim'")
        _ensure_column("positions", "trade_side", "TEXT DEFAULT 'long'")
        _ensure_column("trades", "execution_mode", "TEXT DEFAULT 'sim'")
        _ensure_column("trades", "trade_side", "TEXT DEFAULT 'long'")
        _ensure_column("asset_controls", "trade_side", "TEXT DEFAULT 'long_only'")
        _ensure_column("asset_controls", "last_evaluated_state", "TEXT")
        _ensure_column("asset_controls", "last_evaluated_note", "TEXT")


def get_session() -> Session:
    return SessionLocal()
