from __future__ import annotations

from datetime import datetime, timezone

from mdtas.config import AppConfig


def parse_utc_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def ensure_supported_timeframe(timeframe: str, cfg: AppConfig) -> None:
    if timeframe not in cfg.timeframes and timeframe != "1d":
        raise ValueError(f"Unsupported timeframe: {timeframe}")


def ensure_known_symbol(symbol: str, cfg: AppConfig) -> None:
    if symbol not in cfg.symbols:
        raise ValueError(f"Unsupported symbol: {symbol}")
