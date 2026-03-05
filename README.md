# market-data-ta-service

Production-leaning market data service for candle ingestion, local caching, deterministic technical indicators, and trading-style chart visualization.

## Scope

- Implements: data fetching, cache, dedupe, gap detection/repair, TA APIs, React trading UI, simulated runtime position lifecycle.
- Supports optional guarded real execution through a CCXT market-order adapter when explicitly enabled.

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

## Simulated execution model

- Runtime uses a paper execution adapter (no live order routing).
- Slippage is applied by trade action side (BUY increases price, SELL decreases price).
- Fees are applied on both entry and exit notional using configured `fee_bps` (or per-symbol constraint override).
- Stop-loss / take-profit exits are gap-aware:
  - If open gaps through the threshold, exit fills at bar open (worse outcome).
  - Otherwise, exit fills at the threshold level.
- Position sizing is rounded down by `qty_step`; entries below `min_notional_usd` are skipped.

## Guarded real execution mode (opt-in)

- Real execution is disabled by default via `trading.execution_adapter: "paper"`.
- To enable real orders, you must set all of the following:
  - `trading.execution_adapter: "real"`
  - `trading.live_trading_enabled: true`
  - env `EXCHANGE_API_KEY` and `EXCHANGE_API_SECRET`
  - env `MDTAS_ENABLE_LIVE_TRADING=YES_I_ACKNOWLEDGE_LIVE_TRADING_RISK`
- Safety controls:
  - `trading.live_max_order_notional_usd` hard caps per-order notional.
  - `trading.live_allowed_symbols` restricts tradable symbols.
  - `trading.live_allow_short` defaults to `false`.
  - `providers.ccxt.sandbox` supports testnet/sandbox mode where exchange supports it.

Example minimal real-mode block:

```yaml
providers:
  default_provider: "ccxt"
  ccxt:
    venue: "coinbase"
    sandbox: true

trading:
  execution_adapter: "real"
  live_trading_enabled: true
  live_allow_short: false
  live_max_order_notional_usd: 10.0
  live_allowed_symbols:
    - "XRP/USDT"
```

### Trading risk and constraints config

```yaml
trading:
  risk_budget_policy: "per_symbol" # or "portfolio"
  portfolio_soft_risk_limit_usd: 0.0 # 0 disables portfolio soft cap
  sizing_mode: "fixed_notional" # or "risk_per_trade"
  position_size_usd: 100.0 # used when sizing_mode=fixed_notional
  risk_per_trade_usd: 5.0 # used when sizing_mode=risk_per_trade
  max_position_notional_usd: null # optional hard cap for either sizing mode
  use_regime_filter: true
  htf_timeframe: "1h"
  regime_trend_ema_fast: 50
  regime_trend_ema_slow: 200
  chop_filter_mode: "bb_width" # none | bb_width | atr_pct
  chop_bb_length: 20
  chop_bb_stdev: 2.0
  chop_bb_width_min: 0.01
  chop_atr_pct_min: 0.003
  cooldown_bars_after_exit: 10
  cooldown_bars_after_stop: 30
  max_entries_per_hour: 6
  max_entries_per_day: 40
  timezone: "UTC"
  slippage_bps: 2.0
  default_constraints:
    min_notional_usd: 0.0
    qty_step: 0.0
    price_tick: null
    fee_bps: 6.0
  per_asset_constraints:
    XRP/USD:
      min_notional_usd: 10.0
      qty_step: 0.1
      price_tick: 0.0001
      fee_bps: 6.0
```

- `risk_budget_policy=per_symbol`: uses each asset control `soft_risk_limit_usd`.
- `risk_budget_policy=portfolio`: uses global `portfolio_soft_risk_limit_usd` across all open positions.
- Soft risk limits with value `0` are treated as disabled.
- `sizing_mode=fixed_notional`: sizes quantity from `position_size_usd / entry_price`.
- `sizing_mode=risk_per_trade`: sizes quantity from `risk_per_trade_usd / (stop_atr * atr)` and rounds by `qty_step`.
- `max_position_notional_usd` (if set) caps entry notional for both sizing modes.
- `use_regime_filter=true`: gates LTF entries with HTF trend/chop state; exits remain unmanaged by this gate.
- `htf_timeframe` defaults to `1h`; runtime uses only HTF bars with `ts <=` LTF decision bar (no lookahead).
- Cooldown and entry-frequency guardrails gate entries only:
  - `cooldown_bars_after_exit` for normal exits
  - `cooldown_bars_after_stop` for stop exits
  - `max_entries_per_hour` and `max_entries_per_day` rolling limits

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
bash scripts/run_api_local.sh
```

### 4) Run ingestion worker (separate shell)

```bash
bash scripts/run_ingestion_local.sh
```

### 5) Run trader worker (separate shell)

```bash
bash scripts/run_trader_local.sh
```

### 6) Run web UI

```bash
bash scripts/run_web_local.sh
```

Open `http://localhost:5173`.

