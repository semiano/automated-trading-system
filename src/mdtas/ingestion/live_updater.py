from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from mdtas.config import AppConfig
from mdtas.db.repo import CandleRepository
from mdtas.indicators.engine import compute as compute_indicators
from mdtas.providers.base import MarketDataProvider
from mdtas.trading.runtime import TradingRuntime
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
    tf_delta = timeframe_to_timedelta(timeframe)
    last_cached_ts = repo.get_latest_candle_ts(symbol=symbol, timeframe=timeframe, venue=venue)
    if last_cached_ts is None:
        cursor = end - tf_delta * 4
    else:
        cursor = last_cached_ts + tf_delta

    if cursor <= end and cfg.ingestion.allow_gap_jump_to_recent:
        bars_behind = int(((end - cursor) / tf_delta)) + 1
        max_catchup = max(10, cfg.ingestion.max_catchup_bars_per_cycle)
        if bars_behind > max_catchup:
            jump_start = end - tf_delta * (max_catchup - 1)
            logger.warning(
                "Gap jump for %s %s: behind=%s bars, jumping cursor from %s to %s",
                symbol,
                timeframe,
                bars_behind,
                cursor.isoformat(),
                jump_start.isoformat(),
            )
            cursor = jump_start

    inserted = 0
    page_limit = 1000
    while cursor <= end:
        page_end = min(end, cursor + (tf_delta * (page_limit - 1)))
        candles = provider.fetch_ohlcv(symbol, timeframe, cursor, page_end, limit=page_limit)
        inserted += repo.upsert_candles(candles)
        cursor = page_end + tf_delta

    warmup_bars = max(50, cfg.ingestion.warmup_bars)
    warmup_bars_cap = max(50, cfg.ingestion.warmup_bars_per_cycle_cap)
    effective_warmup_bars = min(warmup_bars, warmup_bars_cap)
    if effective_warmup_bars < warmup_bars:
        logger.info(
            "Warmup bars capped for %s %s: requested=%s capped=%s",
            symbol,
            timeframe,
            warmup_bars,
            effective_warmup_bars,
        )

    warmup_start = end - timeframe_to_timedelta(timeframe) * effective_warmup_bars
    df = repo.get_candles(symbol, timeframe, venue, warmup_start, end, limit=effective_warmup_bars + 10)
    compute_indicators(df, ["bbands", "rsi", "atr", "ema", "volume_sma", "vwap"], cfg.indicators.model_dump())
    return inserted


def run_live_loop(
    repo: CandleRepository,
    provider: MarketDataProvider,
    cfg: AppConfig,
    symbols: list[str],
    timeframes: list[str],
    venue: str,
    trading_runtime: TradingRuntime | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> None:
    if should_continue is None:
        should_continue = lambda: True

    symbol_cooldown_until: dict[str, datetime] = {}

    while should_continue():
        now = datetime.utcnow().replace(microsecond=0)
        for symbol in symbols:
            if trading_runtime is not None and not trading_runtime.is_symbol_enabled(symbol):
                trading_runtime.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
                    state="paused",
                    note="Asset is paused",
                    log_event=False,
                )
                logger.debug("Skipping %s because asset is paused", symbol)
                continue

            cooldown_until = symbol_cooldown_until.get(symbol)
            if cooldown_until is not None and now < cooldown_until:
                logger.warning("Skipping %s due to cooldown until %s", symbol, cooldown_until.isoformat())
                continue

            symbol_errors = 0
            runtime_tf_ok = False
            for timeframe in timeframes:
                try:
                    inserted = run_live_once(repo, provider, cfg, symbol, timeframe, venue)
                    logger.info("Live update %s %s inserted=%s", symbol, timeframe, inserted)
                    if timeframe == cfg.trading.runtime_timeframe:
                        runtime_tf_ok = True
                except Exception as exc:  # noqa: BLE001
                    symbol_errors += 1
                    logger.exception("Live update failed for %s %s: %s", symbol, timeframe, exc)

            if symbol_errors >= len(timeframes):
                cooldown_seconds = max(cfg.ingestion.poll_delay_seconds * 4, 15)
                symbol_cooldown_until[symbol] = datetime.utcnow().replace(microsecond=0) + timedelta(seconds=cooldown_seconds)
                logger.warning(
                    "Applying cooldown for %s after %s/%s timeframe failures",
                    symbol,
                    symbol_errors,
                    len(timeframes),
                )

            if trading_runtime is not None:
                if cfg.trading.runtime_timeframe in timeframes and not runtime_tf_ok:
                    trading_runtime.trading_repo.set_asset_state(
                        symbol=symbol,
                        default_soft_risk_limit_usd=cfg.trading.soft_portfolio_risk_limit_usd,
                        state="runtime_tf_missing",
                        note=f"No successful update for {cfg.trading.runtime_timeframe}",
                        log_event=True,
                    )
                    logger.warning(
                        "Skipping trading eval for %s because runtime timeframe %s did not update this cycle",
                        symbol,
                        cfg.trading.runtime_timeframe,
                    )
                    continue
                try:
                    trading_runtime.evaluate_symbol(symbol=symbol, venue=venue)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Trading runtime failed for %s: %s", symbol, exc)
        if not should_continue():
            break

        sleep_seconds = max(1, cfg.ingestion.poll_delay_seconds)
        sleep_step = 0.2
        slept = 0.0
        while slept < sleep_seconds and should_continue():
            time.sleep(min(sleep_step, sleep_seconds - slept))
            slept += sleep_step
