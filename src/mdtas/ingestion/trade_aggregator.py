from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Trade:
    ts: int
    price: float
    size: float
    symbol: str


@dataclass(slots=True)
class Candle:
    symbol: str
    timeframe: str
    ts_close: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class _OpenCandle:
    minute_start_ms: int
    candle: Candle


def _minute_start_ms(ts_ms: int) -> int:
    return (int(ts_ms) // 60_000) * 60_000


class TradeToCandleAggregator:
    def __init__(self) -> None:
        self._open_by_symbol: dict[str, _OpenCandle] = {}

    @staticmethod
    def _new_candle(symbol: str, minute_start_ms: int, price: float, size: float) -> Candle:
        return Candle(
            symbol=symbol,
            timeframe="1m",
            ts_close=minute_start_ms + 60_000,
            open=float(price),
            high=float(price),
            low=float(price),
            close=float(price),
            volume=float(size),
        )

    def ingest_trade(self, trade: Trade) -> list[Candle]:
        minute_start = _minute_start_ms(trade.ts)
        emitted: list[Candle] = []
        opened = self._open_by_symbol.get(trade.symbol)

        if opened is None:
            self._open_by_symbol[trade.symbol] = _OpenCandle(
                minute_start_ms=minute_start,
                candle=self._new_candle(trade.symbol, minute_start, trade.price, trade.size),
            )
            return emitted

        if minute_start == opened.minute_start_ms:
            opened.candle.high = max(opened.candle.high, float(trade.price))
            opened.candle.low = min(opened.candle.low, float(trade.price))
            opened.candle.close = float(trade.price)
            opened.candle.volume += float(trade.size)
            return emitted

        if minute_start > opened.minute_start_ms:
            emitted.append(opened.candle)
            self._open_by_symbol[trade.symbol] = _OpenCandle(
                minute_start_ms=minute_start,
                candle=self._new_candle(trade.symbol, minute_start, trade.price, trade.size),
            )
            return emitted

        return emitted

    def flush(self, symbol: str | None = None) -> list[Candle]:
        if symbol is not None:
            opened = self._open_by_symbol.pop(symbol, None)
            return [opened.candle] if opened is not None else []

        out = [item.candle for item in self._open_by_symbol.values()]
        self._open_by_symbol.clear()
        return sorted(out, key=lambda row: (row.symbol, row.ts_close))