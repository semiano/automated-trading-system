from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from mdtas.ingestion.trade_aggregator import Candle


def _required_group_size(target_tf: Literal["5m", "1h"]) -> int:
    if target_tf == "5m":
        return 5
    return 60


def _is_aligned_close(ts_close_ms: int, target_tf: Literal["5m", "1h"]) -> bool:
    ts = datetime.fromtimestamp(ts_close_ms / 1000, tz=timezone.utc)
    if target_tf == "5m":
        return ts.second == 0 and ts.microsecond == 0 and (ts.minute % 5 == 0)
    return ts.second == 0 and ts.microsecond == 0 and ts.minute == 0


def rollup_candles(candles_1m: list[Candle], target_tf: Literal["5m", "1h"]) -> list[Candle]:
    if not candles_1m:
        return []

    by_symbol: dict[str, list[Candle]] = defaultdict(list)
    for row in candles_1m:
        if row.timeframe != "1m":
            continue
        by_symbol[row.symbol].append(row)

    out: list[Candle] = []
    required = _required_group_size(target_tf)
    minute_ms = 60_000

    for symbol, rows in by_symbol.items():
        ordered = sorted(rows, key=lambda item: item.ts_close)
        by_close = {item.ts_close: item for item in ordered}

        for item in ordered:
            if not _is_aligned_close(item.ts_close, target_tf):
                continue

            start_close = item.ts_close - ((required - 1) * minute_ms)
            closes = [start_close + (idx * minute_ms) for idx in range(required)]
            if any(close_ts not in by_close for close_ts in closes):
                continue

            group = [by_close[close_ts] for close_ts in closes]
            out.append(
                Candle(
                    symbol=symbol,
                    timeframe=target_tf,
                    ts_close=item.ts_close,
                    open=group[0].open,
                    high=max(row.high for row in group),
                    low=min(row.low for row in group),
                    close=group[-1].close,
                    volume=sum(row.volume for row in group),
                )
            )

    return sorted(out, key=lambda row: (row.symbol, row.ts_close, row.timeframe))