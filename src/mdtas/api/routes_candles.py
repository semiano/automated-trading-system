from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mdtas.api.schemas import CandleOut
from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.utils.validation import ensure_known_symbol, ensure_supported_timeframe

router = APIRouter(tags=["candles"])


def get_repo(session: Session = Depends(get_session)) -> CandleRepository:
    try:
        yield CandleRepository(session)
    finally:
        session.close()


@router.get("/symbols")
def symbols(repo: CandleRepository = Depends(get_repo)) -> dict:
    cfg = get_config()
    return {"symbols": sorted(set(cfg.symbols))}


@router.get("/candles", response_model=list[CandleOut])
def candles(
    symbol: str,
    timeframe: str,
    venue: str = "mock",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=2000, ge=1, le=200000),
    repo: CandleRepository = Depends(get_repo),
):
    cfg = get_config()
    try:
        ensure_known_symbol(symbol, cfg)
        ensure_supported_timeframe(timeframe, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    df = repo.get_candles(symbol, timeframe, venue, start, end, limit)
    return [
        CandleOut(
            ts=row.ts,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in df.itertuples(index=False)
    ]
