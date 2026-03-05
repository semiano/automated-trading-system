from __future__ import annotations

import json

from mdtas.providers.coinbase_ws_provider import CoinbaseWsTradeStream, to_coinbase_product_id


def test_to_coinbase_product_id():
    assert to_coinbase_product_id("XRP/USDT") == "XRP-USDT"
    assert to_coinbase_product_id("HBAR/USDT") == "HBAR-USDT"


def test_parse_match_message_to_trade():
    stream = CoinbaseWsTradeStream(symbols=["XRP/USDT", "HBAR/USDT"])
    message = json.dumps(
        {
            "type": "match",
            "product_id": "XRP-USDT",
            "price": "1.2345",
            "size": "100.5",
            "time": "2026-03-05T15:10:11.123456Z",
        }
    )

    trade = stream._parse_message(message)
    assert trade is not None
    assert trade.symbol == "XRP/USDT"
    assert trade.price == 1.2345
    assert trade.size == 100.5
    assert trade.ts > 0


def test_parse_non_match_message_ignored():
    stream = CoinbaseWsTradeStream(symbols=["XRP/USDT"])
    message = json.dumps({"type": "subscriptions", "channels": []})
    assert stream._parse_message(message) is None