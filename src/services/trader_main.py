from __future__ import annotations

import threading
import time

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.db.trading_repo import TradingRepository
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging
from mdtas.trading.runtime import TradingRuntime
from services.common import emit_service_event, install_shutdown_handlers, runtime_symbols, safe_config_summary


def main() -> None:
    setup_logging()
    cfg = get_config()
    emit_service_event(service="trader", event="starting", **safe_config_summary(cfg))

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event, service="trader")

    session = get_session()
    try:
        candle_repo = CandleRepository(session)
        trading_repo = TradingRepository(session)
        runtime = TradingRuntime(cfg=cfg, candle_repo=candle_repo, trading_repo=trading_repo)
        provider = build_provider(cfg)
        venue, symbols = runtime_symbols(cfg, provider)
        emit_service_event(service="trader", event="started", venue=venue, symbols=symbols)

        while not stop_event.is_set():
            for symbol in symbols:
                try:
                    runtime.evaluate_symbol(symbol=symbol, venue=venue)
                except Exception as exc:  # noqa: BLE001
                    emit_service_event(service="trader", event="cycle_error", symbol=symbol, error=str(exc))
            if stop_event.is_set():
                break

            sleep_seconds = max(1, cfg.ingestion.poll_delay_seconds)
            sleep_step = 0.2
            slept = 0.0
            while slept < sleep_seconds and not stop_event.is_set():
                time.sleep(min(sleep_step, sleep_seconds - slept))
                slept += sleep_step
    finally:
        session.close()
        emit_service_event(service="trader", event="stopped")


if __name__ == "__main__":
    main()
