# VPS API Access For GHCP Sessions

This guide describes a safer way to fetch VPS market data directly over HTTP, without shelling into the server.

It also includes an authenticated SQL admin endpoint for direct DB queries/mutations when explicitly enabled.

## Scope Model

The API supports two scopes via `X-API-Key`:

- `read`:
  - `/api/v1/symbols`
  - `/api/v1/candles`
  - `/api/v1/indicators`
  - `/api/v1/gaps`
  - `/api/v1/features` (GET)
  - `/api/v1/ingestion/catchup-status`
  - `/api/v1/positions/open`
  - `/api/v1/trades/closed`
- `write`:
  - Control-plane and mutation endpoints (asset controls, value balance, risk policy, backfill, reload status)
  - SQL admin endpoint: `/api/v1/admin/sql/execute` (guarded by dedicated enable flags)

`write` keys can also read.

If neither token env var is set, auth is effectively disabled for backward compatibility.

## Required Environment Variables

Set on VPS for the API container:

- `MDTAS_API_READ_TOKEN`
- `MDTAS_API_WRITE_TOKEN`

Set on VPS for the web container (frontend control-plane pages):

- `VITE_API_READ_TOKEN`
- `VITE_API_WRITE_TOKEN`

Example `.env.docker` entries:

```env
MDTAS_API_READ_TOKEN=replace-with-long-random-read-token
MDTAS_API_WRITE_TOKEN=replace-with-long-random-write-token
VITE_API_READ_TOKEN=replace-with-long-random-read-token
VITE_API_WRITE_TOKEN=replace-with-long-random-write-token
MDTAS_ENABLE_SQL_API=false
MDTAS_SQL_API_ALLOW_WRITE=false
```

## SQL Admin Endpoint

Endpoint:

- `POST /api/v1/admin/sql/execute`

Auth:

- Requires `write` token (`X-API-Key`).

Runtime safety flags:

- `MDTAS_ENABLE_SQL_API=true` is required to enable endpoint access.
- `MDTAS_SQL_API_ALLOW_WRITE=true` is additionally required for mutating statements (`insert/update/delete/ddl`).

Request payload:

```json
{
  "sql": "SELECT id, symbol, execution_mode FROM trades WHERE symbol = :symbol ORDER BY id DESC",
  "params": {"symbol": "XRP/USD"},
  "max_rows": 200
}
```

Notes:

- Single statement only (no multi-statement batches).
- Returns structured JSON with `statement_type`, `rowcount`, `rows`, `truncated`.

PowerShell helper (project custom tool-style function):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/invoke_vps_sql_api.ps1 `
  -Sql "SELECT execution_mode, COUNT(*) AS trades FROM trades GROUP BY execution_mode" `
  -MaxRows 100
```

## Local GHCP Usage

Set local env vars in your workstation shell:

```powershell
$env:MDTAS_API_BASE_URL = "http://<VPS_IP>:8000/api/v1"
$env:MDTAS_API_READ_TOKEN = "<read-token>"
```

Run the helper script:

```powershell
c:/Users/Steve/automated-trading-system/.venv/Scripts/python.exe scripts/report_vps_market_data_via_api.py `
  --symbol XRP/USD `
  --timeframe 1m `
  --start 2026-03-08T00:00:00Z `
  --end 2026-03-08T06:00:00Z `
  --out-dir artifacts
```

Output files:

- `artifacts/<symbol>_<tf>_candles.json`
- `artifacts/<symbol>_<tf>_indicators.json`
- `artifacts/<symbol>_<tf>_gaps.json`

## Security Notes

- Keep `write` token out of regular analysis scripts.
- Rotate tokens if shared accidentally.
- Prefer HTTPS + reverse proxy in front of `:8000` for internet-facing access.
- Optionally add network controls (firewall allowlist) on top of token auth.
