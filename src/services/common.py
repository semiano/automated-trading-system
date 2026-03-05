from __future__ import annotations

import json
import logging
import os
import signal
import threading
from collections.abc import Callable

from mdtas.config import AppConfig


logger = logging.getLogger(__name__)


def emit_service_event(*, service: str, event: str, **extra: object) -> None:
    payload: dict[str, object] = {"service": service, "event": event}
    payload.update(extra)
    logger.info("service_event %s", json.dumps(payload, separators=(",", ":"), sort_keys=True))


def safe_config_summary(cfg: AppConfig) -> dict[str, object]:
    return {
        "provider": cfg.providers.default_provider,
        "ccxt_venue": cfg.providers.ccxt.venue,
        "symbols_count": len(cfg.symbols),
        "timeframes": cfg.timeframes,
        "runtime_timeframe": cfg.trading.runtime_timeframe,
        "trading_enabled": cfg.trading.enabled,
        "execution_adapter": cfg.trading.execution_adapter,
        "live_trading_enabled": cfg.trading.live_trading_enabled,
        "config_path": os.getenv("MDTAS_CONFIG_PATH", "config.yaml"),
        "database_url_configured": bool(os.getenv("DATABASE_URL")),
    }


def install_shutdown_handlers(stop_event: threading.Event, *, service: str) -> None:
    def _handle(signum, _frame) -> None:  # type: ignore[no-untyped-def]
        emit_service_event(service=service, event="shutdown_requested", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def runtime_symbols(cfg: AppConfig, provider) -> tuple[str, list[str]]:
    venue = cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock"
    if cfg.providers.default_provider != "ccxt":
        return venue, cfg.symbols

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


def keep_running(stop_event: threading.Event) -> Callable[[], bool]:
    return lambda: not stop_event.is_set()
