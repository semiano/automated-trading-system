from __future__ import annotations

from typing import Any

import pandas as pd


def compute_htf_regime(htf_df: pd.DataFrame, cfg) -> dict[str, Any]:
    if htf_df is None or len(htf_df) == 0:
        return {
            "trend_state": "neutral",
            "chop_state": "unknown",
            "ema_fast": None,
            "ema_slow": None,
            "bb_width_norm": None,
            "atr_pct": None,
        }

    frame = htf_df.sort_values("ts").reset_index(drop=True).copy()
    close = pd.to_numeric(frame["close"], errors="coerce")

    fast_span = int(cfg.trading.regime_trend_ema_fast)
    slow_span = int(cfg.trading.regime_trend_ema_slow)

    ema_fast_series = close.ewm(span=fast_span, adjust=False, min_periods=fast_span).mean()
    ema_slow_series = close.ewm(span=slow_span, adjust=False, min_periods=slow_span).mean()

    ema_fast = float(ema_fast_series.iloc[-1]) if pd.notna(ema_fast_series.iloc[-1]) else None
    ema_slow = float(ema_slow_series.iloc[-1]) if pd.notna(ema_slow_series.iloc[-1]) else None

    trend_state = "neutral"
    if ema_fast is not None and ema_slow is not None:
        if ema_fast > ema_slow:
            trend_state = "bull"
        elif ema_fast < ema_slow:
            trend_state = "bear"

    chop_mode = str(cfg.trading.chop_filter_mode)
    chop_state = "unknown"
    bb_width_norm: float | None = None
    atr_pct: float | None = None

    if chop_mode == "none":
        chop_state = "ok"
    elif chop_mode == "bb_width":
        length = int(cfg.trading.chop_bb_length)
        stdev_mult = float(cfg.trading.chop_bb_stdev)
        mid = close.rolling(window=length, min_periods=length).mean()
        std = close.rolling(window=length, min_periods=length).std(ddof=0)
        upper = mid + (std * stdev_mult)
        lower = mid - (std * stdev_mult)
        if pd.notna(mid.iloc[-1]) and pd.notna(upper.iloc[-1]) and pd.notna(lower.iloc[-1]) and float(mid.iloc[-1]) != 0.0:
            bb_width_norm = float((upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1])
            chop_state = "chop" if bb_width_norm < float(cfg.trading.chop_bb_width_min) else "ok"
    elif chop_mode == "atr_pct":
        atr_length = int(cfg.indicators.atr.length)
        high = pd.to_numeric(frame["high"], errors="coerce")
        low = pd.to_numeric(frame["low"], errors="coerce")
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(window=atr_length, min_periods=atr_length).mean()
        if pd.notna(atr.iloc[-1]) and pd.notna(close.iloc[-1]) and float(close.iloc[-1]) != 0.0:
            atr_pct = float(atr.iloc[-1] / close.iloc[-1])
            chop_state = "chop" if atr_pct < float(cfg.trading.chop_atr_pct_min) else "ok"

    return {
        "trend_state": trend_state,
        "chop_state": chop_state,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "bb_width_norm": bb_width_norm,
        "atr_pct": atr_pct,
    }
