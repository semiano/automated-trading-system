#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env.docker}"

echo "Starting compose stack with env file: ${ENV_FILE}"
docker compose --env-file "${ENV_FILE}" up --build
