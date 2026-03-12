from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
import pandas as pd
from sqlalchemy.orm import Session

from mdtas.config import get_config
from mdtas.db.repo import CandleRepository
from mdtas.db.session import get_session
from mdtas.db.trading_repo import TradingRepository
from mdtas.indicators.engine import compute
from mdtas.trading.runtime_1m_simple import Simple1mParamResolver
from mdtas.trading.runtime_5m_simple import Simple5mParamResolver
from mdtas.utils.validation import ensure_known_symbol, ensure_supported_timeframe

router = APIRouter(tags=["indicators"])


def get_repo(session: Session = Depends(get_session)):
    try:
        yield CandleRepository(session)
    finally:
        session.close()


def get_trading_repo(session: Session = Depends(get_session)):
    try:
        yield TradingRepository(session)
    finally:
        session.close()


def _parse_indicators(indicators: str | None) -> list[str]:
    if not indicators:
        return ["bbands", "rsi", "atr", "ema20", "ema50", "ema200", "volume_sma", "vwap"]
    return [item.strip() for item in indicators.split(",") if item.strip()]


def _append_simple_engine_diagnostics(
    frame: pd.DataFrame,
    *,
    ema_fast: int,
    ema_slow: int,
    slope_lookback_bars: int,
    slope_flatten_factor: float,
    entry_deviation: float,
) -> pd.DataFrame:
    out = frame.copy()
    out["bb_deviation"] = None
    out["entry_deviation"] = float(entry_deviation)
    out["slope_now"] = None
    out["slope_lookback"] = None
    out["flatten_ratio"] = None
    out["long_rounding"] = None
    out["short_rounding"] = None
    out["long_entry_signal"] = None
    out["short_entry_signal"] = None
    out["engine_ema_fast"] = int(ema_fast)
    out["engine_ema_slow"] = int(ema_slow)
    out["engine_slope_lookback_bars"] = int(slope_lookback_bars)
    out["engine_diag_status"] = "ok"

    ema_fast_col = f"ema{int(ema_fast)}"
    ema_slow_col = f"ema{int(ema_slow)}"
    required = ["close", "bb_mid", "bb_lower", "bb_upper", ema_fast_col, ema_slow_col]
    missing = [col for col in required if col not in out.columns]
    if missing:
        out["engine_diag_status"] = f"missing_cols:{','.join(missing)}"
        return out

    half_width = (out["bb_upper"] - out["bb_lower"]) * 0.5
    bb_valid = out["close"].notna() & out["bb_mid"].notna() & half_width.notna() & (half_width > 0)
    bb_deviation = (out["close"] - out["bb_mid"]) / half_width
    out["bb_deviation"] = bb_deviation.where(bb_valid)

    lookback = max(2, int(slope_lookback_bars))
    slope_now = out[ema_fast_col] - out[ema_fast_col].shift(1)
    slope_lookback_shift = max(1, lookback - 1)
    slope_lookback = (out[ema_fast_col] - out[ema_fast_col].shift(slope_lookback_shift)) / float(lookback)
    slope_valid = out[ema_fast_col].notna() & out[ema_fast_col].shift(1).notna() & out[ema_fast_col].shift(slope_lookback_shift).notna()
    out["slope_now"] = slope_now.where(slope_valid)
    out["slope_lookback"] = slope_lookback.where(slope_valid)

    flatten_ratio = slope_now.abs() / slope_lookback.abs().clip(lower=1e-12)
    out["flatten_ratio"] = flatten_ratio.where(slope_valid)

    # Rounding gate is temporarily disabled in runtime; keep columns for UI compatibility.
    out["long_rounding"] = pd.Series(True, index=out.index, dtype="boolean").where(slope_valid)
    out["short_rounding"] = pd.Series(True, index=out.index, dtype="boolean").where(slope_valid)

    signal_base = bb_valid & slope_valid & out[ema_fast_col].notna() & out[ema_slow_col].notna()
    long_entry = (
        (bb_deviation <= -float(entry_deviation))
        & (out[ema_fast_col] <= out[ema_slow_col])
        & (out["close"] <= out[ema_fast_col])
    )
    short_entry = (
        (bb_deviation >= float(entry_deviation))
        & (out[ema_fast_col] >= out[ema_slow_col])
        & (out["close"] >= out[ema_fast_col])
    )
    out["long_entry_signal"] = long_entry.where(signal_base)
    out["short_entry_signal"] = short_entry.where(signal_base)
    return out


@router.get("/indicators")
def indicators(
    symbol: str,
    timeframe: str,
    venue: str = "mock",
    start: datetime | None = None,
    end: datetime | None = None,
    indicators: str | None = Query(default=None),
    repo: CandleRepository = Depends(get_repo),
    trading_repo: TradingRepository = Depends(get_trading_repo),
):
    cfg = get_config()
    try:
        ensure_known_symbol(symbol, cfg)
        ensure_supported_timeframe(timeframe, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    req = _parse_indicators(indicators)
    req_set = set(req)

    simple_runtime = None
    if timeframe == "1m":
        params = Simple1mParamResolver(cfg, trading_repo).for_symbol(symbol)
        simple_runtime = {
            "ema_fast": int(params.ema_fast),
            "ema_slow": int(params.ema_slow),
            "slope_lookback_bars": int(params.slope_lookback_bars),
            "slope_flatten_factor": float(params.slope_flatten_factor),
            "entry_deviation": float(params.bb_entry_deviation),
        }
    elif timeframe == "5m":
        params = Simple5mParamResolver(cfg, trading_repo).for_symbol(symbol)
        simple_runtime = {
            "ema_fast": int(params.ema_fast),
            "ema_slow": int(params.ema_slow),
            "slope_lookback_bars": int(params.slope_lookback_bars),
            "slope_flatten_factor": float(params.slope_flatten_factor),
            "entry_deviation": float(params.bb_entry_deviation),
        }

    if simple_runtime is not None:
        req_set.update({
            "bbands",
            f"ema{simple_runtime['ema_fast']}",
            f"ema{simple_runtime['ema_slow']}",
        })

    frame = repo.get_candles(symbol, timeframe, venue, start, end, limit=200000)
    out = compute(frame, sorted(req_set), cfg.indicators.model_dump())
    if simple_runtime is not None:
        out = _append_simple_engine_diagnostics(
            out,
            ema_fast=simple_runtime["ema_fast"],
            ema_slow=simple_runtime["ema_slow"],
            slope_lookback_bars=simple_runtime["slope_lookback_bars"],
            slope_flatten_factor=simple_runtime["slope_flatten_factor"],
            entry_deviation=simple_runtime["entry_deviation"],
        )
    clean = out.replace([float("inf"), float("-inf")], None)
    return {"rows": json.loads(clean.to_json(orient="records", date_format="iso"))}
