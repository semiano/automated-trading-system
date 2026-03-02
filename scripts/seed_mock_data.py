from __future__ import annotations

from datetime import datetime, timedelta

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session, init_db
from mdtas.ingestion.backfill import run_backfill
from mdtas.providers.mock_provider import MockProvider


def main() -> None:
    cfg = get_config()
    init_db()
    session = get_session()
    repo = CandleRepository(session)
    provider = MockProvider()

    end = datetime.utcnow().replace(microsecond=0)
    start = end - timedelta(days=7)

    for symbol in cfg.symbols:
        for timeframe in cfg.timeframes:
            run_backfill(
                repo=repo,
                provider=provider,
                cfg=cfg,
                symbol=symbol,
                timeframe=timeframe,
                venue="mock",
                start=start,
                end=end,
            )
    session.close()


if __name__ == "__main__":
    main()
