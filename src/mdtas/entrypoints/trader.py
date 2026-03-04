from __future__ import annotations

import logging
import time

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session, init_db
from mdtas.db.trading_repo import TradingRepository
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging
from mdtas.trading.runtime import TradingRuntime


logger = logging.getLogger(__name__)


def _runtime_symbols(cfg, provider) -> tuple[str, list[str]]:
    venue = cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock"
    symbols = cfg.symbols
    if cfg.providers.default_provider != "ccxt":
        return venue, symbols

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
    return venue, supported


def main() -> None:
    setup_logging()
    logger.info("Trader worker started")

    cfg = get_config()
    init_db()
    session = get_session()
    try:
        candle_repo = CandleRepository(session)
        trading_repo = TradingRepository(session)
        runtime = TradingRuntime(cfg=cfg, candle_repo=candle_repo, trading_repo=trading_repo)
        provider = build_provider(cfg)
        venue, symbols = _runtime_symbols(cfg, provider)

        while True:
            for symbol in symbols:
                try:
                    runtime.evaluate_symbol(symbol=symbol, venue=venue)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Trading runtime failed for %s: %s", symbol, exc)
            time.sleep(max(1, cfg.ingestion.poll_delay_seconds))
    finally:
        session.close()


if __name__ == "__main__":
    main()
