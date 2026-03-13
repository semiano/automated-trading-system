from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from mdtas.config import get_db_url
from mdtas.db.models import Base


engine = create_engine(get_db_url(), future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            def _ensure_column(table: str, column: str, ddl: str) -> None:
                rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                existing = {r[1] for r in rows}
                if column not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

            _ensure_column("positions", "execution_mode", "TEXT DEFAULT 'sim'")
            _ensure_column("positions", "trade_side", "TEXT DEFAULT 'long'")
            _ensure_column("positions", "entry_spot_price", "FLOAT")
            _ensure_column("trades", "execution_mode", "TEXT DEFAULT 'sim'")
            _ensure_column("trades", "trade_side", "TEXT DEFAULT 'long'")
            _ensure_column("trades", "entry_spot_price", "FLOAT")
            _ensure_column("trades", "exit_spot_price", "FLOAT")
            _ensure_column("trades", "hold_bars_at_exit", "INTEGER")
            _ensure_column("asset_controls", "trade_side", "TEXT DEFAULT 'long_only'")
            _ensure_column("asset_controls", "last_evaluated_state", "TEXT")
            _ensure_column("asset_controls", "last_evaluated_note", "TEXT")
            _ensure_column("asset_controls", "timeframe", "TEXT DEFAULT '5m'")
            _ensure_column("asset_engine_logs", "timeframe", "TEXT DEFAULT '5m'")

            conn.exec_driver_sql("UPDATE asset_controls SET timeframe='5m' WHERE timeframe IS NULL OR timeframe='' ")
            conn.exec_driver_sql("UPDATE asset_engine_logs SET timeframe='5m' WHERE timeframe IS NULL OR timeframe='' ")

            index_rows = conn.exec_driver_sql("PRAGMA index_list(asset_controls)").fetchall()
            has_symbol_only_unique = False
            for idx in index_rows:
                idx_name = idx[1]
                is_unique = int(idx[2]) == 1
                if not is_unique:
                    continue
                info_rows = conn.exec_driver_sql(f"PRAGMA index_info({idx_name})").fetchall()
                cols = [r[2] for r in info_rows]
                if cols == ["symbol"]:
                    has_symbol_only_unique = True
                    break

            if has_symbol_only_unique:
                conn.exec_driver_sql("ALTER TABLE asset_controls RENAME TO asset_controls_legacy")
                conn.exec_driver_sql(
                    """
                    CREATE TABLE asset_controls (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        symbol VARCHAR(64) NOT NULL,
                        timeframe VARCHAR(16) NOT NULL DEFAULT '5m',
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        execution_mode VARCHAR(16) NOT NULL DEFAULT 'sim',
                        trade_side VARCHAR(16) NOT NULL DEFAULT 'long_only',
                        soft_risk_limit_usd FLOAT NOT NULL DEFAULT 150.0,
                        last_run_ts DATETIME,
                        next_run_ts DATETIME,
                        last_evaluated_state VARCHAR(64),
                        last_evaluated_note VARCHAR(256),
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
                conn.exec_driver_sql(
                    """
                    INSERT INTO asset_controls (
                        id, symbol, timeframe, enabled, execution_mode, trade_side,
                        soft_risk_limit_usd, last_run_ts, next_run_ts,
                        last_evaluated_state, last_evaluated_note, updated_at
                    )
                    SELECT
                        id, symbol, COALESCE(NULLIF(timeframe, ''), '5m'), enabled, execution_mode, trade_side,
                        soft_risk_limit_usd, last_run_ts, next_run_ts,
                        last_evaluated_state, last_evaluated_note, updated_at
                    FROM asset_controls_legacy
                    """
                )
                conn.exec_driver_sql("DROP TABLE asset_controls_legacy")

            conn.exec_driver_sql("DROP INDEX IF EXISTS ix_asset_controls_symbol")

            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_control_symbol_timeframe ON asset_controls (symbol, timeframe)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_asset_control_symbol_timeframe ON asset_controls (symbol, timeframe)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_asset_engine_logs_symbol_tf_ts ON asset_engine_logs (symbol, timeframe, created_at)"
            )
        return

    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE asset_controls ADD COLUMN IF NOT EXISTS timeframe VARCHAR(16) DEFAULT '5m'")
        conn.exec_driver_sql("ALTER TABLE asset_engine_logs ADD COLUMN IF NOT EXISTS timeframe VARCHAR(16) DEFAULT '5m'")
        conn.exec_driver_sql("ALTER TABLE positions ADD COLUMN IF NOT EXISTS entry_spot_price DOUBLE PRECISION")
        conn.exec_driver_sql("ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_spot_price DOUBLE PRECISION")
        conn.exec_driver_sql("ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_spot_price DOUBLE PRECISION")
        conn.exec_driver_sql("ALTER TABLE trades ADD COLUMN IF NOT EXISTS hold_bars_at_exit INTEGER")
        conn.exec_driver_sql("UPDATE asset_controls SET timeframe='5m' WHERE timeframe IS NULL OR timeframe='' ")
        conn.exec_driver_sql("UPDATE asset_engine_logs SET timeframe='5m' WHERE timeframe IS NULL OR timeframe='' ")
        conn.exec_driver_sql("ALTER TABLE asset_controls DROP CONSTRAINT IF EXISTS asset_controls_symbol_key")
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_asset_controls_symbol")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_control_symbol_timeframe ON asset_controls (symbol, timeframe)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_asset_control_symbol_timeframe ON asset_controls (symbol, timeframe)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_asset_engine_logs_symbol_tf_ts ON asset_engine_logs (symbol, timeframe, created_at)"
        )


def get_session() -> Session:
    return SessionLocal()
