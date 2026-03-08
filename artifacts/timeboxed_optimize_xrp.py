from __future__ import annotations

import json
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import tune_xrp_engine_v2 as t  # noqa: E402

DB_PATH = ROOT / "artifacts" / "vps_xrp_tuning.db"
OUT_REPORT = ROOT / "artifacts" / "xrp_timeboxed_20m_tuning_report.json"
OUT_SELECTED = ROOT / "artifacts" / "xrp_tuned_engine_params_selected.yaml"
OUT_FULL = ROOT / "artifacts" / "xrp_tuned_engine_params.yaml"

TIMEBOX_SECONDS = 20 * 60
BATCH_SIZE = 240
SEED = 42
TARGET_TRADES_PER_DAY = 4.0


def robust_with_activity_score(entry: dict, span_days: float) -> float:
    full = entry["full"]
    robust = float(entry["robust_score"])
    total_return = float(full["total_return"])
    trades = float(full["trades"])
    trades_per_day = trades / span_days if span_days > 0 else 0.0

    score = robust
    score += max(min(total_return * 1500.0, 60.0), -120.0)
    score += min(trades_per_day, 12.0) * 3.0

    if total_return <= 0:
        score -= 160.0 + (abs(total_return) * 1200.0)
    if trades_per_day < TARGET_TRADES_PER_DAY:
        score -= (TARGET_TRADES_PER_DAY - trades_per_day) * 45.0
    if trades < 20:
        score -= (20.0 - trades) * 2.0

    return float(score)


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Missing input DB: {DB_PATH}")

    symbol = "XRP/USD"
    venue = "coinbase"
    ltf_name = "1m"
    htf_name = "1h"
    lookback_days = 45

    ltf = t.load_candles(DB_PATH, symbol, venue, ltf_name, lookback_days)
    htf = t.load_candles(DB_PATH, symbol, venue, htf_name, lookback_days * 4)

    split = max(int(len(ltf) * 0.7), 600)
    if split >= len(ltf) - 200:
        split = int(len(ltf) * 0.65)

    ltf_train = ltf.iloc[:split].reset_index(drop=True)
    ltf_test = ltf.iloc[split:].reset_index(drop=True)

    split_ts = pd.to_datetime(ltf.iloc[split]["ts"]).to_pydatetime().replace(tzinfo=None)
    htf_ts = pd.to_datetime(htf["ts"]).dt.tz_localize(None)
    htf_train = htf.loc[htf_ts < split_ts].reset_index(drop=True)
    htf_test = htf.loc[htf_ts >= split_ts].reset_index(drop=True)

    if len(ltf_train) < 800 or len(ltf_test) < 300:
        raise SystemExit(
            f"Insufficient rows for robust tuning train/test: train={len(ltf_train)} test={len(ltf_test)}"
        )

    span_days = max((pd.to_datetime(ltf.iloc[-1]["ts"]) - pd.to_datetime(ltf.iloc[0]["ts"])).total_seconds() / 86400.0, 1.0)

    rng = random.Random(SEED)
    start = time.time()
    best: dict | None = None
    all_top: list[dict] = []
    iterations = 0
    batches = 0

    while time.time() - start < TIMEBOX_SECONDS:
        candidates = [t.random_param(rng, force_momentum_swing=None, force_bb_mode=None) for _ in range(BATCH_SIZE)]
        eval_results = t.evaluate(
            ltf_train,
            ltf_test,
            htf_train,
            htf_test,
            candidates,
            ltf_name,
            fee_bps=0.0,
            slippage_bps=0.0,
        )

        for item in eval_results[:30]:
            cfg = t.AppConfig()
            full = t.backtest(
                ltf.reset_index(drop=True),
                htf.reset_index(drop=True),
                item["params"],
                cfg,
                ltf_name,
                fee_bps=0.0,
                slippage_bps=0.0,
            )
            enriched = {
                "params": item["params"],
                "train": item["train"],
                "test": item["test"],
                "full": full,
                "robust_score": float(item["robust_score"]),
            }
            enriched["activity_adjusted_score"] = robust_with_activity_score(enriched, span_days)

            if best is None or enriched["activity_adjusted_score"] > best["activity_adjusted_score"]:
                best = enriched

            all_top.append(enriched)

        iterations += BATCH_SIZE
        batches += 1

    if best is None:
        raise SystemExit("No optimization candidates evaluated")

    # Keep a compact leaderboard in report output.
    all_top_sorted = sorted(all_top, key=lambda x: x["activity_adjusted_score"], reverse=True)
    leaderboard = []
    for item in all_top_sorted[:25]:
        span = span_days if span_days > 0 else 1.0
        full_trades = float(item["full"]["trades"])
        leaderboard.append(
            {
                "activity_adjusted_score": float(item["activity_adjusted_score"]),
                "robust_score": float(item["robust_score"]),
                "full_trades_per_day": float(full_trades / span),
                "params": asdict(item["params"]),
                "train": item["train"],
                "test": item["test"],
                "full": item["full"],
            }
        )

    now = datetime.now(timezone.utc).isoformat()
    best_full_trades_per_day = float(best["full"]["trades"]) / span_days

    full_payload = {
        "generated_at_utc": now,
        "symbol": symbol,
        "venue": venue,
        "timeframe": ltf_name,
        "lookback_days": lookback_days,
        "optimizer": {
            "seed": SEED,
            "timebox_minutes": 20,
            "batch_size": BATCH_SIZE,
            "iterations_evaluated": iterations,
            "batches": batches,
            "objective": "activity_adjusted_score with positive-return and min-trade-frequency bias",
        },
        "cost_model": {"fee_bps": 0.0, "slippage_bps": 0.0},
        "xrp_strategy_params": asdict(best["params"]),
        "performance": {
            "train": best["train"],
            "test": best["test"],
            "full": best["full"],
            "full_trades_per_day": best_full_trades_per_day,
            "robust_score": float(best["robust_score"]),
            "activity_adjusted_score": float(best["activity_adjusted_score"]),
        },
    }

    selected_payload = {
        "generated_at_utc": now,
        "symbol": symbol,
        "venue": venue,
        "timeframe": ltf_name,
        "selection_basis": "timeboxed_20m_activity_adjusted_best",
        "source_summary": str(OUT_REPORT.relative_to(ROOT)),
        "cost_model": {"fee_bps": 0.0, "slippage_bps": 0.0},
        "xrp_strategy_params": asdict(best["params"]),
        "best_observed_metrics": {
            "robust_score": float(best["robust_score"]),
            "activity_adjusted_score": float(best["activity_adjusted_score"]),
            "full": best["full"],
            "full_trades_per_day": best_full_trades_per_day,
        },
    }

    report_payload = {
        "generated_at_utc": now,
        "dataset": {
            "db_path": str(DB_PATH.relative_to(ROOT)),
            "symbol": symbol,
            "venue": venue,
            "ltf": ltf_name,
            "htf": htf_name,
            "rows_ltf": len(ltf),
            "rows_htf": len(htf),
            "span_days": span_days,
            "split_train_rows": len(ltf_train),
            "split_test_rows": len(ltf_test),
        },
        "optimizer": full_payload["optimizer"],
        "best": {
            "activity_adjusted_score": float(best["activity_adjusted_score"]),
            "robust_score": float(best["robust_score"]),
            "full_trades_per_day": best_full_trades_per_day,
            "params": asdict(best["params"]),
            "train": best["train"],
            "test": best["test"],
            "full": best["full"],
        },
        "leaderboard_top_25": leaderboard,
    }

    OUT_REPORT.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    OUT_FULL.write_text(yaml.safe_dump(full_payload, sort_keys=False), encoding="utf-8")
    OUT_SELECTED.write_text(yaml.safe_dump(selected_payload, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
