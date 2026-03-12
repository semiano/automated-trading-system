from __future__ import annotations

import threading
import time
from pathlib import Path

from mdtas.config import get_config, get_config_mtime_ns, load_config, resolve_config_path
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.db.trading_repo import TradingRepository
from mdtas.ingestion.scheduler import build_provider
from mdtas.logging import setup_logging
from mdtas.trading.runtime_5m_simple import Simple5mRuntime
from services.common import emit_service_event, install_shutdown_handlers, runtime_symbols


def _prepare_1h_cfg(cfg):
    cfg.symbols = [s for s in cfg.symbols if s.upper().startswith("XRP/")] or ["XRP/USD"]
    cfg.trading_5m.runtime_timeframe = "1h"
    tuned_1h = Path("artifacts/xrp_engine_v3_1h_for_runtime.yaml")
    if tuned_1h.exists():
        cfg.trading_5m.tuned_params_path = str(tuned_1h)
    return cfg


def main() -> None:
    setup_logging()
    cfg = _prepare_1h_cfg(get_config())
    config_path = resolve_config_path()
    config_mtime_ns = get_config_mtime_ns(config_path)
    emit_service_event(service="trader_1h", event="starting", runtime_timeframe=cfg.trading.runtime_timeframe)

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event, service="trader_1h")

    session = get_session()
    try:
        candle_repo = CandleRepository(session)
        trading_repo = TradingRepository(session)
        runtime = Simple5mRuntime(cfg=cfg, candle_repo=candle_repo, trading_repo=trading_repo)
        provider = build_provider(cfg)
        venue, symbols = runtime_symbols(cfg, provider)
        emit_service_event(service="trader_1h", event="started", venue=venue, symbols=symbols)

        while not stop_event.is_set():
            latest_mtime_ns = get_config_mtime_ns(config_path)
            if latest_mtime_ns != config_mtime_ns:
                try:
                    cfg = _prepare_1h_cfg(load_config(config_path))
                    runtime.apply_config(cfg)
                    provider = build_provider(cfg)
                    venue, symbols = runtime_symbols(cfg, provider)
                    config_mtime_ns = latest_mtime_ns
                    emit_service_event(
                        service="trader_1h",
                        event="config_reloaded",
                        venue=venue,
                        symbols=symbols,
                        runtime_timeframe=cfg.trading_5m.runtime_timeframe,
                    )
                except Exception as exc:  # noqa: BLE001
                    emit_service_event(service="trader_1h", event="config_reload_failed", error=str(exc))

            for symbol in symbols:
                try:
                    runtime.evaluate_symbol(symbol=symbol, venue=venue)
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    emit_service_event(service="trader_1h", event="cycle_error", symbol=symbol, error=str(exc))

            sleep_seconds = max(1, cfg.ingestion.poll_delay_seconds)
            slept = 0.0
            while slept < sleep_seconds and not stop_event.is_set():
                time.sleep(min(0.2, sleep_seconds - slept))
                slept += 0.2
    finally:
        session.close()
        emit_service_event(service="trader_1h", event="stopped")


if __name__ == "__main__":
    main()
