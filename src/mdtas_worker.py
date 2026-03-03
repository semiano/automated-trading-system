from __future__ import annotations

import logging

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session, init_db
from mdtas.db.trading_repo import TradingRepository
from mdtas.ingestion.live_updater import run_live_loop
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging
from mdtas.trading.runtime import TradingRuntime


logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    cfg = get_config()
    init_db()
    session = get_session()
    try:
        repo = CandleRepository(session)
        trading_repo = TradingRepository(session)
        trading_runtime = TradingRuntime(cfg=cfg, candle_repo=repo, trading_repo=trading_repo)
        provider = build_provider(cfg)
        venue = cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock"
        symbols = cfg.symbols
        if cfg.providers.default_provider == "ccxt":
            supported: list[str] = []
            unsupported: list[str] = []
            for symbol in cfg.symbols:
                if provider.supports_symbol(symbol):
                    supported.append(symbol)
                else:
                    unsupported.append(symbol)

            if unsupported:
                logger.warning(
                    "Skipping unsupported %s symbols on %s: %s",
                    len(unsupported),
                    venue,
                    ", ".join(unsupported),
                )

            symbols = supported

        run_live_loop(repo, provider, cfg, symbols, cfg.timeframes, venue, trading_runtime)
    finally:
        session.close()


if __name__ == "__main__":
    main()
