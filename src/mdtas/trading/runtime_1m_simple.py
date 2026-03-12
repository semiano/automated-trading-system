from __future__ import annotations

import json
import logging
import time
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
    min_hold_bars: int
    max_take_profit_pct: float

    def indicator_params(self) -> dict:
        return {
            "bollinger": {"length": self.bb_length, "stdev": self.bb_stdev},
            "atr": {"length": self.atr_length},
            "ema_lengths": [self.ema_fast, self.ema_slow],
        }


class Simple1mParamResolver:
    def __init__(self, cfg: AppConfig, trading_repo: TradingRepository | None = None) -> None:
        self.cfg = cfg
        self.trading_repo = trading_repo
        self._tuned_symbol: str | None = None
        self._tuned_params: Simple1mParams | None = None
        self._tuned_path: Path | None = None
        self._tuned_mtime_ns: int | None = None
        self._db_cache: dict[str, tuple[Simple1mParams, int]] = {}
        self._db_next_refresh_s: float = 0.0
        self._db_refresh_interval_s: float = 5.0
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
            min_hold_bars=int(item.min_hold_bars),
            max_take_profit_pct=float(item.max_take_profit_pct),
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
                    min_hold_bars=int(tuned.get("min_hold_bars", self.cfg.trading_1m.default_params.min_hold_bars)),
                    max_take_profit_pct=float(tuned.get("max_take_profit_pct", self.cfg.trading_1m.default_params.max_take_profit_pct)),
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
        now_s = time.monotonic()
        if self.trading_repo is not None and now_s >= self._db_next_refresh_s:
            latest = self.trading_repo.latest_asset_tuning_version(symbol=symbol, timeframe=self.cfg.trading_1m.runtime_timeframe)
            if latest is not None:
                tuned = latest.params_json or {}
                self._db_cache[symbol] = (
                    Simple1mParams(
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
                        min_hold_bars=int(tuned.get("min_hold_bars", self.cfg.trading_1m.default_params.min_hold_bars)),
                        max_take_profit_pct=float(
                            tuned.get("max_take_profit_pct", self.cfg.trading_1m.default_params.max_take_profit_pct)
                        ),
                    ),
                    int(latest.version),
                )
            self._db_next_refresh_s = now_s + self._db_refresh_interval_s

        if symbol in self._db_cache:
            return self._db_cache[symbol][0]

        self._refresh_tuned_if_needed()
        if symbol in self.cfg.trading_1m.per_asset_params:
            return self._from_config(self.cfg.trading_1m.per_asset_params[symbol])
        if symbol == self._tuned_symbol and self._tuned_params is not None:
            return self._tuned_params
        return self._from_config(self.cfg.trading_1m.default_params)

    def version_for_symbol(self, symbol: str) -> int | None:
        self.for_symbol(symbol)
        cached = self._db_cache.get(symbol)
        if cached is None:
            return None
        return int(cached[1])


