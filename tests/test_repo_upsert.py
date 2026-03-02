from datetime import datetime

from mdtas.db.repo import CandleDTO, CandleRepository
from mdtas.db.session import get_session, init_db


def test_repo_upsert_dedupe():
    init_db()
    session = get_session()
    repo = CandleRepository(session)

    ts = datetime(2026, 1, 1, 0, 1)
    candle = CandleDTO(
        symbol="TEST/USDT",
        venue="mock",
        timeframe="1m",
        ts=ts,
        open=1,
        high=2,
        low=0.5,
        close=1.5,
        volume=10,
        ingested_at=datetime.utcnow(),
    )
    repo.upsert_candles([candle])
    repo.upsert_candles([candle])

    df = repo.get_candles("TEST/USDT", "1m", "mock", None, None, 100)
    assert len(df) == 1
    session.close()
