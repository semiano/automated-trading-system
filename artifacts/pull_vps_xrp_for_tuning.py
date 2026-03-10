from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOST = "167.71.91.185"
BASE = f"http://{HOST}:8000/api/v1/candles"
OUT_DB = Path("artifacts/vps_xrp_tuning.db")


def fetch(timeframe: str, days: int) -> list[dict]:
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    params = {
        "symbol": "XRP/USD",
        "timeframe": timeframe,
        "venue": "coinbase",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 200000,
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url)
    token = os.getenv("MDTAS_API_READ_TOKEN") or os.getenv("MDTAS_API_WRITE_TOKEN")
    if token:
        request.add_header("X-API-Key", token)
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode())


def main() -> None:
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DB.exists():
        OUT_DB.unlink()

    con = sqlite3.connect(str(OUT_DB))
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE candles (
            ts TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            symbol TEXT,
            venue TEXT,
            timeframe TEXT
        )
        """
    )

    rows_1m = fetch("1m", 45)
    rows_5m = fetch("5m", 180)
    rows_1h = fetch("1h", 180)

    for timeframe, rows in (("1m", rows_1m), ("5m", rows_5m), ("1h", rows_1h)):
        cur.executemany(
            "INSERT INTO candles (ts, open, high, low, close, volume, symbol, venue, timeframe) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row["ts"],
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row.get("volume", 0.0)),
                    "XRP/USD",
                    "coinbase",
                    timeframe,
                )
                for row in rows
            ],
        )
    con.commit()

    summary = {}
    for timeframe in ("1m", "5m", "1h"):
        count, min_ts, max_ts = cur.execute(
            "SELECT count(*), min(ts), max(ts) FROM candles WHERE timeframe=?",
            (timeframe,),
        ).fetchone()
        summary[timeframe] = {"count": count, "min_ts": min_ts, "max_ts": max_ts}
    con.close()

    report_path = Path("artifacts/vps_xrp_tuning_data_summary.json")
    report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