class Simple1mRuntime:
    def __init__(self, cfg: AppConfig, candle_repo: CandleRepository, trading_repo: TradingRepository) -> None:
        self.cfg = cfg
        self.candle_repo = candle_repo
        self.trading_repo = trading_repo
        self.params_resolver = Simple1mParamResolver(cfg, trading_repo)
        self.execution = self._build_execution_adapter()

    def apply_config(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.params_resolver = Simple1mParamResolver(cfg, self.trading_repo)
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

    def _emit_decision(
        self,
        symbol: str,
        timeframe: str,
        ts: datetime,
        decision: str,
        reasons: list[str],
        tuning_version: int | None = None,
    ) -> None:
        effective_reasons = list(reasons)
        if tuning_version is not None:
            effective_reasons = [f"tuning_version=v{tuning_version}", *effective_reasons]

        first_reason = effective_reasons[0] if effective_reasons else "hold"
        if decision in {"enter_long", "enter_short"}:
            state = "position_opened"
        elif decision == "exit":
            state = "position_closed"
        elif first_reason == "position_open":
            state = "position_held"
        elif first_reason in {"missing_indicators", "missing_ema_slope"}:
            state = "signal_unavailable"
        elif first_reason in {"cooldown_active", "max_entries_per_hour", "max_entries_per_day"}:
            state = first_reason
        else:
            state = "no_entry_signal"

        self.trading_repo.set_asset_state(
            symbol=symbol,
            timeframe=timeframe,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            state=state,
            note=", ".join(effective_reasons)[:256] if effective_reasons else None,
            log_event=True,
        )

        logger.info(
            "decision_event %s",
            json.dumps(
                {
                    "engine": "simple_1m",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "ts": ts.isoformat(),
                    "decision": decision,
                    "reasons": effective_reasons,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

    def _htf_rsi_multiplier(self, *, symbol: str, venue: str, trade_side: str) -> float:
        cfg = self.cfg.trading_1m

        def _resolve_rsi(timeframe: str) -> float | None:
            frame = self.candle_repo.get_candles(
                symbol=symbol,
                timeframe=timeframe,
                venue=venue,
                start=None,
                end=None,
                limit=max(120, cfg.htf_rsi_length + 10),
                latest=True,
            )
            if len(frame) < cfg.htf_rsi_length + 2:
                return None
            out = compute(frame, ["rsi"], {"rsi": {"length": int(cfg.htf_rsi_length)}})
            if len(out) < 2:
                return None
            rsi_value = out.iloc[-2].get("rsi")
            if rsi_value is None or pd.isna(rsi_value):
                return None
            return float(rsi_value)

        try:
            rsi = _resolve_rsi(cfg.htf_rsi_timeframe)
            if rsi is None:
                rsi = _resolve_rsi(cfg.runtime_timeframe)
            if rsi is None:
                return 1.0
            if trade_side == "short":
                m = cfg.htf_rsi_sizing.short
                if rsi > 65:
                    return float(m.gt_65)
                if rsi >= 55:
                    return float(m.r55_65)
                if rsi >= 40:
                    return float(m.r40_55)
                if rsi >= 30:
                    return float(m.r30_40)
                return float(m.lt_30)

            m = cfg.htf_rsi_sizing.long
            if rsi < 35:
                return float(m.lt_35)
            if rsi < 45:
                return float(m.r35_45)
            if rsi < 60:
                return float(m.r45_60)
            if rsi <= 70:
                return float(m.r60_70)
            return float(m.gt_70)
        except Exception as exc:  # noqa: BLE001
            logger.debug("1m HTF RSI multiplier fallback to 1.0: %s", exc)
            return 1.0

    def evaluate_symbol(self, symbol: str, venue: str) -> None:
        cfg = self.cfg.trading_1m
        if not cfg.enabled:
            return

        timeframe = cfg.runtime_timeframe
        control = self.trading_repo.mark_asset_run(
            symbol=symbol,
            timeframe=timeframe,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            poll_delay_seconds=self.cfg.ingestion.poll_delay_seconds,
        )
        if not control.enabled:
            return

        params = self.params_resolver.for_symbol(symbol)
        tuning_version = self.params_resolver.version_for_symbol(symbol)
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
            timeframe=timeframe,
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
            self._emit_decision(symbol, timeframe, ts, "hold", ["missing_indicators"], tuning_version=tuning_version)
            return

        ema_fast_col = f"ema{params.ema_fast}"
        ema_slow_col = f"ema{params.ema_slow}"
        slope_now, slope_lookback = self._ema_slope(out, i, ema_fast_col, max(2, params.slope_lookback_bars))
        if slope_now is None or slope_lookback is None:
            self._emit_decision(symbol, timeframe, ts, "hold", ["missing_ema_slope"], tuning_version=tuning_version)
            return

        flatten_ratio = abs(slope_now) / max(abs(slope_lookback), 1e-12)

        ema_fast = float(prev[ema_fast_col])
        ema_slow = float(prev[ema_slow_col])
        close = float(prev["close"])

        long_allowed = trade_side_mode in {"long_only", "long_short"}
        short_allowed = trade_side_mode in {"short_only", "long_short"}

        long_signal = long_allowed and bb_dev <= -params.bb_entry_deviation and ema_fast <= ema_slow and close <= ema_fast
        short_signal = short_allowed and bb_dev >= params.bb_entry_deviation and ema_fast >= ema_slow and close >= ema_fast

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
                    tuning_version=tuning_version,
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
                self._emit_decision(symbol, timeframe, ts, "hold", [guard.blocked_reason], tuning_version=tuning_version)
                return

            sizing = compute_entry_sizing(
                sizing_mode="fixed_notional",
                position_size_usd=float(cfg.position_size_usd) * self._htf_rsi_multiplier(symbol=symbol, venue=venue, trade_side=chosen_side),
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
            raw_tp_distance = params.take_profit_atr * atr
            cap_distance = (params.max_take_profit_pct * float(entry_fill.price)) if params.max_take_profit_pct > 0 else raw_tp_distance
            tp_distance = min(raw_tp_distance, cap_distance)
            if chosen_side == "short":
                stop_price = float(entry_fill.price) + (params.stop_atr * atr)
                take_profit_price = float(entry_fill.price) - tp_distance
            else:
                stop_price = float(entry_fill.price) - (params.stop_atr * atr)
                take_profit_price = float(entry_fill.price) + tp_distance

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
            self._emit_decision(
                symbol,
                timeframe,
                ts,
                "enter_long" if chosen_side == "long" else "enter_short",
                [f"bb_dev={bb_dev:.3f}", f"flatten_ratio={flatten_ratio:.3f}"],
                tuning_version=tuning_version,
            )
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

        min_signal_hold = max(int(cfg.min_hold_bars_before_signal_exit), int(params.min_hold_bars), int(cfg.min_hold_bars))
        signal_exit = False
        if hold_bars >= min_signal_hold:
            if is_short:
                signal_exit = bb_dev <= params.bb_exit_deviation or (close <= ema_fast and slope_now <= 0)
            else:
                signal_exit = bb_dev >= -params.bb_exit_deviation or (close >= ema_fast and slope_now >= 0)

        timed_exit = hold_bars >= int(params.max_hold_bars)

        if not (stop_hit or tp_hit or signal_exit or timed_exit):
            self.trading_repo.touch_position(open_position, hold_bars=hold_bars, last_price=float(bar["close"]))
            self._emit_decision(symbol, timeframe, ts, "hold", ["position_open"], tuning_version=tuning_version)
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
            hold_bars_at_exit=hold_bars,
        )
        self._emit_decision(symbol, timeframe, ts, "exit", [exit_reason], tuning_version=tuning_version)

