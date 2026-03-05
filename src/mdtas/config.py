from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class CcxtConfig(BaseModel):
    venue: str = "binance"
    rate_limit: bool = True
    api_key: str | None = Field(default_factory=lambda: os.getenv("EXCHANGE_API_KEY"))
    api_secret: str | None = Field(default_factory=lambda: os.getenv("EXCHANGE_API_SECRET"))
    api_password: str | None = Field(default_factory=lambda: os.getenv("EXCHANGE_API_PASSWORD"))
    sandbox: bool = Field(default_factory=lambda: os.getenv("EXCHANGE_SANDBOX", "true").lower() == "true")


class ProvidersConfig(BaseModel):
    default_provider: str = "mock"
    ccxt: CcxtConfig = Field(default_factory=CcxtConfig)


class IngestionConfig(BaseModel):
    warmup_bars: int = 2000
    warmup_bars_per_cycle_cap: int = 1000
    poll_delay_seconds: int = 5
    retries: int = 5
    backoff_seconds: int = 2
    allow_gap_jump_to_recent: bool = True
    max_catchup_bars_per_cycle: int = 1200


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


class StrategyParamsConfig(BaseModel):
    rsi_length: int = 14
    atr_length: int = 14
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_entry: float = 32.0
    rsi_exit: float = 65.0
    stop_atr: float = 1.5
    take_profit_atr: float = 2.5
    max_hold_bars: int = 240


class ExecutionConstraintsConfig(BaseModel):
    min_notional_usd: float = 0.0
    qty_step: float = 0.0
    price_tick: float | None = None
    fee_bps: float = 6.0


class TradingConfig(BaseModel):
    enabled: bool = True
    runtime_timeframe: str = "1m"
    execution_adapter: Literal["paper", "real"] = "paper"
    live_trading_enabled: bool = False
    live_allow_short: bool = False
    live_max_order_notional_usd: float = 25.0
    live_allowed_symbols: list[str] = Field(default_factory=list)
    live_require_explicit_env_ack: bool = True
    live_ack_env_var_name: str = "MDTAS_ENABLE_LIVE_TRADING"
    live_ack_env_var_value: str = "YES_I_ACKNOWLEDGE_LIVE_TRADING_RISK"
    position_size_usd: float = 100.0
    soft_portfolio_risk_limit_usd: float = 0.0
    risk_budget_policy: Literal["per_symbol", "portfolio"] = "per_symbol"
    portfolio_soft_risk_limit_usd: float = 0.0
    fee_bps: float = 6.0
    slippage_bps: float = 2.0
    tuned_params_path: str = "artifacts/xrp_tuned_engine_params_selected.yaml"
    default_params: StrategyParamsConfig = Field(default_factory=StrategyParamsConfig)
    per_asset_params: dict[str, StrategyParamsConfig] = Field(default_factory=dict)
    default_constraints: ExecutionConstraintsConfig = Field(default_factory=ExecutionConstraintsConfig)
    per_asset_constraints: dict[str, ExecutionConstraintsConfig] = Field(default_factory=dict)


class AppConfig(BaseModel):
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    timeframes: list[str] = Field(default_factory=lambda: ["1m", "5m", "1h"])
    cache_horizon_days: dict[str, int] = Field(
        default_factory=lambda: {"1m": 30, "5m": 180, "1h": 730, "1d": 3650}
    )
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)


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
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    db_path = os.getenv("MDTAS_DB_PATH", "./mdtas.db")
    return f"sqlite:///{db_path}"
