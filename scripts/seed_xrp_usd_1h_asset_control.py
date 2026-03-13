import os
from mdtas.db.session import SessionLocal
from mdtas.db.trading_repo import TradingRepository

SYMBOL = "XRP/USD"
TIMEFRAME = "1h"
DEFAULT_SOFT_RISK_LIMIT_USD = 1000.0
DEFAULT_EXECUTION_MODE = "sim"
DEFAULT_TRADE_SIDE = "long_short"
DEFAULT_ENABLED = True


session = SessionLocal()
repo = TradingRepository(session)

repo.get_or_create_asset_control(
    symbol=SYMBOL,
    timeframe=TIMEFRAME,
    default_soft_risk_limit_usd=DEFAULT_SOFT_RISK_LIMIT_USD,
    default_execution_mode=DEFAULT_EXECUTION_MODE,
    default_trade_side=DEFAULT_TRADE_SIDE,
    default_enabled=DEFAULT_ENABLED,
)
session.close()

print(f"Seeded asset control for {SYMBOL} {TIMEFRAME}")
