#!/usr/bin/env bash
set -euo pipefail

export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://localhost:8000/api/v1}"

echo "Web UI started (VITE_API_BASE_URL=${VITE_API_BASE_URL})"
npm --prefix web run dev -- --host 0.0.0.0 --port 5173
