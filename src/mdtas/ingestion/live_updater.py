from __future__ import annotations

import logging
import time
from collections.abc import Callable
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import pandas as pd
from mdtas.config import AppConfig
from mdtas.db.repo import CandleDTO, CandleRepository
from mdtas.ingestion.gaps import detect_gaps
from mdtas.ingestion.rollup import rollup_candles
from mdtas.ingestion.trade_aggregator import Candle as AggCandle
from mdtas.ingestion.trade_aggregator import Trade, TradeToCandleAggregator
from mdtas.indicators.engine import compute as compute_indicators
from mdtas.providers.base import MarketDataProvider
from mdtas.providers.coinbase_ws_provider import CoinbaseWsTradeStream
from mdtas.trading.runtime import TradingRuntime
from mdtas.utils.timeframes import align_to_candle_close, timeframe_to_timedelta

logger = logging.getLogger(__name__)


def _agg_to_dto(candle: AggCandle, venue: str) -> CandleDTO:
    return CandleDTO(
        symbol=candle.symbol,
        venue=venue,
        timeframe=candle.timeframe,
        ts=datetime.utcfromtimestamp(candle.ts_close / 1000).replace(microsecond=0),
        open=float(candle.open),
        high=float(candle.high),
        low=float(candle.low),
        close=float(candle.close),
        volume=float(candle.volume),
        ingested_at=datetime.utcnow().replace(microsecond=0),
    )


def _retry_fetch(
    provider: MarketDataProvider,
    symbol: str,
    timeframe: str,
    start_ts: datetime,
    end_ts: datetime,
    limit: int,
    retries: int,
    backoff_seconds: int,
) -> list[CandleDTO]:
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return provider.fetch_ohlcv(symbol, timeframe, start_ts, end_ts, limit)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt + 1 >= max(1, retries):
                break
            sleep_s = max(1, backoff_seconds) * (2**attempt)
            logger.warning("WS repair fetch failed (%s), retry in %ss", exc, sleep_s)
            time.sleep(sleep_s)
    if last_exc is not None:
        raise last_exc
    return []