### Standard local environment variables

```bash
export MDTAS_CONFIG_PATH=config.yaml
export DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/mdtas
export VITE_API_BASE_URL=http://localhost:8000/api/v1
```

If `DATABASE_URL` is not set, the backend falls back to `MDTAS_DB_PATH` (SQLite).

### Service split (backend)

- API service: `python -m services.api_main`
- Ingestion service: `python -m services.ingestion_main`
- Trader service: `python -m services.trader_main`

Schema initialization responsibility:

- API initializes DB schema on startup.
- Ingestion/trader do not initialize schema.
- Optional explicit init command: `python -m services.db_init_main`

### Windows deterministic startup (recommended)

Use PowerShell scripts that stop stale dev processes first, then start a single API, worker, and web server on fixed ports.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_dev_stack.ps1
```

To stop all dev services:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_dev_stack.ps1
```

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

## Docker Compose (local multi-container)

Quickstart:

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

For low-resource VPS mode (1 vCPU / 1GB RAM), use minimal profile:

```bash
cp .env.docker.example .env.docker
# set this in .env.docker
# MDTAS_CONFIG_FILE=./config.minimal.yaml
docker compose --env-file .env.docker up --build
```

Using wrapper scripts:

```bash
bash scripts/compose_up.sh
bash scripts/compose_logs.sh
bash scripts/compose_down.sh
```

Services:

- Postgres: `localhost:5432`
- API: `http://localhost:8000/api/v1/health`
- Web UI: `http://localhost:5173`

Seed mock data in the running compose stack:

```bash
docker compose --env-file .env.docker exec api python scripts/seed_mock_data.py
```

### Local confidence checklist

1. Bring up the stack:

```bash
docker compose --env-file .env.docker up --build -d
```

2. Run end-to-end smoke test:

```bash
bash scripts/smoke_test_compose.sh
```

Windows PowerShell equivalent:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_compose.ps1
```

3. Open UI: `http://localhost:5173`
4. Confirm candles render in the chart for the selected symbol/timeframe.

### 1GB VPS tuning notes

- Compose memory tuning is configured via `.env.docker` (`*_MEM_LIMIT` and `*_MEM_RESERVATION`).
- Enforcement depends on container runtime support; if unsupported, limits may be advisory only.
- Default low-RAM targets in `.env.docker`:
  - API: `256m` reservation / `384m` limit
  - Ingestion: `128m` reservation / `256m` limit
  - Trader: `128m` reservation / `256m` limit
  - Postgres: `256m` reservation / `384m` limit
  - Web (Vite dev): `128m` reservation / `256m` limit

Postgres conservative settings (set in compose command via `.env.docker`):

- `shared_buffers=128MB`
- `work_mem=4MB`
- `max_connections=20`

Python runtime memory controls:

- `ingestion.max_catchup_bars_per_cycle` prevents large catch-up fetches.
- `ingestion.warmup_bars_per_cycle_cap` caps warmup rows loaded into DataFrames per cycle.
- Default log level is `INFO` (`MDTAS_LOG_LEVEL`), with `DEBUG` optional when troubleshooting.

## Docker (standalone services)

Build images:

```bash
docker build -f docker/api.Dockerfile -t mdtas-api .
docker build -f docker/ingestion.Dockerfile -t mdtas-ingestion .
docker build -f docker/trader.Dockerfile -t mdtas-trader .
docker build -f docker/web.Dockerfile -t mdtas-web .
```

Run API:

```bash
docker run --rm -p 8000:8000 \
  -e MDTAS_CONFIG_PATH=/app/config.yaml \
  -e DATABASE_URL=postgresql+psycopg://user:password@host:5432/mdtas \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  mdtas-api
```

Run ingestion worker:

```bash
docker run --rm \
  -e MDTAS_CONFIG_PATH=/app/config.yaml \
  -e DATABASE_URL=postgresql+psycopg://user:password@host:5432/mdtas \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  mdtas-ingestion
```

Run trader worker:

```bash
docker run --rm \
  -e MDTAS_CONFIG_PATH=/app/config.yaml \
  -e DATABASE_URL=postgresql+psycopg://user:password@host:5432/mdtas \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  mdtas-trader
```

Run web UI:

```bash
docker run --rm -p 5173:5173 \
  -e VITE_API_BASE_URL=http://localhost:8000/api/v1 \
  mdtas-web
```

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

- Keep SQLAlchemy models; set `DATABASE_URL` to a Postgres DSN.
- Add alembic migrations for production schema evolution.
- For Timescale, convert `candles` to hypertable on `ts`, partition by symbol/timeframe if needed.
- Keep unique constraints for dedupe and add retention/compression policies.

## Tests

```bash
pytest
```
