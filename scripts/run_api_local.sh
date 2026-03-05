#!/usr/bin/env bash
set -euo pipefail

export MDTAS_CONFIG_PATH="${MDTAS_CONFIG_PATH:-config.yaml}"
export MDTAS_API_HOST="${MDTAS_API_HOST:-0.0.0.0}"
export MDTAS_API_PORT="${MDTAS_API_PORT:-8000}"

echo "API service started (MDTAS_CONFIG_PATH=${MDTAS_CONFIG_PATH}, DATABASE_URL=${DATABASE_URL:-unset})"
python -m services.api_main