def _ws_warmup_from_rest(repo: CandleRepository, provider: MarketDataProvider, cfg: AppConfig, symbols: list[str], venue: str) -> None:
    now = datetime.utcnow().replace(microsecond=0)
    tf = "1m"
    tf_delta = timeframe_to_timedelta(tf)
    end = align_to_candle_close(now, tf) - tf_delta
    warmup_bars = max(50, min(cfg.ingestion.warmup_bars, cfg.ingestion.warmup_bars_per_cycle_cap))
    start = end - tf_delta * (warmup_bars - 1)
    limit = max(200, warmup_bars + 10)

    for symbol in symbols:
        candles = _retry_fetch(
            provider=provider,
            symbol=symbol,
            timeframe=tf,
            start_ts=start,
            end_ts=end,
            limit=limit,
            retries=cfg.ingestion.retries,
            backoff_seconds=cfg.ingestion.backoff_seconds,
        )
        if candles:
            repo.upsert_candles(candles)

        if not cfg.ingestion.ws_rollup_timeframes:
            continue

        frame = repo.get_candles(symbol=symbol, timeframe="1m", venue=venue, start=start, end=end, limit=warmup_bars + 200)
        if frame.empty:
            continue

        agg_rows = [
            AggCandle(
                symbol=symbol,
                timeframe="1m",
                ts_close=int(pd.to_datetime(row["ts"]).to_pydatetime().replace(tzinfo=timezone.utc).timestamp() * 1000),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for _, row in frame.iterrows()
        ]

        for target_tf in cfg.ingestion.ws_rollup_timeframes:
            rolled = rollup_candles(agg_rows, target_tf)
            if rolled:
                repo.upsert_candles([_agg_to_dto(item, venue) for item in rolled])


def _detect_missing_1m_intervals(repo: CandleRepository, symbol: str, venue: str, lookback_limit: int = 240) -> list[tuple[datetime, datetime]]:
    frame = repo.get_candles(symbol=symbol, timeframe="1m", venue=venue, start=None, end=None, limit=lookback_limit, latest=True)
    gaps = detect_gaps(frame, "1m")
    return [(gap.start_ts, gap.end_ts) for gap in gaps]


def _repair_gaps_from_rest(
    repo: CandleRepository,
    provider: MarketDataProvider,
    cfg: AppConfig,
    symbol: str,
    venue: str,
    intervals: list[tuple[datetime, datetime]],
) -> None:
    if not intervals or not cfg.ingestion.gap_repair_enabled:
        return

    minute = timeframe_to_timedelta("1m")
    max_minutes = max(1, cfg.ingestion.gap_repair_max_minutes)
    for start_ts, end_ts in intervals:
        missing_minutes = int(((end_ts - start_ts) / minute)) + 1
        if missing_minutes > max_minutes:
            logger.warning("Skipping gap repair for %s due to size=%s min (max=%s)", symbol, missing_minutes, max_minutes)
            continue

        repaired = _retry_fetch(
            provider=provider,
            symbol=symbol,
            timeframe="1m",
            start_ts=start_ts,
            end_ts=end_ts,
            limit=max(200, missing_minutes + 5),
            retries=cfg.ingestion.retries,
            backoff_seconds=cfg.ingestion.gap_repair_backoff_seconds,
        )
        if repaired:
            repo.upsert_candles(repaired)


def _run_ws_trades_loop(
    repo: CandleRepository,
    provider: MarketDataProvider,
    cfg: AppConfig,
    symbols: list[str],
    venue: str,
    should_continue: Callable[[], bool],
) -> None:
    _ws_warmup_from_rest(repo, provider, cfg, symbols, venue)

    aggregator = TradeToCandleAggregator()
    rollup_targets = [item for item in cfg.ingestion.ws_rollup_timeframes if item in {"5m", "1h"}]
    one_minute_buffers: dict[str, deque[AggCandle]] = defaultdict(lambda: deque(maxlen=240))
    last_rollup_close_ms: dict[tuple[str, str], int] = {}
    symbol_last_gap_check_at: dict[str, float] = defaultdict(float)
    symbol_last_gap_repair_at: dict[str, float] = defaultdict(float)

    gap_check_interval_seconds = max(15, cfg.ingestion.poll_delay_seconds * 3)
    gap_repair_cooldown_seconds = max(30, cfg.ingestion.poll_delay_seconds * 6)
    max_repair_intervals_per_cycle = 2

    for symbol in symbols:
        for target_tf in rollup_targets:
            latest = repo.get_latest_candle_ts(symbol=symbol, timeframe=target_tf, venue=venue)
            if latest is not None:
                last_rollup_close_ms[(symbol, target_tf)] = int(latest.replace(tzinfo=timezone.utc).timestamp() * 1000)

    def _maybe_repair_symbol_gaps(symbol: str) -> None:
        if not cfg.ingestion.gap_repair_enabled:
            return

        now_mono = time.monotonic()
        last_check = symbol_last_gap_check_at[symbol]
        if (now_mono - last_check) < gap_check_interval_seconds:
            return

        symbol_last_gap_check_at[symbol] = now_mono
        intervals = _detect_missing_1m_intervals(repo, symbol, venue, lookback_limit=240)
        if not intervals:
            return

        last_repair = symbol_last_gap_repair_at[symbol]
        if (now_mono - last_repair) < gap_repair_cooldown_seconds:
            logger.info(
                "Deferring gap repair for %s: cooldown active (%.1fs remaining)",
                symbol,
                gap_repair_cooldown_seconds - (now_mono - last_repair),
            )
            return

        selected = intervals[-max_repair_intervals_per_cycle:]
        _repair_gaps_from_rest(repo, provider, cfg, symbol, venue, selected)
        symbol_last_gap_repair_at[symbol] = time.monotonic()

    def _on_trade(trade: Trade) -> None:
        closed = aggregator.ingest_trade(trade)
        if not closed:
            return

        repo.upsert_candles([_agg_to_dto(item, venue) for item in closed])

        for one_min in closed:
            one_minute_buffers[one_min.symbol].append(one_min)

            for target_tf in rollup_targets:
                rolled = rollup_candles(list(one_minute_buffers[one_min.symbol]), target_tf)
                if not rolled:
                    continue

                new_rows: list[AggCandle] = []
                watermark = last_rollup_close_ms.get((one_min.symbol, target_tf), 0)
                for row in rolled:
                    if row.ts_close > watermark:
                        new_rows.append(row)

                if not new_rows:
                    continue

                repo.upsert_candles([_agg_to_dto(item, venue) for item in new_rows])
                last_rollup_close_ms[(one_min.symbol, target_tf)] = max(item.ts_close for item in new_rows)

            _maybe_repair_symbol_gaps(one_min.symbol)

    stream = CoinbaseWsTradeStream(
        symbols=symbols,
        reconnect_initial_backoff_seconds=cfg.ingestion.ws_reconnect_initial_backoff_seconds,
        reconnect_max_backoff_seconds=cfg.ingestion.ws_reconnect_max_backoff_seconds,
    )
    stream.run(on_trade_callback=_on_trade, should_continue=should_continue)


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

    if cfg.ingestion.mode == "ws_trades":
        logger.info("Running ingestion in ws_trades mode for symbols=%s", symbols)
        _run_ws_trades_loop(
            repo=repo,
            provider=provider,
            cfg=cfg,
            symbols=symbols,
            venue=venue,
            should_continue=should_continue,
        )
        return

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
