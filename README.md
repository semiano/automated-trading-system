# market-data-ta-service

Production-leaning market data service for candle ingestion, local caching, deterministic technical indicators, and trading-style chart visualization.

## Scope

- Implements: data fetching, cache, dedupe, gap detection/repair, TA APIs, React trading UI, simulated runtime position lifecycle.
- Does **not** implement: real exchange order execution.

## Reasonable defaults used

- Default provider is `mock` in `config.yaml` so the stack runs without keys.
- Default venue in mock mode is `mock`; in ccxt mode it uses `providers.ccxt.venue` (`binance` default).
- API allows `1d` timeframe validation even if not present in default `timeframes` list.
- Worker recomputes indicator frames in-memory for warmup windows and serves indicators on-demand from `/indicators` and `/features`.
- Worker includes a simulated strategy runtime with asset-specific parameters and persistent open-position state in SQLite.
- Optional `indicator_series` table exists but is not enabled for write-through caching in MVP.

## Architecture

- Backend: FastAPI + SQLAlchemy + SQLite.
- Ingestion:
  - Backfill: paged fetch + upsert + gap detect + gap repair refetch.
  - Live updater: periodic polling of recent closed candles.
- Indicators: deterministic pandas/numpy pipeline.
- Frontend: React + TypeScript + Vite + `lightweight-charts`.

## Quickstart (mock mode)

### 1) Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

### 2) Seed mock candles

```bash
python scripts/seed_mock_data.py
```

### 3) Run API

```bash
bash scripts/run_api.sh
```

### 4) Run worker (separate shell)

```bash
bash scripts/run_worker.sh
```

### 5) Run web UI

```bash
cd web
npm install
bash ../scripts/run_web.sh
```

Open `http://localhost:5173`.

## Enable ccxt provider

1. Set in `config.yaml`:

```yaml
providers:
  default_provider: "ccxt"
  ccxt:
    venue: "binance"
    rate_limit: true
```

2. Optional keys in `.env` for exchanges requiring auth:

```env
EXCHANGE_API_KEY=...
EXCHANGE_API_SECRET=...
```

3. Restart API and worker.

## Cache horizons and warmup

- Configured by timeframe in `cache_horizon_days`.
- `ingestion.warmup_bars` controls how much history the worker reads during incremental recomputation context.

## API examples

```bash
curl "http://localhost:8000/api/v1/health"
curl "http://localhost:8000/api/v1/symbols"
curl "http://localhost:8000/api/v1/candles?symbol=BTC/USDT&timeframe=5m&venue=mock&limit=500"
curl "http://localhost:8000/api/v1/indicators?symbol=BTC/USDT&timeframe=5m&venue=mock&indicators=bbands,rsi,atr,ema20"
curl "http://localhost:8000/api/v1/features?symbol=BTC/USDT&timeframe=5m&venue=mock&indicators=bbands,rsi,atr,ema20,ema50,ema200"
curl "http://localhost:8000/api/v1/gaps?symbol=BTC/USDT&timeframe=5m&venue=mock"
curl "http://localhost:8000/api/v1/positions/open?venue=coinbase&timeframe=1m"
curl "http://localhost:8000/api/v1/trades/closed?venue=coinbase&timeframe=1m&limit=200"
curl "http://localhost:8000/api/v1/portfolio/risk-limit?venue=coinbase&timeframe=1m"
curl -X PUT "http://localhost:8000/api/v1/portfolio/risk-limit?venue=coinbase&timeframe=1m" -H "Content-Type: application/json" -d '{"soft_limit_usd":150}'
curl -X POST "http://localhost:8000/api/v1/backfill" -H "Content-Type: application/json" -d '{"symbols":["BTC/USDT"],"timeframes":["5m"],"lookback_days":7}'
```

## Indicator definitions

- Bollinger Bands:
  - `bb_mid`: SMA(length)
  - `bb_upper/lower`: SMA ± stdev * rolling std
  - Rolling std uses `ddof=0` (population standard deviation) for deterministic behavior.
  - Also outputs `bb_width` and `bb_percent_b`.
- RSI(14), ATR(14), EMA(20/50/200), rolling VWAP, Volume SMA(20).
- Closed-candle only semantics and warmup NaNs preserved.

## Volumetric candle approximation (MVP)

Given OHLCV-only data, true intrabar volume distribution is unavailable. Two approximations are implemented:

1. **Candle Volume Heat**: candle opacity scales by `volume / volume_sma(20)`.
2. **Visible-range Volume Profile**: bucket volume by candle typical price `(H+L+C)/3` into price bins.

Limitations: this is not tick-accurate volume-at-price.

## SQLite to Postgres/Timescale migration notes

- Keep SQLAlchemy models; swap engine URL in `MDTAS_DB_PATH`/config style to a Postgres DSN.
- Add alembic migrations for production schema evolution.
- For Timescale, convert `candles` to hypertable on `ts`, partition by symbol/timeframe if needed.
- Keep unique constraints for dedupe and add retention/compression policies.

## Tests

```bash
pytest
```
