from __future__ import annotations

import logging
import time

from mdtas.config import get_config, get_config_mtime_ns, load_config, resolve_config_path
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session, init_db
from mdtas.db.trading_repo import TradingRepository
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging
from mdtas.trading.runtime import TradingRuntime


logger = logging.getLogger(__name__)
SYSTEM_TRADER_SYMBOL = "__SYSTEM__/TRADER"


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
    config_path = resolve_config_path()
    config_mtime_ns = get_config_mtime_ns(config_path)
    init_db()
    session = get_session()
    try:
        candle_repo = CandleRepository(session)
        trading_repo = TradingRepository(session)
        runtime = TradingRuntime(cfg=cfg, candle_repo=candle_repo, trading_repo=trading_repo)
        provider = build_provider(cfg)
        venue, symbols = _runtime_symbols(cfg, provider)

        while True:
            latest_mtime_ns = get_config_mtime_ns(config_path)
            if latest_mtime_ns != config_mtime_ns:
                try:
                    cfg = load_config(config_path)
                    runtime.apply_config(cfg)
                    provider = build_provider(cfg)
                    venue, symbols = _runtime_symbols(cfg, provider)
                    config_mtime_ns = latest_mtime_ns
                    logger.info(
                        "Reloaded trader config (venue=%s, symbols=%s, runtime_timeframe=%s, bb_entry_mode=%s)",
                        venue,
                        symbols,
                        cfg.trading.runtime_timeframe,
                        cfg.trading.bb_entry_mode,
                    )
                    trading_repo.log_engine_event(
                        symbol=SYSTEM_TRADER_SYMBOL,
                        state="config_reloaded",
                        note=(
                            f"runtime_timeframe={cfg.trading.runtime_timeframe}, "
                            f"bb_entry_mode={cfg.trading.bb_entry_mode}, symbols={len(symbols)}"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to hot-reload trader config: %s", exc)
                    trading_repo.log_engine_event(
                        symbol=SYSTEM_TRADER_SYMBOL,
                        state="config_reload_failed",
                        note=str(exc),
                    )

            for symbol in symbols:
                try:
                    runtime.evaluate_symbol(symbol=symbol, venue=venue)
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    logger.exception("Trading runtime failed for %s: %s", symbol, exc)
            time.sleep(max(1, cfg.ingestion.poll_delay_seconds))
    finally:
        session.close()


if __name__ == "__main__":
    main()
