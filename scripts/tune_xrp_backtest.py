from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mdtas.indicators.engine import compute


@dataclass
class StrategyParams:
    rsi_length: int
    atr_length: int
    ema_fast: int
    ema_slow: int
    rsi_entry: float
    rsi_exit: float
    stop_atr: float
    take_profit_atr: float
    max_hold_bars: int

    def indicator_params(self) -> dict:
        return {
            "rsi": {"length": self.rsi_length},
            "atr": {"length": self.atr_length},
            "ema_lengths": [self.ema_fast, self.ema_slow],
            "volume_sma": 20,
        }


def load_candles(db_path: Path, symbol: str, venue: str, timeframe: str, lookback_days: int) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    try:
        query = """
            SELECT ts, open, high, low, close, volume
            FROM candles
            WHERE symbol = ?
              AND venue = ?
              AND timeframe = ?
              AND ts >= datetime('now', ?)
            ORDER BY ts ASC
        """
        df = pd.read_sql_query(query, con, params=(symbol, venue, timeframe, f"-{lookback_days} day"))
    finally:
        con.close()

    if df.empty:
        raise RuntimeError("No candles found for requested symbol/venue/timeframe/lookback.")

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["ts", "open", "high", "low", "close"]).reset_index(drop=True)
    return df


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = (equity / running_max) - 1.0
    return float(dd.min()) if not dd.empty else 0.0


def annualization_factor(timeframe: str) -> float:
    if timeframe == "1m":
        return math.sqrt(525600)
    if timeframe == "5m":
        return math.sqrt(105120)
    if timeframe == "1h":
        return math.sqrt(8760)
    return math.sqrt(365)


def backtest(df: pd.DataFrame, params: StrategyParams, timeframe: str, fee_bps: float, slippage_bps: float) -> dict:
    work = compute(df, ["rsi", "atr", f"ema{params.ema_fast}", f"ema{params.ema_slow}"], params.indicator_params())
    fast_col = f"ema{params.ema_fast}"
    slow_col = f"ema{params.ema_slow}"

    cash = 1.0
    qty = 0.0
    entry_price = 0.0
    stop_price = None
    tp_price = None
    hold_bars = 0
    trades = 0
    wins = 0

    fee = fee_bps / 10000.0
    slippage = slippage_bps / 10000.0

    equity_curve: list[float] = []

    for i in range(1, len(work)):
        prev = work.iloc[i - 1]
        bar = work.iloc[i]

        if qty <= 0:
            cond_ready = (
                pd.notna(prev.get("rsi"))
                and pd.notna(prev.get("atr"))
                and pd.notna(prev.get(fast_col))
                and pd.notna(prev.get(slow_col))
            )
            if cond_ready:
                entry_signal = (
                    float(prev["rsi"]) <= params.rsi_entry
                    and float(prev["close"]) > float(prev[fast_col])
                )
                if entry_signal and cash > 0:
                    exec_price = float(bar["open"]) * (1.0 + slippage)
                    qty = cash / (exec_price * (1.0 + fee))
                    cash = 0.0
                    entry_price = exec_price
                    atr = float(prev["atr"])
                    stop_price = entry_price - params.stop_atr * atr
                    tp_price = entry_price + params.take_profit_atr * atr
                    hold_bars = 0
                    trades += 1
        else:
            hold_bars += 1
            atr = float(prev["atr"]) if pd.notna(prev.get("atr")) else None

            stop_hit = stop_price is not None and float(bar["low"]) <= stop_price
            tp_hit = tp_price is not None and float(bar["high"]) >= tp_price

            indicator_exit = False
            if (
                pd.notna(prev.get("rsi"))
                and pd.notna(prev.get(fast_col))
                and pd.notna(prev.get(slow_col))
            ):
                indicator_exit = (
                    float(prev["rsi"]) >= params.rsi_exit
                    or float(prev["close"]) < float(prev[fast_col])
                )

            timed_exit = hold_bars >= params.max_hold_bars

            if stop_hit or tp_hit or indicator_exit or timed_exit:
                if stop_hit:
                    raw_exit = float(stop_price)
                elif tp_hit:
                    raw_exit = float(tp_price)
                else:
                    raw_exit = float(bar["open"])

                exec_exit = raw_exit * (1.0 - slippage)
                cash = qty * exec_exit * (1.0 - fee)
                if exec_exit > entry_price:
                    wins += 1
                qty = 0.0
                entry_price = 0.0
                stop_price = None
                tp_price = None
                hold_bars = 0

        equity = cash + (qty * float(bar["close"]))
        equity_curve.append(equity)

    if qty > 0:
        last_close = float(work.iloc[-1]["close"])
        cash = qty * last_close * (1.0 - fee)
        qty = 0.0
        equity_curve.append(cash)

    if not equity_curve:
        equity_curve = [1.0]

    equity_series = pd.Series(equity_curve, dtype=float)
    returns = equity_series.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    total_return = float(equity_series.iloc[-1] - 1.0)
    mdd = max_drawdown(equity_series)
    sharpe = 0.0
    if len(returns) > 2 and returns.std() and float(returns.std()) > 0:
        sharpe = float((returns.mean() / returns.std()) * annualization_factor(timeframe))

    score = (total_return * 100.0) + (sharpe * 2.0) + (mdd * 60.0) - (0.03 * trades)

    return {
        "score": float(score),
        "total_return": float(total_return),
        "max_drawdown": float(mdd),
        "sharpe": float(sharpe),
        "trades": int(trades),
        "win_rate": float((wins / trades) if trades else 0.0),
    }


