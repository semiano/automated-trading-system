#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env.docker}"
SYMBOL="${SMOKE_SYMBOL:-BTC/USDT}"
TIMEFRAME="${SMOKE_TIMEFRAME:-5m}"
VENUE="${SMOKE_VENUE:-mock}"
API_BASE="${SMOKE_API_BASE:-http://localhost:8000/api/v1}"
BACKFILL_DAYS="${SMOKE_BACKFILL_DAYS:-2}"
HEALTH_TIMEOUT_SECONDS="${SMOKE_HEALTH_TIMEOUT_SECONDS:-180}"

export SYMBOL TIMEFRAME VENUE API_BASE BACKFILL_DAYS

COMPOSE_CMD=(docker compose --env-file "${ENV_FILE}")

log() {
  printf '[smoke] %s\n' "$*"
}

dump_diagnostics() {
  log "Diagnostic snapshot:"
  "${COMPOSE_CMD[@]}" ps || true
  "${COMPOSE_CMD[@]}" logs --tail=120 api postgres ingestion trader web || true
}

on_error() {
  local exit_code=$?
  log "Smoke test failed with exit code ${exit_code}."
  dump_diagnostics
  exit "${exit_code}"
}
trap on_error ERR

wait_for_service_health() {
  local service="$1"
  local timeout="$2"
  local start_ts
  start_ts="$(date +%s)"

  while true; do
    local container_id
    container_id="$("${COMPOSE_CMD[@]}" ps -q "${service}")"
    if [[ -n "${container_id}" ]]; then
      local status
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
      if [[ "${status}" == "healthy" || "${status}" == "running" ]]; then
        log "${service} status=${status}"
        return 0
      fi
      if [[ "${status}" == "unhealthy" || "${status}" == "exited" ]]; then
        log "${service} status=${status}"
        return 1
      fi
    fi

    local now_ts
    now_ts="$(date +%s)"
    if (( now_ts - start_ts > timeout )); then
      log "Timeout waiting for ${service} to be healthy/running."
      return 1
    fi
    sleep 2
  done
}

log "Starting compose stack with ${ENV_FILE}"
"${COMPOSE_CMD[@]}" up --build -d

wait_for_service_health postgres "${HEALTH_TIMEOUT_SECONDS}"
wait_for_service_health api "${HEALTH_TIMEOUT_SECONDS}"

log "Validating /health"
python - <<'PY'
import os
import urllib.request

api_base = os.environ["API_BASE"]
with urllib.request.urlopen(f"{api_base}/health", timeout=10) as response:
    if response.status != 200:
        raise SystemExit(f"health failed with status={response.status}")
print("[smoke] health endpoint ok")
PY

log "Triggering backfill for ${SYMBOL} ${TIMEFRAME} ${VENUE}"
python - <<'PY'
import json
import os
import urllib.request

api_base = os.environ["API_BASE"]
symbol = os.environ["SYMBOL"]
timeframe = os.environ["TIMEFRAME"]
venue = os.environ["VENUE"]
lookback_days = int(os.environ["BACKFILL_DAYS"])

payload = {
    "symbols": [symbol],
    "timeframes": [timeframe],
    "venue": venue,
    "lookback_days": lookback_days,
}
req = urllib.request.Request(
    f"{api_base}/backfill",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=60) as response:
    if response.status != 200:
        raise SystemExit(f"backfill failed with status={response.status}")
    body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, list):
        raise SystemExit("backfill response is not a list")
print("[smoke] backfill endpoint ok")
PY

log "Asserting non-empty candles/indicators/features responses"
python - <<'PY'
import json
import os
import urllib.parse
import urllib.request

api_base = os.environ["API_BASE"]
params = urllib.parse.urlencode(
    {
        "symbol": os.environ["SYMBOL"],
        "timeframe": os.environ["TIMEFRAME"],
        "venue": os.environ["VENUE"],
        "limit": 200,
    }
)


def load_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as response:
        if response.status != 200:
            raise SystemExit(f"request failed for {url} status={response.status}")
        return json.loads(response.read().decode("utf-8"))

candles = load_json(f"{api_base}/candles?{params}")
if not isinstance(candles, list) or len(candles) == 0:
    raise SystemExit("candles response is empty")
if not all(k in candles[0] for k in ["ts", "open", "high", "low", "close", "volume"]):
    raise SystemExit("candles response missing expected keys")

indicators = load_json(f"{api_base}/indicators?{params}&indicators=bbands,rsi,atr,ema20")
rows = indicators.get("rows") if isinstance(indicators, dict) else None
if not isinstance(rows, list) or len(rows) == 0:
    raise SystemExit("indicators response rows are empty")

features = load_json(f"{api_base}/features?{params}&indicators=bbands,rsi,atr,ema20,ema50")
f_rows = features.get("rows") if isinstance(features, dict) else None
if not isinstance(f_rows, list) or len(f_rows) == 0:
    raise SystemExit("features response rows are empty")

print("[smoke] response assertions ok")
PY

log "Smoke test passed ✅"
