from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed


WS_URL = "wss://ws-feed.exchange.coinbase.com"
PRODUCT_ID = "XRP-USD"
CHANNEL = "matches"


@dataclass
class Trade:
    ts_ms: int
    price: float
    size: float


@dataclass
class OpenCandle:
    minute_open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def close_ms(self) -> int:
        return self.minute_open_ms + 59_999

    def ingest(self, trade: Trade) -> None:
        self.high = max(self.high, trade.price)
        self.low = min(self.low, trade.price)
        self.close = trade.price
        self.volume += trade.size


@dataclass
class ClosedCandle:
    minute_open_ms: int
    close_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    observed_ms: int

    @property
    def latency_seconds(self) -> float:
        return max(0.0, (self.observed_ms - self.close_ms) / 1000.0)


class Probe:
    def __init__(self, *, minutes: int, queue_size: int, ping_interval: int, ping_timeout: int) -> None:
        self.minutes = max(1, minutes)
        self.queue_size = max(100, queue_size)
        self.ping_interval = max(5, ping_interval)
        self.ping_timeout = max(5, ping_timeout)

        self.started_ms = int(time.time() * 1000)
        self.end_ms = self.started_ms + self.minutes * 60_000

        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.queue_size)
        self.stop_event = asyncio.Event()

        self.connection_attempts = 0
        self.reconnects = 0
        self.queue_overflow_drops = 0
        self.reader_errors = 0
        self.consumer_parse_errors = 0

        self.last_message_monotonic = time.monotonic()

        self.open_candle: OpenCandle | None = None
        self.closed_candles: dict[int, ClosedCandle] = {}

    @staticmethod
    def _to_iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()

    @staticmethod
    def _parse_coinbase_time_to_ms(raw: str) -> int | None:
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return None

    @staticmethod
    def _minute_open_ms(ts_ms: int) -> int:
        return (ts_ms // 60_000) * 60_000

    def _close_current_candle(self, observed_ms: int) -> None:
        if self.open_candle is None:
            return
        if self.open_candle.minute_open_ms in self.closed_candles:
            return

        closed = ClosedCandle(
            minute_open_ms=self.open_candle.minute_open_ms,
            close_ms=self.open_candle.close_ms,
            open=self.open_candle.open,
            high=self.open_candle.high,
            low=self.open_candle.low,
            close=self.open_candle.close,
            volume=self.open_candle.volume,
            observed_ms=observed_ms,
        )
        self.closed_candles[closed.minute_open_ms] = closed
        print(
            "[BAR]"
            f" close={self._to_iso(closed.close_ms)}"
            f" o={closed.open:.6f} h={closed.high:.6f}"
            f" l={closed.low:.6f} c={closed.close:.6f}"
            f" v={closed.volume:.2f}"
            f" latency={closed.latency_seconds:.3f}s"
        )

    def _ingest_trade(self, trade: Trade, observed_ms: int) -> None:
        minute_open = self._minute_open_ms(trade.ts_ms)

        if self.open_candle is None:
            self.open_candle = OpenCandle(
                minute_open_ms=minute_open,
                open=trade.price,
                high=trade.price,
                low=trade.price,
                close=trade.price,
                volume=trade.size,
            )
            return

        if minute_open == self.open_candle.minute_open_ms:
            self.open_candle.ingest(trade)
            return

        if minute_open > self.open_candle.minute_open_ms:
            self._close_current_candle(observed_ms=observed_ms)
            self.open_candle = OpenCandle(
                minute_open_ms=minute_open,
                open=trade.price,
                high=trade.price,
                low=trade.price,
                close=trade.price,
                volume=trade.size,
            )

    async def ws_reader(self) -> None:
        subscribe = {
            "type": "subscribe",
            "product_ids": [PRODUCT_ID],
            "channels": [CHANNEL],
        }

        backoff = 1.0
        first = True

        while not self.stop_event.is_set() and int(time.time() * 1000) < self.end_ms:
            if not first:
                self.reconnects += 1
            first = False
            self.connection_attempts += 1

            try:
                async with websockets.connect(
                    WS_URL,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    max_queue=1024,
                    close_timeout=5,
                ) as ws:
                    await ws.send(json.dumps(subscribe))
                    backoff = 1.0
                    self.last_message_monotonic = time.monotonic()
                    print(f"[OPEN] connected {datetime.now(UTC).isoformat()} attempt={self.connection_attempts}")

                    async for message in ws:
                        self.last_message_monotonic = time.monotonic()
                        if self.stop_event.is_set() or int(time.time() * 1000) >= self.end_ms:
                            break
                        try:
                            self.queue.put_nowait(message)
                        except asyncio.QueueFull:
                            self.queue_overflow_drops += 1
            except ConnectionClosed as exc:
                self.reader_errors += 1
                print(f"[CLOSE] code={exc.code} reason={exc.reason}")
            except Exception as exc:  # noqa: BLE001
                self.reader_errors += 1
                print(f"[ERROR] reader exception: {exc}")

            if self.stop_event.is_set() or int(time.time() * 1000) >= self.end_ms:
                break

            sleep_s = min(60.0, backoff) + random.uniform(0.0, 0.75)
            print(f"[RECONNECT] in {sleep_s:.2f}s")
            await asyncio.sleep(sleep_s)
            backoff = min(60.0, backoff * 2)

    async def trade_consumer(self) -> None:
        while not self.stop_event.is_set() or not self.queue.empty():
            if int(time.time() * 1000) >= self.end_ms and self.queue.empty():
                break

            try:
                message = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            now_ms = int(time.time() * 1000)
            try:
                payload: dict[str, Any] = json.loads(message)
                if payload.get("type") != "match":
                    continue
                if payload.get("product_id") != PRODUCT_ID:
                    continue

                ts_ms = self._parse_coinbase_time_to_ms(str(payload.get("time", "")))
                if ts_ms is None:
                    continue
                if ts_ms < self.started_ms - 120_000:
                    continue

                price = float(payload["price"])
                size = float(payload["size"])
                trade = Trade(ts_ms=ts_ms, price=price, size=size)
                self._ingest_trade(trade, observed_ms=now_ms)
            except Exception:
                self.consumer_parse_errors += 1
            finally:
                self.queue.task_done()

    async def watchdog(self) -> None:
        while not self.stop_event.is_set() and int(time.time() * 1000) < self.end_ms:
            idle = time.monotonic() - self.last_message_monotonic
            if idle > 90:
                print(f"[WATCHDOG] no messages for {idle:.1f}s")
            await asyncio.sleep(5)

    def _summary(self) -> int:
        bars = [self.closed_candles[key] for key in sorted(self.closed_candles)]
        latencies = [bar.latency_seconds for bar in bars]
        gaps = [bars[index + 1].close_ms - bars[index].close_ms for index in range(len(bars) - 1)]

        expected = max(1, self.minutes - 1)
        observed = len(bars)
        coverage = observed / expected

        print("\n[SUMMARY]")
        print(f"connection_attempts={self.connection_attempts}")
        print(f"reconnects={self.reconnects}")
        print(f"reader_errors={self.reader_errors}")
        print(f"consumer_parse_errors={self.consumer_parse_errors}")
        print(f"queue_overflow_drops={self.queue_overflow_drops}")
        print(f"bars_observed={observed}")
        print(f"bars_expected≈{expected}")
        print(f"coverage={coverage:.2%}")

        if bars:
            print(f"first_bar_close={self._to_iso(bars[0].close_ms)}")
            print(f"last_bar_close={self._to_iso(bars[-1].close_ms)}")
            print(f"max_latency_s={max(latencies):.3f}")
            print(f"avg_latency_s={statistics.fmean(latencies):.3f}")
            if len(latencies) >= 20:
                print(f"p95_latency_s={statistics.quantiles(latencies, n=20)[18]:.3f}")
            else:
                print(f"p95_latency_s={max(latencies):.3f}")

        if gaps:
            max_gap_s = max(gaps) / 1000.0
            avg_gap_s = statistics.fmean(gaps) / 1000.0
            print(f"max_interbar_gap_s={max_gap_s:.1f}")
            print(f"avg_interbar_gap_s={avg_gap_s:.1f}")
        else:
            max_gap_s = 0.0

        passed = (
            coverage >= 0.9
            and self.queue_overflow_drops == 0
            and self.reader_errors <= max(1, self.minutes // 3)
            and (not gaps or max_gap_s <= 90.0)
        )
        print("result=PASS" if passed else "result=FAIL")
        return 0 if passed else 2

    async def run(self) -> int:
        print(
            f"[START] minutes={self.minutes}"
            f" ws_url={WS_URL}"
            f" product={PRODUCT_ID}"
            f" channel={CHANNEL}"
            f" queue_size={self.queue_size}"
        )

        consumer_task = asyncio.create_task(self.trade_consumer())
        reader_task = asyncio.create_task(self.ws_reader())
        watchdog_task = asyncio.create_task(self.watchdog())

        while int(time.time() * 1000) < self.end_ms:
            await asyncio.sleep(1)

        self.stop_event.set()

        await asyncio.wait([reader_task], timeout=5)
        await self.queue.join()
        await asyncio.wait([consumer_task], timeout=5)

        watchdog_task.cancel()
        with contextlib.suppress(Exception):
            await watchdog_task

        return self._summary()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone XRP 1m websocket reliability probe")
    parser.add_argument("--minutes", type=int, default=10, help="How long to run")
    parser.add_argument("--queue-size", type=int, default=5000, help="Bounded queue size")
    parser.add_argument("--ping-interval", type=int, default=20, help="Websocket ping interval seconds")
    parser.add_argument("--ping-timeout", type=int, default=20, help="Websocket ping timeout seconds")
    return parser.parse_args()


async def _amain() -> int:
    args = parse_args()
    probe = Probe(
        minutes=args.minutes,
        queue_size=args.queue_size,
        ping_interval=args.ping_interval,
        ping_timeout=args.ping_timeout,
    )
    return await probe.run()


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
