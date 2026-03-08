from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1"


def fetch_json(base_url: str, path: str, params: dict[str, str], api_key: str | None) -> object:
    query = urllib.parse.urlencode(params)
    url = f"{base_url}{path}?{query}" if query else f"{base_url}{path}"
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch VPS market data over authenticated API.")
    parser.add_argument("--base-url", default=os.getenv("MDTAS_API_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.getenv("MDTAS_API_READ_TOKEN"))
    parser.add_argument("--symbol", default="XRP/USD")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--venue", default="coinbase")
    parser.add_argument("--start", required=True, help="ISO timestamp, e.g. 2026-03-08T00:00:00Z")
    parser.add_argument("--end", required=True, help="ISO timestamp, e.g. 2026-03-08T06:00:00Z")
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--indicators", default="rsi,atr,bbands")
    parser.add_argument("--out-dir", default="artifacts")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    common = {
        "symbol": args.symbol,
        "venue": args.venue,
        "timeframe": args.timeframe,
        "start": args.start,
        "end": args.end,
        "limit": str(args.limit),
    }

    candles = fetch_json(args.base_url, "/candles", common, args.api_key)
    indicators = fetch_json(
        args.base_url,
        "/indicators",
        {
            **common,
            "indicators": args.indicators,
        },
        args.api_key,
    )
    gaps = fetch_json(args.base_url, "/gaps", {k: common[k] for k in ("symbol", "venue", "timeframe", "start", "end")}, args.api_key)

    slug = args.symbol.replace("/", "_")
    candles_path = out_dir / f"{slug}_{args.timeframe}_candles.json"
    indicators_path = out_dir / f"{slug}_{args.timeframe}_indicators.json"
    gaps_path = out_dir / f"{slug}_{args.timeframe}_gaps.json"

    candles_path.write_text(json.dumps(candles, indent=2), encoding="utf-8")
    indicators_path.write_text(json.dumps(indicators, indent=2), encoding="utf-8")
    gaps_path.write_text(json.dumps(gaps, indent=2), encoding="utf-8")

    candle_count = len(candles) if isinstance(candles, list) else 0
    indicator_rows = indicators.get("rows", []) if isinstance(indicators, dict) else []
    print(
        json.dumps(
            {
                "base_url": args.base_url,
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "candles": candle_count,
                "indicators": len(indicator_rows),
                "gaps": len(gaps) if isinstance(gaps, list) else 0,
                "out": {
                    "candles": str(candles_path),
                    "indicators": str(indicators_path),
                    "gaps": str(gaps_path),
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
