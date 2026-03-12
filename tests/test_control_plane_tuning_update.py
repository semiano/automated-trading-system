from __future__ import annotations

from uuid import uuid4

from mdtas.db.session import get_session, init_db
from mdtas.db.trading_repo import TradingRepository


def test_db_native_tuning_versions_mark_latest_active():
    init_db()
    session = get_session()
    repo = TradingRepository(session)
    symbol = f"TUNE/TEST-{uuid4().hex[:8]}"
    timeframe = "5m"

    v1 = repo.create_asset_tuning_version(
        symbol=symbol,
        timeframe=timeframe,
        params_json={"ema_fast": 20, "ema_slow": 50, "atr_length": 14},
        note="seed",
        source="manual",
        updated_by="test",
    )
    v2 = repo.create_asset_tuning_version(
        symbol=symbol,
        timeframe=timeframe,
        params_json={"ema_fast": 12, "ema_slow": 55, "atr_length": 10},
        note="optimized",
        source="backtest",
        updated_by="test",
    )

    latest = repo.latest_asset_tuning_version(symbol=symbol, timeframe=timeframe)
    history = repo.list_asset_tuning_versions(symbol=symbol, timeframe=timeframe, limit=10)

    assert latest is not None
    assert latest.id == v2.id
    assert latest.version == 2
    assert latest.note == "optimized"
    assert latest.params_json["ema_fast"] == 12
    assert len(history) >= 2
    assert history[0].id == v2.id
    assert history[1].id == v1.id
    assert history[0].is_active is True
    assert history[1].is_active is False

    session.close()
