from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mdtas.api.schemas import BackfillRequest, BackfillResult
from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.indicators.engine import compute
from mdtas.ingestion.backfill import run_backfill
from mdtas.ingestion.scheduler import build_provider
from mdtas.utils.validation import ensure_known_symbol, ensure_supported_timeframe

router = APIRouter(tags=["features"])


def get_repo(session: Session = Depends(get_session)):
    try:
        yield CandleRepository(session)
    finally:
        session.close()


@router.post("/backfill", response_model=list[BackfillResult])
def backfill(req: BackfillRequest, repo: CandleRepository = Depends(get_repo)):
    cfg = get_config()
    provider = build_provider(cfg)
    venue = req.venue or cfg.providers.ccxt.venue if cfg.providers.default_provider == "ccxt" else "mock"
    symbols = req.symbols or cfg.symbols
    timeframes = req.timeframes or cfg.timeframes

    results: list[BackfillResult] = []
    for symbol in symbols:
        ensure_known_symbol(symbol, cfg)
        for timeframe in timeframes:
            ensure_supported_timeframe(timeframe, cfg)
            r = run_backfill(
                repo=repo,
                provider=provider,
                cfg=cfg,
                symbol=symbol,
                timeframe=timeframe,
                venue=venue,
                start=req.start,
                end=req.end,
                lookback_days=req.lookback_days,
            )
            results.append(BackfillResult(**r))
    return results


@router.get("/features")
def features(
    symbol: str,
    timeframe: str,
    venue: str = "mock",
    start: datetime | None = None,
    end: datetime | None = None,
    indicators: str = "bbands,rsi,atr,ema20,ema50,ema200,volume_sma,vwap",
    format: str = Query(default="json"),
    repo: CandleRepository = Depends(get_repo),
):
    cfg = get_config()
    try:
        ensure_known_symbol(symbol, cfg)
        ensure_supported_timeframe(timeframe, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    requested = [s.strip() for s in indicators.split(",") if s.strip()]
    frame = repo.get_candles(symbol, timeframe, venue, start, end, limit=200000)
    out = compute(frame, requested, cfg.indicators.model_dump())
    if format != "json":
        raise HTTPException(status_code=422, detail="Only format=json is supported in MVP")
    return {"rows": out.where(out.notna(), None).to_dict(orient="records")}
