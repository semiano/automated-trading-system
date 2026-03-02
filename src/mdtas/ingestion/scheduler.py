from __future__ import annotations

from mdtas.config import AppConfig
from mdtas.providers.base import MarketDataProvider
from mdtas.providers.ccxt_provider import CcxtProvider
from mdtas.providers.mock_provider import MockProvider


def build_provider(cfg: AppConfig) -> MarketDataProvider:
    provider_name = cfg.providers.default_provider.lower()
    if provider_name == "ccxt":
        return CcxtProvider(
            venue=cfg.providers.ccxt.venue,
            rate_limit=cfg.providers.ccxt.rate_limit,
        )
    return MockProvider()
