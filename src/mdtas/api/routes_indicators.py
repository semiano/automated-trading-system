from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.indicators.engine import compute
from mdtas.utils.validation import ensure_known_symbol, ensure_supported_timeframe

router = APIRouter(tags=["indicators"])


def get_repo(session: Session = Depends(get_session)):
    try:
        yield CandleRepository(session)
    finally:
        session.close()


def _parse_indicators(indicators: str | None) -> list[str]:
    if not indicators:
        return ["bbands", "rsi", "atr", "ema20", "ema50", "ema200", "volume_sma", "vwap"]
    return [item.strip() for item in indicators.split(",") if item.strip()]


@router.get("/indicators")
def indicators(
    symbol: str,
    timeframe: str,
    venue: str = "mock",
    start: datetime | None = None,
    end: datetime | None = None,
    indicators: str | None = Query(default=None),
    repo: CandleRepository = Depends(get_repo),
):
    cfg = get_config()
    try:
        ensure_known_symbol(symbol, cfg)
        ensure_supported_timeframe(timeframe, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    req = _parse_indicators(indicators)
    frame = repo.get_candles(symbol, timeframe, venue, start, end, limit=200000)
    out = compute(frame, req, cfg.indicators.model_dump())
    clean = out.replace([float("inf"), float("-inf")], None)
    return {"rows": json.loads(clean.to_json(orient="records", date_format="iso"))}
