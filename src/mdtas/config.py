from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class CcxtConfig(BaseModel):
    venue: str = "binance"
    rate_limit: bool = True


class ProvidersConfig(BaseModel):
    default_provider: str = "mock"
    ccxt: CcxtConfig = Field(default_factory=CcxtConfig)


class IngestionConfig(BaseModel):
    warmup_bars: int = 2000
    poll_delay_seconds: int = 3
    retries: int = 5
    backoff_seconds: int = 2


class BollingerConfig(BaseModel):
    length: int = 20
    stdev: float = 2.0


class RsiConfig(BaseModel):
    length: int = 14


class AtrConfig(BaseModel):
    length: int = 14


class IndicatorConfig(BaseModel):
    bollinger: BollingerConfig = Field(default_factory=BollingerConfig)
    rsi: RsiConfig = Field(default_factory=RsiConfig)
    atr: AtrConfig = Field(default_factory=AtrConfig)
    ema_lengths: list[int] = Field(default_factory=lambda: [20, 50, 200])
    volume_sma: int = 20
    vwap_mode: str = "rolling"


class AppConfig(BaseModel):
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    timeframes: list[str] = Field(default_factory=lambda: ["1m", "5m", "1h"])
    cache_horizon_days: dict[str, int] = Field(
        default_factory=lambda: {"1m": 30, "5m": 180, "1h": 730, "1d": 3650}
    )
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    load_dotenv()
    config_path = Path(os.getenv("MDTAS_CONFIG_PATH", "config.yaml"))
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path

    default_obj = AppConfig().model_dump()
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            parsed = yaml.safe_load(handle) or {}
        merged = _deep_merge(default_obj, parsed)
    else:
        merged = default_obj

    return AppConfig(**merged)


def get_db_url() -> str:
    db_path = os.getenv("MDTAS_DB_PATH", "./mdtas.db")
    return f"sqlite:///{db_path}"
