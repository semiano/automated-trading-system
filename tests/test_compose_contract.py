from __future__ import annotations

from datetime import UTC, datetime

from mdtas.api.schemas import CandleOut


def test_candle_contract_fields_exist() -> None:
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 123.4,
    }
    candle = CandleOut.model_validate(payload)
    assert candle.ts is not None
    assert candle.open > 0
    assert candle.high >= candle.low
    assert candle.volume >= 0
