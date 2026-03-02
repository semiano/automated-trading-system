from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from mdtas.config import AppConfig
from mdtas.db.repo import CandleRepository
from mdtas.ingestion.gaps import detect_gaps, gap_ranges_to_windows
from mdtas.providers.base import MarketDataProvider
from mdtas.utils.timeframes import timeframe_to_timedelta

logger = logging.getLogger(__name__)


def _retry_fetch(
    provider: MarketDataProvider,
    symbol: str,
    timeframe: str,
    start_ts: datetime,
    end_ts: datetime,
    limit: int,
    retries: int,
    backoff_seconds: int,
):
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return provider.fetch_ohlcv(symbol, timeframe, start_ts, end_ts, limit)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            sleep_s = backoff_seconds * (2**attempt)
            logger.warning("Fetch failed (%s), retry in %ss", exc, sleep_s)
            time.sleep(sleep_s)
    if last_exc:
        raise last_exc
    return []


def run_backfill(
    repo: CandleRepository,
    provider: MarketDataProvider,
    cfg: AppConfig,
    symbol: str,
    timeframe: str,
    venue: str,
    start: datetime | None = None,
    end: datetime | None = None,
    lookback_days: int | None = None,
) -> dict:
    now = datetime.utcnow().replace(microsecond=0)
    if end is None:
        end = now
    if start is None:
        if lookback_days is not None:
            start = end - timedelta(days=lookback_days)
        else:
            horizon = cfg.cache_horizon_days.get(timeframe, 30)
            start = end - timedelta(days=horizon)

    delta = timeframe_to_timedelta(timeframe)
    page_limit = 1000
    cursor = start
    total_inserted = 0

    while cursor <= end:
        page_end = min(end, cursor + (delta * (page_limit - 1)))
        candles = _retry_fetch(
            provider=provider,
            symbol=symbol,
            timeframe=timeframe,
            start_ts=cursor,
            end_ts=page_end,
            limit=page_limit,
            retries=cfg.ingestion.retries,
            backoff_seconds=cfg.ingestion.backoff_seconds,
        )
        total_inserted += repo.upsert_candles(candles)
        cursor = page_end + delta

    stored = repo.get_candles(symbol, timeframe, venue, start, end, limit=2_000_000)
    gaps = detect_gaps(stored, timeframe)

    for gap_start, gap_end in gap_ranges_to_windows(gaps):
        repaired = _retry_fetch(
            provider=provider,
            symbol=symbol,
            timeframe=timeframe,
            start_ts=gap_start,
            end_ts=gap_end,
            limit=2000,
            retries=cfg.ingestion.retries,
            backoff_seconds=cfg.ingestion.backoff_seconds,
        )
        repo.upsert_candles(repaired)

    final_df = repo.get_candles(symbol, timeframe, venue, start, end, limit=2_000_000)
    unresolved = detect_gaps(final_df, timeframe)
    repo.record_unresolved_gaps(symbol=symbol, timeframe=timeframe, venue=venue, gaps=unresolved)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "venue": venue,
        "inserted": total_inserted,
        "remaining_gaps": len(unresolved),
    }
