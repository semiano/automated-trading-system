from __future__ import annotations

import json
import pathlib
import subprocess
import sys

PY = r"c:/Users/Steve/automated-trading-system/.venv/Scripts/python.exe"
TUNER = "scripts/tune_xrp_backtest.py"
DB = "artifacts/hbar_vps_tuning.db"
OUT_DIR = pathlib.Path("artifacts/hbar_retune_runs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEEDS = [11, 23, 37, 51, 73, 97]


def run_once(timeframe: str, seed: int) -> dict:
    cmd = [
        PY,
        TUNER,
        "--symbol",
        "HBAR/USD",
        "--venue",
        "coinbase",
        "--timeframe",
        timeframe,
        "--db-path",
        DB,
        "--lookback-days",
        "30",
        "--coarse-iters",
        "400",
        "--refine-iters",
        "320",
        "--seed",
        str(seed),
    ]
    print(f"RUN {timeframe} seed {seed}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise RuntimeError(f"tuning failed for {timeframe} seed {seed}")

    rep_src = pathlib.Path("artifacts/xrp_backtest_tuning_report.json")
    params_src = pathlib.Path("artifacts/xrp_tuned_engine_params.yaml")
    rep_dst = OUT_DIR / f"hbar_usd_{timeframe}_seed{seed}_report.json"
    params_dst = OUT_DIR / f"hbar_usd_{timeframe}_seed{seed}_params.yaml"
    rep_dst.write_text(rep_src.read_text(encoding="utf-8"), encoding="utf-8")
    params_dst.write_text(params_src.read_text(encoding="utf-8"), encoding="utf-8")

    rep = json.loads(rep_dst.read_text(encoding="utf-8"))
    best = rep["best"]
    return {
        "timeframe": timeframe,
        "seed": seed,
        "robust_score": float(best["robust_score"]),
        "train_trades": int(best["train"]["trades"]),
        "test_trades": int(best["test"]["trades"]),
        "full_return": float(best["full"]["total_return"]),
        "full_sharpe": float(best["full"]["sharpe"]),
        "params": best["params"],
        "report_path": str(rep_dst),
        "params_path": str(params_dst),
    }


def main() -> None:
    runs: list[dict] = []
    for timeframe in ["1m", "5m"]:
        for seed in SEEDS:
            runs.append(run_once(timeframe, seed))

    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(runs, indent=2), encoding="utf-8")

    selected: dict[str, dict] = {}
    for timeframe in ["1m", "5m"]:
        candidates = [r for r in runs if r["timeframe"] == timeframe and r["test_trades"] >= 2]
        if not candidates:
            candidates = [r for r in runs if r["timeframe"] == timeframe]
        candidates.sort(key=lambda r: (r["robust_score"], r["full_return"], r["full_sharpe"]), reverse=True)
        selected[timeframe] = candidates[0]

    selected_path = OUT_DIR / "selected.json"
    selected_path.write_text(json.dumps(selected, indent=2), encoding="utf-8")

    print("SELECTED")
    print(json.dumps(selected, indent=2))
    print(f"SUMMARY: {summary_path}")
    print(f"SELECTED_FILE: {selected_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        sys.exit(1)
