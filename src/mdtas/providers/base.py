from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from mdtas.db.repo import CandleDTO


class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_ts: datetime,
        end_ts: datetime,
        limit: int,
    ) -> list[CandleDTO]:
        raise NotImplementedError

    def supports_symbol(self, symbol: str) -> bool:
        return True
