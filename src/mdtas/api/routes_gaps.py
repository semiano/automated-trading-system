from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mdtas.api.schemas import GapOut
from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.utils.validation import ensure_known_symbol, ensure_supported_timeframe

router = APIRouter(tags=["gaps"])


def get_repo(session: Session = Depends(get_session)):
    try:
        yield CandleRepository(session)
    finally:
        session.close()


@router.get("/gaps", response_model=list[GapOut])
def gaps(
    symbol: str,
    timeframe: str,
    venue: str = "mock",
    start: datetime | None = None,
    end: datetime | None = None,
    repo: CandleRepository = Depends(get_repo),
):
    cfg = get_config()
    try:
        ensure_known_symbol(symbol, cfg)
        ensure_supported_timeframe(timeframe, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    items = repo.get_unresolved_gaps(symbol, timeframe, venue, start, end)
    return [GapOut(start_ts=item.start_ts, end_ts=item.end_ts) for item in items]
