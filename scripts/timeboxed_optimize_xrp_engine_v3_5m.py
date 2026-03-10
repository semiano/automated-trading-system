from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "artifacts" / "vps_xrp_tuning.db"
DEFAULT_TIMEBOX_SECONDS = 20 * 60
BATCH_SIZE = 24
SEED = 123


def timeframe_to_minutes(timeframe: str) -> int:
    if timeframe.endswith("m"):
        return int(timeframe[:-1])
    if timeframe.endswith("h"):
        return int(timeframe[:-1]) * 60
    if timeframe.endswith("d"):
        return int(timeframe[:-1]) * 24 * 60
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def annualization_factor_for_timeframe(timeframe: str) -> float:
    bars_per_year = (365.0 * 24.0 * 60.0) / float(timeframe_to_minutes(timeframe))
    return bars_per_year ** 0.5


@dataclass
class Params:
    bb_length: int
    bb_stdev: float
    atr_length: int
    ema_fast: int
    ema_slow: int
    bb_entry_deviation: float
    bb_exit_deviation: float
    slope_lookback_bars: int
    slope_flatten_factor: float
    stop_atr: float
    take_profit_atr: float
    max_hold_bars: int


def load_candles(db_path: Path, symbol: str, venue: str, timeframe: str, lookback_days: int) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    try:
        query = """
        SELECT ts, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND venue = ? AND timeframe = ? AND ts >= datetime('now', ?)
        ORDER BY ts ASC
        """
        df = pd.read_sql_query(query, con, params=(symbol, venue, timeframe, f"-{lookback_days} day"))
    finally:
        con.close()
    if df.empty and timeframe == "5m":
        # Fallback for local tuning DB snapshots that only include 1m candles.
        con = sqlite3.connect(str(db_path))
        try:
            one_min = pd.read_sql_query(
                """
                SELECT ts, open, high, low, close, volume
                FROM candles
                WHERE symbol = ? AND venue = ? AND timeframe = '1m' AND ts >= datetime('now', ?)
                ORDER BY ts ASC
                """,
                con,
                params=(symbol, venue, f"-{lookback_days} day"),
            )
        finally:
            con.close()
        if not one_min.empty:
            one_min["ts"] = pd.to_datetime(one_min["ts"], utc=True)
            for col in ["open", "high", "low", "close", "volume"]:
                one_min[col] = pd.to_numeric(one_min[col], errors="coerce")
            one_min = one_min.dropna().set_index("ts")
            rolled = one_min.resample("5min", label="right", closed="right").agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            rolled = rolled.dropna().reset_index()
            df = rolled
    if df.empty:
        raise RuntimeError(f"No candles for {symbol} {timeframe}")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna().reset_index(drop=True)


