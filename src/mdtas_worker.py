from __future__ import annotations

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session, init_db
from mdtas.ingestion.live_updater import run_live_loop
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging


def main() -> None:
    setup_logging()
    cfg = get_config()
    init_db()
    session = get_session()
    try:
        repo = CandleRepository(session)
        provider = build_provider(cfg)
        venue = cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock"
        run_live_loop(repo, provider, cfg, cfg.symbols, cfg.timeframes, venue)
    finally:
        session.close()


if __name__ == "__main__":
    main()
