from __future__ import annotations

from datetime import datetime, timezone

import ccxt

from mdtas.db.repo import CandleDTO
from mdtas.providers.base import MarketDataProvider
from mdtas.utils.timeframes import timeframe_to_timedelta


class CcxtProvider(MarketDataProvider):
    def __init__(self, venue: str = "binance", rate_limit: bool = True) -> None:
        venue_cls = getattr(ccxt, venue)
        self.exchange = venue_cls({"enableRateLimit": rate_limit})
        self.venue = venue

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_ts: datetime,
        end_ts: datetime,
        limit: int,
    ) -> list[CandleDTO]:
        tf_delta = timeframe_to_timedelta(timeframe)
        since_ms = int(start_ts.replace(tzinfo=timezone.utc).timestamp() * 1000)
        rows = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        out: list[CandleDTO] = []
        for row in rows:
            open_ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            close_ts = open_ts + tf_delta
            close_ts_naive = close_ts.replace(tzinfo=None)
            if close_ts_naive < start_ts or close_ts_naive > end_ts:
                continue
            out.append(
                CandleDTO(
                    symbol=symbol,
                    venue=self.venue,
                    timeframe=timeframe,
                    ts=close_ts_naive,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    ingested_at=datetime.utcnow(),
                )
            )

        uniq = {(c.ts, c.symbol, c.timeframe): c for c in out}
        return [uniq[key] for key in sorted(uniq.keys(), key=lambda k: k[0])]
