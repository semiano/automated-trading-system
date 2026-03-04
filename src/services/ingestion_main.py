from __future__ import annotations

import threading

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.ingestion.live_updater import run_live_loop
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging
from services.common import emit_service_event, install_shutdown_handlers, keep_running, runtime_symbols, safe_config_summary


def main() -> None:
    setup_logging()
    cfg = get_config()
    emit_service_event(service="ingestion", event="starting", **safe_config_summary(cfg))

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event, service="ingestion")

    session = get_session()
    try:
        repo = CandleRepository(session)
        provider = build_provider(cfg)
        venue, symbols = runtime_symbols(cfg, provider)
        emit_service_event(service="ingestion", event="started", venue=venue, symbols=symbols)
        run_live_loop(
            repo=repo,
            provider=provider,
            cfg=cfg,
            symbols=symbols,
            timeframes=cfg.timeframes,
            venue=venue,
            trading_runtime=None,
            should_continue=keep_running(stop_event),
        )
    finally:
        session.close()
        emit_service_event(service="ingestion", event="stopped")


if __name__ == "__main__":
    main()
