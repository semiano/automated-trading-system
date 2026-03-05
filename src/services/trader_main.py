from __future__ import annotations

import threading
import time

from mdtas.config import get_config, get_config_mtime_ns, load_config, resolve_config_path
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.db.trading_repo import TradingRepository
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging
from mdtas.trading.runtime import TradingRuntime
from services.common import emit_service_event, install_shutdown_handlers, runtime_symbols, safe_config_summary


SYSTEM_TRADER_SYMBOL = "__SYSTEM__/TRADER"


def main() -> None:
    setup_logging()
    cfg = get_config()
    config_path = resolve_config_path()
    config_mtime_ns = get_config_mtime_ns(config_path)
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
            latest_mtime_ns = get_config_mtime_ns(config_path)
            if latest_mtime_ns != config_mtime_ns:
                try:
                    cfg = load_config(config_path)
                    runtime.apply_config(cfg)
                    provider = build_provider(cfg)
                    venue, symbols = runtime_symbols(cfg, provider)
                    config_mtime_ns = latest_mtime_ns
                    emit_service_event(
                        service="trader",
                        event="config_reloaded",
                        venue=venue,
                        symbols=symbols,
                        runtime_timeframe=cfg.trading.runtime_timeframe,
                        bb_entry_mode=cfg.trading.bb_entry_mode,
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
                    emit_service_event(service="trader", event="config_reload_failed", error=str(exc))
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
