from __future__ import annotations

import time

from mdtas.config import AppConfig
from mdtas.trading.runtime import AssetParamResolver, TradingRuntime


def _write_tuned_file(path, *, rsi_entry: float) -> None:
    path.write_text(
        "\n".join(
            [
                "symbol: XRP/USDT",
                "xrp_strategy_params:",
                "  rsi_length: 14",
                "  atr_length: 14",
                "  ema_fast: 20",
                "  ema_slow: 50",
                f"  rsi_entry: {rsi_entry}",
                "  rsi_exit: 65.0",
                "  stop_atr: 1.5",
                "  take_profit_atr: 2.5",
                "  max_hold_bars: 240",
            ]
        ),
        encoding="utf-8",
    )


def test_asset_param_resolver_reload_tuned_file_on_change(tmp_path):
    tuned_path = tmp_path / "tuned.yaml"
    _write_tuned_file(tuned_path, rsi_entry=31.0)

    cfg = AppConfig()
    cfg.trading.tuned_params_path = str(tuned_path)
    resolver = AssetParamResolver(cfg)

    before = resolver.for_symbol("XRP/USDT")
    assert before.rsi_entry == 31.0

    time.sleep(0.01)
    _write_tuned_file(tuned_path, rsi_entry=26.0)

    after = resolver.for_symbol("XRP/USDT")
    assert after.rsi_entry == 26.0


def test_runtime_apply_config_refreshes_runtime_state():
    cfg = AppConfig()
    cfg.trading.slippage_bps = 2.0
    runtime = TradingRuntime(cfg=cfg, candle_repo=None, trading_repo=None)  # type: ignore[arg-type]
    original_execution = runtime.execution

    updated = AppConfig()
    updated.trading.slippage_bps = 9.0
    runtime.apply_config(updated)

    assert runtime.cfg is updated
    assert runtime.params_resolver.cfg is updated
    assert runtime.execution is not original_execution