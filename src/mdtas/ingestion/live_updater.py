from __future__ import annotations

import logging
import time
from datetime import datetime

from mdtas.config import AppConfig
from mdtas.db.repo import CandleRepository
from mdtas.indicators.engine import compute as compute_indicators
from mdtas.providers.base import MarketDataProvider
from mdtas.utils.timeframes import align_to_candle_close, timeframe_to_timedelta

logger = logging.getLogger(__name__)


def run_live_once(
    repo: CandleRepository,
    provider: MarketDataProvider,
    cfg: AppConfig,
    symbol: str,
    timeframe: str,
    venue: str,
) -> int:
    now = datetime.utcnow().replace(microsecond=0)
    close_boundary = align_to_candle_close(now, timeframe)
    end = close_boundary - timeframe_to_timedelta(timeframe)
    start = end - timeframe_to_timedelta(timeframe) * 4

    candles = provider.fetch_ohlcv(symbol, timeframe, start, end, limit=5)
    inserted = repo.upsert_candles(candles)

    warmup_start = end - timeframe_to_timedelta(timeframe) * cfg.ingestion.warmup_bars
    df = repo.get_candles(symbol, timeframe, venue, warmup_start, end, limit=cfg.ingestion.warmup_bars + 10)
    compute_indicators(df, ["bbands", "rsi", "atr", "ema", "volume_sma", "vwap"], cfg.indicators.model_dump())
    return inserted


def run_live_loop(
    repo: CandleRepository,
    provider: MarketDataProvider,
    cfg: AppConfig,
    symbols: list[str],
    timeframes: list[str],
    venue: str,
) -> None:
    while True:
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    inserted = run_live_once(repo, provider, cfg, symbol, timeframe, venue)
                    logger.info("Live update %s %s inserted=%s", symbol, timeframe, inserted)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Live update failed for %s %s: %s", symbol, timeframe, exc)
        time.sleep(max(1, cfg.ingestion.poll_delay_seconds))
