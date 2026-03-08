# VPS API Access For GHCP Sessions

This guide describes a safer way to fetch VPS market data directly over HTTP, without shelling into the server.

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

`write` keys can also read.

If neither token env var is set, auth is effectively disabled for backward compatibility.

## Required Environment Variables

Set on VPS for the API container:

- `MDTAS_API_READ_TOKEN`
- `MDTAS_API_WRITE_TOKEN`

Example `.env.docker` entries:

```env
MDTAS_API_READ_TOKEN=replace-with-long-random-read-token
MDTAS_API_WRITE_TOKEN=replace-with-long-random-write-token
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
