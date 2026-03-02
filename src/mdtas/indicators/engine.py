from __future__ import annotations

import pandas as pd

from mdtas.indicators.atr import compute_atr
from mdtas.indicators.bollinger import compute_bollinger
from mdtas.indicators.ema import compute_ema
from mdtas.indicators.rsi import compute_rsi
from mdtas.indicators.volume import compute_volume_sma
from mdtas.indicators.vwap import compute_rolling_vwap


def compute(
    df: pd.DataFrame,
    indicators_requested: list[str],
    params: dict,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    out = df.copy().sort_values("ts").reset_index(drop=True)
    req = set(indicators_requested)

    if "bbands" in req or any(k.startswith("bb_") for k in req):
        bb_cfg = params.get("bollinger", {})
        bb = compute_bollinger(
            out,
            length=int(bb_cfg.get("length", 20)),
            stdev=float(bb_cfg.get("stdev", 2.0)),
        )
        for col in bb.columns:
            out[col] = bb[col]

    if "rsi" in req:
        out["rsi"] = compute_rsi(out, length=int(params.get("rsi", {}).get("length", 14)))

    if "atr" in req:
        out["atr"] = compute_atr(out, length=int(params.get("atr", {}).get("length", 14)))

    ema_lengths = params.get("ema_lengths", [20, 50, 200])
    for length in ema_lengths:
        key = f"ema{length}"
        if "ema" in req or key in req:
            out[key] = compute_ema(out, int(length))

    if "vwap" in req:
        out["vwap"] = compute_rolling_vwap(out, window=int(params.get("volume_sma", 20)))

    if "volume_sma" in req:
        out["volume_sma"] = compute_volume_sma(out, length=int(params.get("volume_sma", 20)))

    return out
