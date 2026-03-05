from __future__ import annotations

import json
import logging
import signal
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from websocket import WebSocketApp

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
    ) -> None:
        self.symbols = list(symbols)
        self.product_ids = [to_coinbase_product_id(item) for item in symbols]
        self.symbol_by_product = {to_coinbase_product_id(item): item for item in symbols}
        self.reconnect_initial_backoff_seconds = max(1, int(reconnect_initial_backoff_seconds))
        self.reconnect_max_backoff_seconds = max(self.reconnect_initial_backoff_seconds, int(reconnect_max_backoff_seconds))
        self.ws_url = ws_url

        self._stop_event = threading.Event()
        self._app: WebSocketApp | None = None
        self._last_error: str | None = None

    def stop(self) -> None:
        self._stop_event.set()
        if self._app is not None:
            try:
                self._app.close()
            except Exception:  # noqa: BLE001
                pass

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

    def run(self, on_trade_callback: Callable[[Trade], None], should_continue: Callable[[], bool] | None = None) -> None:
        if should_continue is None:
            should_continue = lambda: True

        def _handle_signal(_signum, _frame):  # type: ignore[no-untyped-def]
            self.stop()

        previous_sigterm = signal.getsignal(signal.SIGTERM)
        previous_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        backoff_seconds = self.reconnect_initial_backoff_seconds
        try:
            while should_continue() and not self._stop_event.is_set():
                opened_event = threading.Event()

                def _on_open(ws):
                    subscriptions = []
                    if "advanced-trade-ws.coinbase.com" in self.ws_url:
                        subscriptions.append(
                            {
                                "type": "subscribe",
                                "channel": "market_trades",
                                "product_ids": self.product_ids,
                            }
                        )
                    else:
                        subscriptions.append(
                            {
                                "type": "subscribe",
                                "product_ids": self.product_ids,
                                "channels": ["matches"],
                            }
                        )
                    for item in subscriptions:
                        ws.send(json.dumps(item))
                    opened_event.set()
                    logger.info("Coinbase WS connected: products=%s", self.product_ids)

                def _on_message(_ws, message: str):
                    trades = self._parse_message(message)
                    for trade in trades:
                        on_trade_callback(trade)

                def _on_error(_ws, error):
                    self._last_error = str(error)
                    logger.warning("Coinbase WS error: %s", self._last_error)

                def _on_close(_ws, status_code, status_message):
                    logger.warning("Coinbase WS closed: code=%s msg=%s", status_code, status_message)

                self._app = WebSocketApp(
                    self.ws_url,
                    on_open=_on_open,
                    on_message=_on_message,
                    on_error=_on_error,
                    on_close=_on_close,
                )
                self._app.run_forever(ping_interval=0)

                if self._stop_event.is_set() or not should_continue():
                    break

                if opened_event.is_set():
                    backoff_seconds = self.reconnect_initial_backoff_seconds

                logger.info("Coinbase WS reconnect in %ss", backoff_seconds)
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, self.reconnect_max_backoff_seconds)
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
            signal.signal(signal.SIGINT, previous_sigint)