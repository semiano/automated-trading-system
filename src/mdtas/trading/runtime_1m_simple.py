from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from mdtas.config import AppConfig, SimpleEngine1mParamsConfig
from mdtas.db.repo import CandleRepository
from mdtas.db.trading_repo import TradingRepository
from mdtas.indicators.engine import compute
from mdtas.trading.execution import (
    CcxtExecutionAdapter,
    PaperExecutionAdapter,
    SymbolExecutionConstraints,
    gap_aware_raw_exit_price,
)
from mdtas.trading.runtime import compute_entry_sizing, evaluate_entry_guards
from mdtas.utils.timeframes import timeframe_to_timedelta

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Simple1mParams:
    bb_length: int
    bb_stdev: float
    atr_length: int
    ema_fast: int
    ema_slow: int
    bb_entry_deviation: float
    bb_exit_deviation: float
    slope_lookback_bars: int
    slope_flatten_factor: float
    stop_atr: float
    take_profit_atr: float
    max_hold_bars: int

    def indicator_params(self) -> dict:
        return {
            "bollinger": {"length": self.bb_length, "stdev": self.bb_stdev},
            "atr": {"length": self.atr_length},
            "ema_lengths": [self.ema_fast, self.ema_slow],
        }


class Simple1mParamResolver:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self._tuned_symbol: str | None = None
        self._tuned_params: Simple1mParams | None = None
        self._tuned_path: Path | None = None
        self._tuned_mtime_ns: int | None = None
        self._refresh_tuned_if_needed()

    @staticmethod
    def _from_config(item: SimpleEngine1mParamsConfig) -> Simple1mParams:
        return Simple1mParams(
            bb_length=int(item.bb_length),
            bb_stdev=float(item.bb_stdev),
            atr_length=int(item.atr_length),
            ema_fast=int(item.ema_fast),
            ema_slow=int(item.ema_slow),
            bb_entry_deviation=float(item.bb_entry_deviation),
            bb_exit_deviation=float(item.bb_exit_deviation),
            slope_lookback_bars=int(item.slope_lookback_bars),
            slope_flatten_factor=float(item.slope_flatten_factor),
            stop_atr=float(item.stop_atr),
            take_profit_atr=float(item.take_profit_atr),
            max_hold_bars=int(item.max_hold_bars),
        )

    def _resolve_tuned_path(self) -> Path:
        path = Path(self.cfg.trading_1m.tuned_params_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    def _load_tuned_file(self, path: Path) -> None:
        if not path.exists():
            self._tuned_symbol = None
            self._tuned_params = None
            return

        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            tuned = payload.get("xrp_engine_v3_1m_params")
            symbol = payload.get("symbol")
            if isinstance(symbol, str) and isinstance(tuned, dict):
                self._tuned_symbol = symbol
                self._tuned_params = Simple1mParams(
                    bb_length=int(tuned.get("bb_length", 20)),
                    bb_stdev=float(tuned.get("bb_stdev", 2.0)),
                    atr_length=int(tuned.get("atr_length", 14)),
                    ema_fast=int(tuned.get("ema_fast", 20)),
                    ema_slow=int(tuned.get("ema_slow", 50)),
                    bb_entry_deviation=float(tuned.get("bb_entry_deviation", 1.05)),
                    bb_exit_deviation=float(tuned.get("bb_exit_deviation", 0.15)),
                    slope_lookback_bars=int(tuned.get("slope_lookback_bars", 3)),
                    slope_flatten_factor=float(tuned.get("slope_flatten_factor", 0.82)),
                    stop_atr=float(tuned.get("stop_atr", 1.4)),
                    take_profit_atr=float(tuned.get("take_profit_atr", 2.2)),
                    max_hold_bars=int(tuned.get("max_hold_bars", 60)),
                )
                logger.info("Loaded 1m tuned params for %s from %s", symbol, path)
            else:
                self._tuned_symbol = None
                self._tuned_params = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed loading 1m tuned params file: %s", exc)

    def _refresh_tuned_if_needed(self) -> None:
        path = self._resolve_tuned_path()
        try:
            mtime_ns = path.stat().st_mtime_ns
        except FileNotFoundError:
            mtime_ns = None

        if self._tuned_path == path and self._tuned_mtime_ns == mtime_ns:
            return

        self._tuned_path = path
        self._tuned_mtime_ns = mtime_ns
        self._load_tuned_file(path)

    def for_symbol(self, symbol: str) -> Simple1mParams:
        self._refresh_tuned_if_needed()
        if symbol in self.cfg.trading_1m.per_asset_params:
            return self._from_config(self.cfg.trading_1m.per_asset_params[symbol])
        if symbol == self._tuned_symbol and self._tuned_params is not None:
            return self._tuned_params
        return self._from_config(self.cfg.trading_1m.default_params)


class Simple1mRuntime:
    def __init__(self, cfg: AppConfig, candle_repo: CandleRepository, trading_repo: TradingRepository) -> None:
        self.cfg = cfg
        self.candle_repo = candle_repo
        self.trading_repo = trading_repo
        self.params_resolver = Simple1mParamResolver(cfg)
        self.execution = self._build_execution_adapter()

    def apply_config(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.params_resolver = Simple1mParamResolver(cfg)
        self.execution = self._build_execution_adapter()

    def _build_execution_adapter(self):
        cfg = self.cfg.trading_1m
        if cfg.execution_adapter != "real":
            return PaperExecutionAdapter(slippage_bps=cfg.slippage_bps)

        try:
            return CcxtExecutionAdapter(
                venue=self.cfg.providers.ccxt.venue,
                rate_limit=self.cfg.providers.ccxt.rate_limit,
                api_key=self.cfg.providers.ccxt.api_key,
                api_secret=self.cfg.providers.ccxt.api_secret,
                api_password=self.cfg.providers.ccxt.api_password,
                sandbox=self.cfg.providers.ccxt.sandbox,
                live_trading_enabled=cfg.live_trading_enabled,
                live_allow_short=cfg.live_allow_short,
                live_max_order_notional_usd=cfg.live_max_order_notional_usd,
                live_allowed_symbols=cfg.live_allowed_symbols,
                live_require_explicit_env_ack=cfg.live_require_explicit_env_ack,
                live_ack_env_var_name=cfg.live_ack_env_var_name,
                live_ack_env_var_value=cfg.live_ack_env_var_value,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("1m runtime real adapter failed; fallback to paper: %s", exc)
            return PaperExecutionAdapter(slippage_bps=cfg.slippage_bps)

    def _constraints_for_symbol(self, symbol: str) -> SymbolExecutionConstraints:
        cfg = self.cfg.trading_1m
        default_cfg = cfg.default_constraints
        item = cfg.per_asset_constraints.get(symbol, default_cfg)
        return SymbolExecutionConstraints(
            min_notional_usd=float(item.min_notional_usd),
            qty_step=float(item.qty_step),
            price_tick=float(item.price_tick) if item.price_tick is not None else None,
            fee_bps=float(item.fee_bps),
        )

    @staticmethod
    def _bb_deviation(row: pd.Series) -> float | None:
        close = row.get("close")
        bb_mid = row.get("bb_mid")
        bb_lower = row.get("bb_lower")
        bb_upper = row.get("bb_upper")
        if pd.isna(close) or pd.isna(bb_mid) or pd.isna(bb_lower) or pd.isna(bb_upper):
            return None
        half_width = (float(bb_upper) - float(bb_lower)) * 0.5
        if half_width <= 0:
            return None
        return (float(close) - float(bb_mid)) / half_width

    @staticmethod
    def _ema_slope(out: pd.DataFrame, index: int, col: str, lookback: int) -> tuple[float | None, float | None]:
        if index - 1 < 0 or index - lookback < 0:
            return None, None
        now = out.iloc[index - 1]
        prev = out.iloc[index - lookback]
        if pd.isna(now.get(col)) or pd.isna(prev.get(col)):
            return None, None
        latest = float(now[col]) - float(out.iloc[index - 2][col]) if index - 2 >= 0 and pd.notna(out.iloc[index - 2].get(col)) else None
        lookback_slope = (float(now[col]) - float(prev[col])) / float(lookback)
        return latest, lookback_slope

    def _emit_decision(self, symbol: str, timeframe: str, ts: datetime, decision: str, reasons: list[str]) -> None:
        logger.info(
            "decision_event %s",
            json.dumps(
                {
                    "engine": "simple_1m",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "ts": ts.isoformat(),
                    "decision": decision,
                    "reasons": reasons,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

    def evaluate_symbol(self, symbol: str, venue: str) -> None:
        cfg = self.cfg.trading_1m
        if not cfg.enabled:
            return

        timeframe = cfg.runtime_timeframe
        control = self.trading_repo.mark_asset_run(
            symbol=symbol,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            poll_delay_seconds=self.cfg.ingestion.poll_delay_seconds,
        )
        if not control.enabled:
            return

        params = self.params_resolver.for_symbol(symbol)
        frame = self.candle_repo.get_candles(
            symbol=symbol,
            timeframe=timeframe,
            venue=venue,
            start=None,
            end=None,
            limit=max(300, self.cfg.ingestion.warmup_bars),
            latest=True,
        )
        required_bars = max(params.ema_slow + 6, params.bb_length + 6, params.atr_length + 6, params.slope_lookback_bars + 6)
        if len(frame) < required_bars:
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="runtime1m_insufficient_bars",
                note=f"have={len(frame)}, need={required_bars}, timeframe={timeframe}",
                log_event=True,
            )
            return

        out = compute(
            frame,
            ["bbands", "atr", f"ema{params.ema_fast}", f"ema{params.ema_slow}"],
            params.indicator_params(),
        )
        if len(out) < params.slope_lookback_bars + 3:
            return

        i = len(out) - 1
        prev = out.iloc[i - 1]
        bar = out.iloc[i]
        ts = pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None)
        execution_mode = control.execution_mode
        trade_side_mode = control.trade_side

        open_position = self.trading_repo.get_open_position(symbol, venue, timeframe, execution_mode)
        constraints = self._constraints_for_symbol(symbol)

        bb_dev = self._bb_deviation(prev)
        if bb_dev is None or pd.isna(prev.get("atr")) or pd.isna(prev.get("close")):
            self._emit_decision(symbol, timeframe, ts, "hold", ["missing_indicators"])
            return

        ema_fast_col = f"ema{params.ema_fast}"
        ema_slow_col = f"ema{params.ema_slow}"
        slope_now, slope_lookback = self._ema_slope(out, i, ema_fast_col, max(2, params.slope_lookback_bars))
        if slope_now is None or slope_lookback is None:
            self._emit_decision(symbol, timeframe, ts, "hold", ["missing_ema_slope"])
            return

        flatten_ratio = abs(slope_now) / max(abs(slope_lookback), 1e-12)
        long_rounding = slope_now > slope_lookback and slope_now < 0 and flatten_ratio <= params.slope_flatten_factor
        short_rounding = slope_now < slope_lookback and slope_now > 0 and flatten_ratio <= params.slope_flatten_factor

        ema_fast = float(prev[ema_fast_col])
        ema_slow = float(prev[ema_slow_col])
        close = float(prev["close"])

        long_allowed = trade_side_mode in {"long_only", "long_short"}
        short_allowed = trade_side_mode in {"short_only", "long_short"}

        long_signal = long_allowed and bb_dev <= -params.bb_entry_deviation and ema_fast <= ema_slow and long_rounding and close <= ema_fast
        short_signal = short_allowed and bb_dev >= params.bb_entry_deviation and ema_fast >= ema_slow and short_rounding and close >= ema_fast

        if open_position is None:
            chosen_side: str | None = "long" if long_signal else ("short" if short_signal else None)
            if chosen_side is None:
                self._emit_decision(
                    symbol,
                    timeframe,
                    ts,
                    "hold",
                    [
                        f"bb_dev={bb_dev:.3f}",
                        f"ema_fast={ema_fast:.6f}",
                        f"ema_slow={ema_slow:.6f}",
                        f"slope_now={slope_now:.8f}",
                        f"slope_lookback={slope_lookback:.8f}",
                        f"flatten_ratio={flatten_ratio:.3f}",
                    ],
                )
                return

            last_exit = self.trading_repo.get_last_exit(
                symbol=symbol,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
            )
            hour_window_start = ts - timeframe_to_timedelta("1h")
            day_window_start = ts - timeframe_to_timedelta("1d")
            entries_last_hour = self.trading_repo.count_entries(symbol=symbol, since_ts=hour_window_start, venue=venue, timeframe=timeframe, execution_mode=execution_mode)
            entries_last_day = self.trading_repo.count_entries(symbol=symbol, since_ts=day_window_start, venue=venue, timeframe=timeframe, execution_mode=execution_mode)
            guard = evaluate_entry_guards(
                decision_ts=ts,
                timeframe=timeframe,
                last_exit_ts=last_exit.ts if last_exit else None,
                last_exit_reason=last_exit.reason if last_exit else None,
                cooldown_bars_after_exit=int(cfg.cooldown_bars_after_exit),
                cooldown_bars_after_stop=int(cfg.cooldown_bars_after_stop),
                entries_last_hour=entries_last_hour,
                entries_last_day=entries_last_day,
                max_entries_per_hour=int(cfg.max_entries_per_hour),
                max_entries_per_day=int(cfg.max_entries_per_day),
            )
            if guard.blocked_reason is not None:
                self._emit_decision(symbol, timeframe, ts, "hold", [guard.blocked_reason])
                return

            sizing = compute_entry_sizing(
                sizing_mode="fixed_notional",
                position_size_usd=float(cfg.position_size_usd),
                risk_per_trade_usd=0.0,
                max_position_notional_usd=cfg.max_position_notional_usd,
                raw_entry_price=float(bar["open"]),
                atr=float(prev["atr"]),
                stop_atr=float(params.stop_atr),
                qty_step=max(float(constraints.qty_step), 0.0001),
            )
            if sizing.qty_final <= 0:
                return

            entry_fill = self.execution.submit_entry(
                symbol=symbol,
                raw_price=float(bar["open"]),
                qty=float(sizing.qty_final),
                trade_side=chosen_side,
                constraints=constraints,
            )
            atr = float(prev["atr"])
            if chosen_side == "short":
                stop_price = float(entry_fill.price) + (params.stop_atr * atr)
                take_profit_price = float(entry_fill.price) - (params.take_profit_atr * atr)
            else:
                stop_price = float(entry_fill.price) - (params.stop_atr * atr)
                take_profit_price = float(entry_fill.price) + (params.take_profit_atr * atr)

            self.trading_repo.open_position(
                symbol=symbol,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
                trade_side=chosen_side,
                entry_ts=ts,
                entry_price=float(entry_fill.price),
                qty=float(entry_fill.qty),
                entry_fee=float(entry_fill.fee_usd),
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                last_price=float(bar["close"]),
            )
            self._emit_decision(symbol, timeframe, ts, "enter_long" if chosen_side == "long" else "enter_short", [f"bb_dev={bb_dev:.3f}", f"flatten_ratio={flatten_ratio:.3f}"])
            return

        hold_bars = int(open_position.hold_bars) + 1
        is_short = open_position.trade_side == "short"

        stop_hit = False
        tp_hit = False
        if is_short:
            stop_hit = open_position.stop_price is not None and float(bar["high"]) >= float(open_position.stop_price)
            tp_hit = open_position.take_profit_price is not None and float(bar["low"]) <= float(open_position.take_profit_price)
        else:
            stop_hit = open_position.stop_price is not None and float(bar["low"]) <= float(open_position.stop_price)
            tp_hit = open_position.take_profit_price is not None and float(bar["high"]) >= float(open_position.take_profit_price)

        signal_exit = False
        if hold_bars >= int(cfg.min_hold_bars_before_signal_exit):
            if is_short:
                signal_exit = bb_dev <= params.bb_exit_deviation or (close <= ema_fast and slope_now <= 0)
            else:
                signal_exit = bb_dev >= -params.bb_exit_deviation or (close >= ema_fast and slope_now >= 0)

        timed_exit = hold_bars >= int(params.max_hold_bars)

        if not (stop_hit or tp_hit or signal_exit or timed_exit):
            self.trading_repo.touch_position(open_position, hold_bars=hold_bars, last_price=float(bar["close"]))
            self._emit_decision(symbol, timeframe, ts, "hold", ["position_open"])
            return

        if stop_hit:
            raw_exit_price = float(open_position.stop_price)
            exit_reason = "stop"
        elif tp_hit:
            raw_exit_price = float(open_position.take_profit_price)
            exit_reason = "take_profit"
        elif signal_exit:
            raw_exit_price = float(bar["open"])
            exit_reason = "signal"
        else:
            raw_exit_price = float(bar["open"])
            exit_reason = "max_hold"

        exit_raw = gap_aware_raw_exit_price(
            trade_side=open_position.trade_side,
            reason=exit_reason,
            bar_open=float(bar["open"]),
            stop_price=float(open_position.stop_price) if open_position.stop_price is not None else None,
            take_profit_price=float(open_position.take_profit_price) if open_position.take_profit_price is not None else None,
        )
        exit_fill = self.execution.submit_exit(
            symbol=symbol,
            raw_price=float(exit_raw),
            qty=float(open_position.qty),
            trade_side=open_position.trade_side,
            constraints=constraints,
        )
        self.trading_repo.close_position(
            open_position,
            exit_ts=ts,
            exit_price=float(exit_fill.price),
            exit_reason=exit_reason,
            exit_fee=float(exit_fill.fee_usd),
        )
        self._emit_decision(symbol, timeframe, ts, "exit", [exit_reason])

