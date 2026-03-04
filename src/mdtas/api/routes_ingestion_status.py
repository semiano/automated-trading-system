from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mdtas.api.schemas import CatchupStatusOut
from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.utils.timeframes import align_to_candle_close, timeframe_to_timedelta
from mdtas.utils.validation import ensure_known_symbol, ensure_supported_timeframe

router = APIRouter(tags=["ingestion"])


def get_repo(session: Session = Depends(get_session)):
    try:
        yield CandleRepository(session)
    finally:
        session.close()


def _status_for_pair(repo: CandleRepository, *, symbol: str, timeframe: str, venue: str) -> CatchupStatusOut:
    cfg = get_config()
    delta = timeframe_to_timedelta(timeframe)
    now = datetime.utcnow().replace(microsecond=0)
    close_boundary = align_to_candle_close(now, timeframe)
    target_end = close_boundary - delta

    latest_ts = repo.get_latest_candle_ts(symbol=symbol, timeframe=timeframe, venue=venue)
    if latest_ts is None:
        base_cursor = target_end - delta * 4
    else:
        base_cursor = latest_ts + delta

    bars_behind_before_jump = 0
    if base_cursor <= target_end:
        bars_behind_before_jump = int((target_end - base_cursor) / delta) + 1

    attempt_cursor = base_cursor
    max_catchup = max(10, cfg.ingestion.max_catchup_bars_per_cycle)
    if base_cursor <= target_end and cfg.ingestion.allow_gap_jump_to_recent and bars_behind_before_jump > max_catchup:
        attempt_cursor = target_end - delta * (max_catchup - 1)

    attempted_start = attempt_cursor if attempt_cursor <= target_end else None
    attempted_end = target_end if attempted_start is not None else None

    bars_attempted = 0
    if attempted_start is not None and attempted_end is not None:
        bars_attempted = int((attempted_end - attempted_start) / delta) + 1

    remaining_after_attempt = max(0, bars_behind_before_jump - bars_attempted)
    progress_pct = 100.0 if bars_behind_before_jump == 0 else round((bars_attempted / bars_behind_before_jump) * 100.0, 2)

    unresolved_gaps = repo.get_unresolved_gaps(
        symbol=symbol,
        timeframe=timeframe,
        venue=venue,
        start=None,
        end=None,
    )
    unresolved_gap_count = len(unresolved_gaps)
    unresolved_gap_bars_estimate = 0
    for gap in unresolved_gaps:
        unresolved_gap_bars_estimate += int((gap.end_ts - gap.start_ts) / delta) + 1

    last_gap_scan_ts = repo.get_latest_unresolved_gap_noted_at(symbol=symbol, timeframe=timeframe, venue=venue)

    return CatchupStatusOut(
        symbol=symbol,
        timeframe=timeframe,
        venue=venue,
        latest_ts=latest_ts,
        target_end_ts=target_end,
        attempted_start_ts=attempted_start,
        attempted_end_ts=attempted_end,
        bars_behind_before_jump=bars_behind_before_jump,
        bars_attempted_this_cycle=bars_attempted,
        remaining_after_attempt_bars=remaining_after_attempt,
        catchup_progress_pct=max(0.0, min(100.0, progress_pct)),
        unresolved_gap_count=unresolved_gap_count,
        unresolved_gap_bars_estimate=unresolved_gap_bars_estimate,
        last_gap_scan_ts=last_gap_scan_ts,
        is_caught_up=bars_behind_before_jump == 0,
    )


@router.get("/ingestion/catchup-status", response_model=list[CatchupStatusOut])
def catchup_status(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    venue: str | None = Query(default=None),
    repo: CandleRepository = Depends(get_repo),
):
    cfg = get_config()
    selected_venue = venue or (cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock")

    symbols = [symbol] if symbol else cfg.symbols
    timeframes = [timeframe] if timeframe else cfg.timeframes

    for item in symbols:
        try:
            ensure_known_symbol(item, cfg)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    for item in timeframes:
        try:
            ensure_supported_timeframe(item, cfg)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows: list[CatchupStatusOut] = []
    for sym in symbols:
        for tf in timeframes:
            rows.append(_status_for_pair(repo, symbol=sym, timeframe=tf, venue=selected_venue))

    return rows
