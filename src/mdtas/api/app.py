from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mdtas.api.routes_candles import router as candles_router
from mdtas.api.routes_features import router as features_router
from mdtas.api.routes_gaps import router as gaps_router
from mdtas.api.routes_health import router as health_router
from mdtas.api.routes_indicators import router as indicators_router
from mdtas.api.routes_trading import router as trading_router
from mdtas.db.session import init_db
from mdtas.logging import setup_logging

setup_logging()

app = FastAPI(title="market-data-ta-service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


app.include_router(health_router, prefix="/api/v1")
app.include_router(candles_router, prefix="/api/v1")
app.include_router(indicators_router, prefix="/api/v1")
app.include_router(features_router, prefix="/api/v1")
app.include_router(gaps_router, prefix="/api/v1")
app.include_router(trading_router, prefix="/api/v1")