def compute_indicators(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = df.copy().reset_index(drop=True)
    out["bb_mid"] = out["close"].rolling(p.bb_length).mean()
    bb_std = out["close"].rolling(p.bb_length).std(ddof=0)
    out["bb_upper"] = out["bb_mid"] + (p.bb_stdev * bb_std)
    out["bb_lower"] = out["bb_mid"] - (p.bb_stdev * bb_std)

    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - out["close"].shift(1)).abs(),
            (out["low"] - out["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(p.atr_length).mean()

    out[f"ema{p.ema_fast}"] = out["close"].ewm(span=p.ema_fast, adjust=False).mean()
    out[f"ema{p.ema_slow}"] = out["close"].ewm(span=p.ema_slow, adjust=False).mean()
    return out


def bb_deviation(row: pd.Series) -> float | None:
    close = row.get("close")
    mid = row.get("bb_mid")
    low = row.get("bb_lower")
    up = row.get("bb_upper")
    if pd.isna(close) or pd.isna(mid) or pd.isna(low) or pd.isna(up):
        return None
    half = (float(up) - float(low)) * 0.5
    if half <= 0:
        return None
    return (float(close) - float(mid)) / half


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = (equity / running_max) - 1.0
    return float(dd.min()) if not dd.empty else 0.0


def backtest(df: pd.DataFrame, p: Params, timeframe: str) -> dict:
    work = compute_indicators(df, p)
    fast_col = f"ema{p.ema_fast}"
    slow_col = f"ema{p.ema_slow}"

    cash = 1.0
    qty = 0.0
    side: str | None = None
    entry = 0.0
    stop = None
    tp = None
    hold = 0
    trades = 0
    wins = 0
    eq_curve: list[float] = []

    for i in range(max(3, p.slope_lookback_bars + 1), len(work)):
        prev = work.iloc[i - 1]
        bar = work.iloc[i]

        dev = bb_deviation(prev)
        if dev is None or pd.isna(prev.get("atr")):
            eq_curve.append(cash + qty * float(bar["close"]))
            continue

        if pd.isna(prev.get(fast_col)) or pd.isna(prev.get(slow_col)) or pd.isna(work.iloc[i - 2].get(fast_col)):
            eq_curve.append(cash + qty * float(bar["close"]))
            continue

        ema_fast = float(prev[fast_col])
        ema_slow = float(prev[slow_col])
        slope_now = float(prev[fast_col]) - float(work.iloc[i - 2][fast_col])
        slope_lookback = (float(prev[fast_col]) - float(work.iloc[i - 1 - p.slope_lookback_bars][fast_col])) / float(p.slope_lookback_bars)
        flatten_ratio = abs(slope_now) / max(abs(slope_lookback), 1e-12)
        long_round = slope_now > slope_lookback and slope_now < 0 and flatten_ratio <= p.slope_flatten_factor
        short_round = slope_now < slope_lookback and slope_now > 0 and flatten_ratio <= p.slope_flatten_factor

        if qty <= 0:
            long_signal = dev <= -p.bb_entry_deviation and ema_fast <= ema_slow and long_round and float(prev["close"]) <= ema_fast
            short_signal = dev >= p.bb_entry_deviation and ema_fast >= ema_slow and short_round and float(prev["close"]) >= ema_fast
            if not (long_signal or short_signal):
                eq_curve.append(cash)
                continue

            entry_px = float(bar["open"])
            qty = cash / max(entry_px, 1e-9)
            cash = 0.0
            entry = entry_px
            atr = float(prev["atr"])
            side = "long" if long_signal else "short"
            if side == "short":
                stop = entry + (p.stop_atr * atr)
                tp = entry - (p.take_profit_atr * atr)
            else:
                stop = entry - (p.stop_atr * atr)
                tp = entry + (p.take_profit_atr * atr)
            hold = 0
            trades += 1
        else:
            hold += 1
            if side == "short":
                stop_hit = stop is not None and float(bar["high"]) >= float(stop)
                tp_hit = tp is not None and float(bar["low"]) <= float(tp)
                signal_exit = dev <= p.bb_exit_deviation or (float(prev["close"]) <= ema_fast and slope_now <= 0)
            else:
                stop_hit = stop is not None and float(bar["low"]) <= float(stop)
                tp_hit = tp is not None and float(bar["high"]) >= float(tp)
                signal_exit = dev >= -p.bb_exit_deviation or (float(prev["close"]) >= ema_fast and slope_now >= 0)

            timed_exit = hold >= p.max_hold_bars
            if stop_hit or tp_hit or signal_exit or timed_exit:
                if stop_hit:
                    exit_px = float(stop)
                elif tp_hit:
                    exit_px = float(tp)
                else:
                    exit_px = float(bar["open"])
                if side == "short":
                    cash = qty * (2 * entry - exit_px)
                    wins += 1 if exit_px < entry else 0
                else:
                    cash = qty * exit_px
                    wins += 1 if exit_px > entry else 0
                qty = 0.0
                side = None
                hold = 0

        mark = cash if qty <= 0 else (qty * float(bar["close"]) if side == "long" else qty * (2 * entry - float(bar["close"])))
        eq_curve.append(mark)

    if qty > 0:
        final_close = float(work.iloc[-1]["close"])
        cash = qty * final_close if side == "long" else qty * (2 * entry - final_close)
        qty = 0.0
        eq_curve.append(cash)

    if not eq_curve:
        eq_curve = [1.0]

    eq = pd.Series(eq_curve, dtype=float)
    total_return = float(eq.iloc[-1] - 1.0)
    mdd = max_drawdown(eq)
    ret = eq.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    annualizer = annualization_factor_for_timeframe(timeframe)
    sharpe = float((ret.mean() / ret.std()) * annualizer) if len(ret) > 2 and float(ret.std()) > 0 else 0.0
    win_rate = float(wins / trades) if trades else 0.0

    score = (total_return * 800.0) + (sharpe * 10.0) + (mdd * 160.0) + min(trades, 220) * 0.2
    if total_return <= 0:
        score -= 140.0
    if trades < 25:
        score -= (25.0 - trades) * 2.0

    return {
        "score": float(score),
        "total_return": total_return,
        "max_drawdown": float(mdd),
        "sharpe": sharpe,
        "trades": int(trades),
        "win_rate": win_rate,
    }


def random_params(rng: random.Random) -> Params:
    ema_fast = rng.choice([12, 16, 20, 24, 28])
    ema_slow = rng.choice([34, 40, 50, 55, 65])
    if ema_fast >= ema_slow:
        ema_fast = max(8, ema_slow - 2)
    return Params(
        bb_length=rng.choice([18, 20, 22, 24, 26]),
        bb_stdev=rng.choice([1.8, 2.0, 2.2, 2.4]),
        atr_length=rng.choice([10, 12, 14, 16]),
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        bb_entry_deviation=rng.choice([0.9, 1.0, 1.05, 1.1, 1.2]),
        bb_exit_deviation=rng.choice([0.05, 0.1, 0.15, 0.2, 0.25]),
        slope_lookback_bars=rng.choice([2, 3, 4, 5]),
        slope_flatten_factor=rng.choice([0.65, 0.72, 0.8, 0.9]),
        stop_atr=rng.choice([1.0, 1.2, 1.4, 1.6]),
        take_profit_atr=rng.choice([1.8, 2.0, 2.2, 2.6, 3.0]),
        max_hold_bars=rng.choice([30, 40, 50, 60, 72]),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Timeboxed optimizer for engine v3 across timeframes")
    parser.add_argument("--timeframe", default="5m", choices=["1m", "5m", "1h"], help="Target timeframe")
    parser.add_argument("--lookback-days", type=int, default=180, help="Lookback days to query from local tuning DB")
    parser.add_argument("--timebox-minutes", type=int, default=20, help="Timebox duration in minutes")
    parser.add_argument("--seed", type=int, default=SEED, help="RNG seed")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"Missing input DB: {DB_PATH}")

    symbol = "XRP/USD"
    venue = "coinbase"
    timeframe = args.timeframe
    lookback_days = int(args.lookback_days)
    timebox_seconds = int(args.timebox_minutes) * 60
    timeframe_tag = timeframe.replace("/", "_")
    OUT_REPORT = ROOT / "artifacts" / f"xrp_engine_v3_{timeframe_tag}_timeboxed_report.json"
    OUT_BEST = ROOT / "artifacts" / f"xrp_engine_v3_{timeframe_tag}_best_params.yaml"
    params_key = f"xrp_engine_v3_{timeframe_tag}_params"

    df = load_candles(DB_PATH, symbol, venue, timeframe, lookback_days)
    split = max(int(len(df) * 0.7), 400)
    if split >= len(df) - 150:
        split = int(len(df) * 0.65)

    train = df.iloc[:split].reset_index(drop=True)
    test = df.iloc[split:].reset_index(drop=True)
    min_train_rows = 120 if timeframe in {"1m", "5m"} else 50
    min_test_rows = 60 if timeframe in {"1m", "5m"} else 25
    if len(train) < min_train_rows or len(test) < min_test_rows:
        raise SystemExit(f"Insufficient rows for robust split: train={len(train)} test={len(test)}")

    rng = random.Random(args.seed)
    start = time.time()
    best: dict | None = None
    leaderboard: list[dict] = []
    iterations = 0
    batches = 0

    while time.time() - start < timebox_seconds:
        params_batch = [random_params(rng) for _ in range(BATCH_SIZE)]
        for p in params_batch:
            train_metrics = backtest(train, p, timeframe)
            test_metrics = backtest(test, p, timeframe)
            full_metrics = backtest(df, p, timeframe)
            robust_score = (train_metrics["score"] * 0.35) + (test_metrics["score"] * 0.65)
            candidate = {
                "params": p,
                "train": train_metrics,
                "test": test_metrics,
                "full": full_metrics,
                "robust_score": float(robust_score),
            }
            if best is None or robust_score > best["robust_score"]:
                best = candidate
            leaderboard.append(candidate)

        iterations += BATCH_SIZE
        batches += 1

    if best is None:
        raise SystemExit("No candidates evaluated")

    top = sorted(leaderboard, key=lambda x: x["robust_score"], reverse=True)[:25]

    report_payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "db_path": str(DB_PATH.relative_to(ROOT)),
            "symbol": symbol,
            "venue": venue,
            "timeframe": timeframe,
            "lookback_days": lookback_days,
            "rows": len(df),
            "split_train_rows": len(train),
            "split_test_rows": len(test),
        },
        "optimizer": {
            "seed": int(args.seed),
            "timebox_minutes": int(args.timebox_minutes),
            "batch_size": BATCH_SIZE,
            "iterations_evaluated": iterations,
            "batches": batches,
            "objective": "robust_score = 35% train + 65% test",
        },
        "best": {
            "robust_score": float(best["robust_score"]),
            "params": asdict(best["params"]),
            "train": best["train"],
            "test": best["test"],
            "full": best["full"],
        },
        "leaderboard_top_25": [
            {
                "robust_score": float(item["robust_score"]),
                "params": asdict(item["params"]),
                "train": item["train"],
                "test": item["test"],
                "full": item["full"],
            }
            for item in top
        ],
    }

    best_payload = {
        "generated_at_utc": report_payload["generated_at_utc"],
        "symbol": symbol,
        "venue": venue,
        "timeframe": timeframe,
        "selection_basis": f"timeboxed_{int(args.timebox_minutes)}m_robust_score",
        "source_summary": str(OUT_REPORT.relative_to(ROOT)),
        params_key: asdict(best["params"]),
        "best_observed_metrics": {
            "robust_score": float(best["robust_score"]),
            "train": best["train"],
            "test": best["test"],
            "full": best["full"],
        },
    }

    OUT_REPORT.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    OUT_BEST.write_text(yaml.safe_dump(best_payload, sort_keys=False), encoding="utf-8")

    print(json.dumps({
        "status": "ok",
        "report": str(OUT_REPORT),
        "best_params": str(OUT_BEST),
        "robust_score": float(best["robust_score"]),
        "full": best["full"],
    }, indent=2))


if __name__ == "__main__":
    main()
