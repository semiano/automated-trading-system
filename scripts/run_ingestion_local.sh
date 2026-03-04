#!/usr/bin/env bash
set -euo pipefail

export MDTAS_CONFIG_PATH="${MDTAS_CONFIG_PATH:-config.yaml}"

echo "Ingestion worker started (MDTAS_CONFIG_PATH=${MDTAS_CONFIG_PATH}, DATABASE_URL=${DATABASE_URL:-unset})"
python -m services.ingestion_main