def random_param(rng: random.Random) -> StrategyParams:
    ema_fast = rng.choice([7, 9, 12, 16, 20, 24])
    ema_slow = rng.choice([34, 50, 72, 100, 144, 200])
    if ema_fast >= ema_slow:
        ema_fast, ema_slow = min(ema_fast, ema_slow - 1), max(ema_slow, ema_fast + 1)
    return StrategyParams(
        rsi_length=rng.choice([7, 10, 14, 18, 21]),
        atr_length=rng.choice([7, 10, 14, 21]),
        ema_fast=max(3, ema_fast),
        ema_slow=max(ema_fast + 1, ema_slow),
        rsi_entry=rng.choice([24, 26, 28, 30, 32, 34, 36, 38, 40]),
        rsi_exit=rng.choice([52, 55, 58, 60, 62, 65, 68, 70, 72]),
        stop_atr=rng.choice([0.8, 1.0, 1.2, 1.5, 1.8, 2.2]),
        take_profit_atr=rng.choice([1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 3.5]),
        max_hold_bars=rng.choice([30, 60, 120, 240, 480, 720]),
    )


def refine_params(base: StrategyParams, rng: random.Random) -> StrategyParams:
    def jitter_int(v: int, min_v: int, max_v: int, step: int = 1) -> int:
        delta = rng.choice([-2, -1, 0, 1, 2]) * step
        return max(min_v, min(max_v, v + delta))

    def jitter_float(v: float, min_v: float, max_v: float, step: float) -> float:
        delta = rng.choice([-2, -1, 0, 1, 2]) * step
        x = max(min_v, min(max_v, v + delta))
        return round(x, 4)

    ema_fast = jitter_int(base.ema_fast, 3, 80)
    ema_slow = jitter_int(base.ema_slow, ema_fast + 1, 300)

    return StrategyParams(
        rsi_length=jitter_int(base.rsi_length, 5, 30),
        atr_length=jitter_int(base.atr_length, 5, 30),
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_entry=jitter_float(base.rsi_entry, 18, 45, 1.0),
        rsi_exit=jitter_float(base.rsi_exit, 50, 85, 1.0),
        stop_atr=jitter_float(base.stop_atr, 0.5, 4.0, 0.1),
        take_profit_atr=jitter_float(base.take_profit_atr, 0.8, 6.0, 0.1),
        max_hold_bars=jitter_int(base.max_hold_bars, 10, 2000, 10),
    )


