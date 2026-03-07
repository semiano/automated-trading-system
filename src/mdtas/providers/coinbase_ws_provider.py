from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import signal
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

import websockets
from websockets.exceptions import ConnectionClosed

from mdtas.ingestion.trade_aggregator import Trade

logger = logging.getLogger(__name__)


def to_coinbase_product_id(symbol: str) -> str:
    base, quote = symbol.split("/", 1)
    return f"{base}-{quote}"


class CoinbaseWsTradeStream:
    def __init__(
        self,
        *,
        symbols: list[str],
        reconnect_initial_backoff_seconds: int = 1,
        reconnect_max_backoff_seconds: int = 30,
        ws_url: str = "wss://advanced-trade-ws.coinbase.com",
        queue_maxsize: int = 5000,
        ping_interval_seconds: int = 20,
        ping_timeout_seconds: int = 20,
    ) -> None:
        self.symbols = list(symbols)
        self.product_ids = [to_coinbase_product_id(item) for item in symbols]
        self.symbol_by_product = {to_coinbase_product_id(item): item for item in symbols}
        self.reconnect_initial_backoff_seconds = max(1, int(reconnect_initial_backoff_seconds))
        self.reconnect_max_backoff_seconds = max(self.reconnect_initial_backoff_seconds, int(reconnect_max_backoff_seconds))
        self.ws_url = ws_url
        self.queue_maxsize = max(100, int(queue_maxsize))
        self.ping_interval_seconds = max(5, int(ping_interval_seconds))
        self.ping_timeout_seconds = max(5, int(ping_timeout_seconds))

        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _build_subscribe_payload(self) -> dict:
        if "advanced-trade-ws.coinbase.com" in self.ws_url:
            return {
                "type": "subscribe",
                "channel": "market_trades",
                "product_ids": self.product_ids,
            }
        return {
            "type": "subscribe",
            "product_ids": self.product_ids,
            "channels": ["matches"],
        }

    @staticmethod
    def _parse_ts_to_ms(raw: str) -> int | None:
        try:
            normalized = raw.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except Exception:  # noqa: BLE001
            return None

    def _parse_message(self, message: str) -> list[Trade]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return []

        out: list[Trade] = []

        if payload.get("type") == "match":
            product_id = payload.get("product_id")
            symbol = self.symbol_by_product.get(product_id)
            if symbol is None:
                return []

            ts_ms = self._parse_ts_to_ms(str(payload.get("time", "")))
            if ts_ms is None:
                return []

            try:
                price = float(payload["price"])
                size = float(payload["size"])
            except Exception:  # noqa: BLE001
                return []

            out.append(Trade(ts=ts_ms, price=price, size=size, symbol=symbol))
            return out

        events = payload.get("events")
        if not isinstance(events, list):
            return []

        for event in events:
            trades = event.get("trades") if isinstance(event, dict) else None
            if not isinstance(trades, list):
                continue
            for row in trades:
                if not isinstance(row, dict):
                    continue
                product_id = row.get("product_id")
                symbol = self.symbol_by_product.get(product_id)
                if symbol is None:
                    continue
                ts_ms = self._parse_ts_to_ms(str(row.get("time", "")))
                if ts_ms is None:
                    continue
                try:
                    price = float(row["price"])
                    size = float(row["size"])
                except Exception:  # noqa: BLE001
                    continue
                out.append(Trade(ts=ts_ms, price=price, size=size, symbol=symbol))

        return out

    async def _consumer_loop(
        self,
        queue: asyncio.Queue[str],
        on_trade_callback: Callable[[Trade], None],
        on_idle_callback: Callable[[], None] | None = None,
    ) -> None:
        while not self._stop_event.is_set() or not queue.empty():
            try:
                message = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if on_idle_callback is not None:
                    try:
                        on_idle_callback()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Coinbase WS idle callback error: %s", exc)
                continue

            try:
                trades = self._parse_message(message)
                for trade in trades:
                    on_trade_callback(trade)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Coinbase WS consumer error: %s", exc)
            finally:
                queue.task_done()

    async def _reader_loop(
        self,
        queue: asyncio.Queue[str],
        should_continue: Callable[[], bool],
    ) -> None:
        backoff_seconds = float(self.reconnect_initial_backoff_seconds)

        while should_continue() and not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=self.ping_interval_seconds,
                    ping_timeout=self.ping_timeout_seconds,
                    max_queue=1024,
                    close_timeout=5,
                ) as ws:
                    await ws.send(json.dumps(self._build_subscribe_payload()))
                    logger.info("Coinbase WS connected: products=%s", self.product_ids)
                    backoff_seconds = float(self.reconnect_initial_backoff_seconds)

                    async for message in ws:
                        if self._stop_event.is_set() or not should_continue():
                            break
                        try:
                            queue.put_nowait(message)
                        except asyncio.QueueFull:
                            logger.warning("Coinbase WS queue full; dropping message")

            except ConnectionClosed as exc:
                logger.warning("Coinbase WS closed: code=%s msg=%s", exc.code, exc.reason)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Coinbase WS error: %s", exc)

            if self._stop_event.is_set() or not should_continue():
                break

            sleep_s = min(float(self.reconnect_max_backoff_seconds), backoff_seconds) + random.uniform(0.0, 0.75)
            logger.info("Coinbase WS reconnect in %.2fs", sleep_s)
            await asyncio.sleep(sleep_s)
            backoff_seconds = min(float(self.reconnect_max_backoff_seconds), backoff_seconds * 2.0)

    async def _run_async(
        self,
        on_trade_callback: Callable[[Trade], None],
        should_continue: Callable[[], bool],
        on_idle_callback: Callable[[], None] | None = None,
    ) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.queue_maxsize)
        consumer_task = asyncio.create_task(self._consumer_loop(queue, on_trade_callback, on_idle_callback=on_idle_callback))
        reader_task = asyncio.create_task(self._reader_loop(queue, should_continue))

        await reader_task
        self._stop_event.set()
        await queue.join()
        consumer_task.cancel()
        with contextlib.suppress(Exception):
            await consumer_task

    def run(
        self,
        on_trade_callback: Callable[[Trade], None],
        should_continue: Callable[[], bool] | None = None,
        on_idle_callback: Callable[[], None] | None = None,
    ) -> None:
        if should_continue is None:
            should_continue = lambda: True

        def _handle_signal(_signum, _frame):  # type: ignore[no-untyped-def]
            self.stop()

        previous_sigterm = signal.getsignal(signal.SIGTERM)
        previous_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        try:
            asyncio.run(self._run_async(on_trade_callback, should_continue, on_idle_callback=on_idle_callback))
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
            signal.signal(signal.SIGINT, previous_sigint)