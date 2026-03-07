# Scripts Reference

This folder contains local development, smoke test, VPS ops, replay analysis, and tuning utilities.

## Most Important Scripts

Use these first in day-to-day workflow.

- `start_dev_stack.ps1`
  - Starts API, worker, and web dev server on Windows.
  - Use when beginning local development quickly.

- `stop_dev_stack.ps1`
  - Stops API, worker, and web dev server processes on Windows.
  - Use when cleaning up local dev processes.

- `seed_mock_data.py`
  - Seeds local DB with mock candles.
  - Use before local UI/API testing if the DB is empty.

- `smoke_test_compose.ps1` / `smoke_test_compose.sh`
  - Basic end-to-end smoke checks for compose-based stack.
  - Use after infra or service wiring changes.

- `deploy_vps_engine_iteration_hotfix.ps1`
  - Canonical VPS hotfix deploy script for engine/backend plus web and config sync.
  - Use for most production hotfixes.

- `check_vps_trader_status.ps1`
  - Checks trader service state, config/env wiring, and recent logs.
  - Use after deploys and when trades are not firing as expected.

- `check_vps_ingestion_status.ps1`
  - Checks 1m catchup status and ingestion logs for key symbols.
  - Use when candles look stale or delayed.

- `check_vps_ingestion_ws_debug.ps1`
  - Deeper websocket/catchup diagnostics for ingestion.
  - Use when there are reconnects, queue pressure, or heartbeat synthesis concerns.

- `check_vps_xrp_bar_quality.ps1`
  - Validates XRP bar quality and freshness in the VPS database.
  - Use when investigating flat/irregular bar behavior.

- `report_vps_xrp_engine_replay.ps1`
  - Runs VPS replay and reports open/close behavior with theoretical PnL.
  - Use to evaluate behavior changes after strategy updates.

- `report_vps_xrp_engine_scenarios.ps1`
  - Compares strategy scenarios over VPS data.
  - Use for structured scenario testing before/after parameter changes.

## Local Runner Scripts

- `run_api_local.sh`, `run_ingestion_local.sh`, `run_trader_local.sh`, `run_web_local.sh`
  - Linux/macOS local service entrypoints.

- `run_api.sh`, `run_worker.sh`, `run_web.sh`
  - Generic service launch wrappers used in shell-based workflows.

## Compose Convenience Scripts

- `compose_up.sh`, `compose_down.sh`, `compose_logs.sh`
  - Lightweight wrappers around `docker compose` lifecycle commands.

## Tuning and Simulation Scripts

- `tune_xrp_backtest.py`
  - Backtest parameter tuning utility for XRP.

- `tune_xrp_engine_v2.py`
  - Engine v2-oriented tuning workflow.

- `live_ops_smoke.py`, `real_roundtrip_smoke.py`, `real_short_smoke.py`
  - Operational/probe scripts for specific runtime smoke scenarios.

## VPS Utility Scripts

- `sync_vps_exchange_env.ps1`
  - Syncs exchange credentials/settings to VPS env file.

- `backfill_vps_recent_candles.ps1`
  - Triggers/assists recent candle backfill on VPS.

- `deploy_vps_ingestion_ws_hotfix.ps1`
  - Targeted ingestion websocket provider hotfix deploy.
  - Use only for ingestion-only emergency patches.

- `deploy_vps_web_hotfix.ps1`
  - Targeted web-only hotfix deploy.
  - Use only for frontend-only emergency patches.

- `maint_flatten_project_root.ps1`
  - Maintenance helper to flatten an old nested project root layout.
  - Use only for one-time repository structure migration/cleanup tasks.

## Naming Standard

Use these prefixes for new scripts so purpose is obvious from filename:

- `deploy_`: Deploy or hotfix push to VPS/infrastructure.
- `check_`: Read-only diagnostics and health checks.
- `report_`: Replay, analytics, or comparative reporting.
- `run_`: Local/dev service launch helpers.
- `compose_`: Docker compose convenience wrappers.
- `smoke_test_`: End-to-end smoke validation.
- `tune_`: Parameter search and tuning workflows.
- `maint_`: One-off repository/operator maintenance actions.

Legacy compatibility scripts may exist temporarily, but new additions should follow this convention.

## Deprecation Policy

When replacing a script, use this lifecycle:

1. Add the new canonical script with standardized naming.
2. Keep the old filename as a compatibility shim that prints a deprecation warning and forwards execution.
3. Document both scripts in this README and mark the old one as deprecated.
4. Remove the deprecated shim after at least one release cycle or once all operator runbooks are updated.

Current deprecated shim:

- `flatten_project_root.ps1` -> forwards to `maint_flatten_project_root.ps1`.

## Maintenance Notes

- Prefer `deploy_vps_engine_iteration_hotfix.ps1` for normal hotfix deployments.
- Prefer `check_vps_ingestion_status.ps1` and escalate to `check_vps_ingestion_ws_debug.ps1` when needed.
- Keep this file updated when scripts are added/removed so operators have one reliable index.