def evaluate_candidates(df_train: pd.DataFrame, df_test: pd.DataFrame, timeframe: str, candidates: list[StrategyParams], fee_bps: float, slippage_bps: float) -> list[dict]:
    results: list[dict] = []
    for p in candidates:
        train = backtest(df_train, p, timeframe, fee_bps, slippage_bps)
        test = backtest(df_test, p, timeframe, fee_bps, slippage_bps)
        robust_score = (0.65 * train["score"]) + (0.35 * test["score"]) + (10.0 * min(test["win_rate"], train["win_rate"]))
        if train["trades"] < 3:
            robust_score -= (3 - train["trades"]) * 25.0
        if test["trades"] < 2:
            robust_score -= (2 - test["trades"]) * 25.0
        if train["trades"] == 0 and test["trades"] == 0:
            robust_score -= 1000.0
        results.append({
            "params": p,
            "train": train,
            "test": test,
            "robust_score": float(robust_score),
        })
    results.sort(key=lambda x: x["robust_score"], reverse=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune XRP backtest strategy on lowest timeframe.")
    parser.add_argument("--symbol", default="XRP/USDT")
    parser.add_argument("--venue", default="coinbase")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--db-path", default="mdtas.db")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--coarse-iters", type=int, default=220)
    parser.add_argument("--refine-iters", type=int, default=180)
    parser.add_argument("--fee-bps", type=float, default=6.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    candles = load_candles(db_path, args.symbol, args.venue, args.timeframe, args.lookback_days)
    split = max(int(len(candles) * 0.7), 200)
    df_train = candles.iloc[:split].reset_index(drop=True)
    df_test = candles.iloc[split:].reset_index(drop=True)

    if len(df_test) < 100:
        raise RuntimeError("Insufficient test set size after split. Need more data for robust tuning.")

    rng = random.Random(args.seed)

    coarse_candidates = [random_param(rng) for _ in range(args.coarse_iters)]
    coarse_results = evaluate_candidates(df_train, df_test, args.timeframe, coarse_candidates, args.fee_bps, args.slippage_bps)

    top_seed = coarse_results[:12]
    refine_candidates: list[StrategyParams] = []
    for item in top_seed:
        base = item["params"]
        for _ in range(max(1, args.refine_iters // len(top_seed))):
            refine_candidates.append(refine_params(base, rng))

    refine_results = evaluate_candidates(df_train, df_test, args.timeframe, refine_candidates, args.fee_bps, args.slippage_bps) if refine_candidates else []

    combined = sorted(coarse_results + refine_results, key=lambda x: x["robust_score"], reverse=True)
    best = combined[0]
    best_params: StrategyParams = best["params"]

    full_metrics = backtest(candles.reset_index(drop=True), best_params, args.timeframe, args.fee_bps, args.slippage_bps)

    now_iso = datetime.now(timezone.utc).isoformat()
    output_dir = Path("artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)

    tuned_yaml_path = output_dir / "xrp_tuned_engine_params.yaml"
    report_json_path = output_dir / "xrp_backtest_tuning_report.json"

    tuned_payload = {
        "generated_at_utc": now_iso,
        "symbol": args.symbol,
        "venue": args.venue,
        "timeframe": args.timeframe,
        "lookback_days": args.lookback_days,
        "optimizer": {
            "seed": args.seed,
            "coarse_iterations": args.coarse_iters,
            "refine_iterations": args.refine_iters,
            "objective": "robust_score = 0.65*train_score + 0.35*test_score + 10*min(train_win_rate,test_win_rate)",
        },
        "cost_model": {"fee_bps": args.fee_bps, "slippage_bps": args.slippage_bps},
        "xrp_strategy_params": {
            "rsi_length": best_params.rsi_length,
            "atr_length": best_params.atr_length,
            "ema_fast": best_params.ema_fast,
            "ema_slow": best_params.ema_slow,
            "rsi_entry": best_params.rsi_entry,
            "rsi_exit": best_params.rsi_exit,
            "stop_atr": best_params.stop_atr,
            "take_profit_atr": best_params.take_profit_atr,
            "max_hold_bars": best_params.max_hold_bars,
        },
        "performance": {
            "train": best["train"],
            "test": best["test"],
            "full": full_metrics,
        },
    }

    with tuned_yaml_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(tuned_payload, f, sort_keys=False)

    serializable_top = []
    for item in combined[:20]:
        p: StrategyParams = item["params"]
        serializable_top.append(
            {
                "robust_score": item["robust_score"],
                "params": p.__dict__,
                "train": item["train"],
                "test": item["test"],
            }
        )

    report_payload = {
        "generated_at_utc": now_iso,
        "symbol": args.symbol,
        "venue": args.venue,
        "timeframe": args.timeframe,
        "rows_used": len(candles),
        "train_rows": len(df_train),
        "test_rows": len(df_test),
        "best": {
            "robust_score": best["robust_score"],
            "params": best_params.__dict__,
            "train": best["train"],
            "test": best["test"],
            "full": full_metrics,
        },
        "top_20": serializable_top,
    }

    with report_json_path.open("w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print("Tuning complete")
    print(f"Rows used: {len(candles)} (train={len(df_train)}, test={len(df_test)})")
    print(f"Best robust score: {best['robust_score']:.4f}")
    print(f"Best params: {best_params.__dict__}")
    print(f"Full metrics: {full_metrics}")
    print(f"Saved params: {tuned_yaml_path}")
    print(f"Saved report: {report_json_path}")


if __name__ == "__main__":
    main()
