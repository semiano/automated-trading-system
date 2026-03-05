from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from mdtas.config import AppConfig, StrategyParamsConfig
from mdtas.db.repo import CandleRepository
from mdtas.db.trading_repo import TradingRepository
from mdtas.indicators.engine import compute
from mdtas.trading.execution import (
    CcxtExecutionAdapter,
    PaperExecutionAdapter,
    SymbolExecutionConstraints,
    gap_aware_raw_exit_price,
    round_down_to_step,
)
from mdtas.trading.regime import compute_htf_regime
from mdtas.utils.timeframes import timeframe_to_timedelta

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EntrySizingResult:
    qty_raw: float
    qty_final: float
    stop_distance: float | None
    sizing_reason: str | None


@dataclass(slots=True)
class EntryGuardResult:
    blocked_reason: str | None
    details: str


def evaluate_entry_guards(
    *,
    decision_ts: datetime,
    timeframe: str,
    last_exit_ts: datetime | None,
    last_exit_reason: str | None,
    cooldown_bars_after_exit: int,
    cooldown_bars_after_stop: int,
    entries_last_hour: int,
    entries_last_day: int,
    max_entries_per_hour: int,
    max_entries_per_day: int,
) -> EntryGuardResult:
    if last_exit_ts is not None:
        tf_delta = timeframe_to_timedelta(timeframe)
        elapsed = decision_ts - last_exit_ts
        bars_since_exit = int(elapsed // tf_delta) if elapsed.total_seconds() >= 0 else 0
        required_bars = int(cooldown_bars_after_stop) if (last_exit_reason == "stop") else int(cooldown_bars_after_exit)
        if bars_since_exit < required_bars:
            return EntryGuardResult(
                blocked_reason="cooldown_active",
                details=(
                    f"bars_since_exit={bars_since_exit}, required={required_bars}, "
                    f"last_exit_reason={last_exit_reason}, timeframe={timeframe}"
                ),
            )

    if max_entries_per_hour > 0 and entries_last_hour >= max_entries_per_hour:
        return EntryGuardResult(
            blocked_reason="max_entries_per_hour",
            details=f"entries_last_hour={entries_last_hour}, cap={max_entries_per_hour}",
        )

    if max_entries_per_day > 0 and entries_last_day >= max_entries_per_day:
        return EntryGuardResult(
            blocked_reason="max_entries_per_day",
            details=f"entries_last_day={entries_last_day}, cap={max_entries_per_day}",
        )

    return EntryGuardResult(blocked_reason=None, details="ok")


def compute_entry_sizing(
    *,
    sizing_mode: str,
    position_size_usd: float,
    risk_per_trade_usd: float,
    max_position_notional_usd: float | None,
    raw_entry_price: float,
    atr: float | None,
    stop_atr: float,
    qty_step: float,
) -> EntrySizingResult:
    if raw_entry_price <= 0 or not math.isfinite(raw_entry_price):
        return EntrySizingResult(qty_raw=0.0, qty_final=0.0, stop_distance=None, sizing_reason="invalid_entry_price")

    if sizing_mode == "risk_per_trade":
        if atr is None or not math.isfinite(float(atr)):
            return EntrySizingResult(qty_raw=0.0, qty_final=0.0, stop_distance=None, sizing_reason="invalid_atr")
        stop_distance = float(stop_atr) * float(atr)
        if stop_distance <= 0 or not math.isfinite(stop_distance):
            return EntrySizingResult(
                qty_raw=0.0,
                qty_final=0.0,
                stop_distance=stop_distance,
                sizing_reason="invalid_stop_distance",
            )

        qty_raw = max(float(risk_per_trade_usd), 0.0) / stop_distance
        if max_position_notional_usd is not None and max_position_notional_usd > 0:
            qty_cap = float(max_position_notional_usd) / float(raw_entry_price)
            qty_raw = min(qty_raw, qty_cap)

        qty_final = round_down_to_step(qty_raw, qty_step)
        if qty_final <= 0:
            return EntrySizingResult(
                qty_raw=qty_raw,
                qty_final=qty_final,
                stop_distance=stop_distance,
                sizing_reason="qty_rounded_to_zero",
            )
        return EntrySizingResult(qty_raw=qty_raw, qty_final=qty_final, stop_distance=stop_distance, sizing_reason=None)

    notional_budget = max(float(position_size_usd), 1.0)
    if max_position_notional_usd is not None and max_position_notional_usd > 0:
        notional_budget = min(notional_budget, float(max_position_notional_usd))
    qty_raw = notional_budget / float(raw_entry_price)
    qty_final = round_down_to_step(qty_raw, qty_step)
    if qty_final <= 0:
        return EntrySizingResult(qty_raw=qty_raw, qty_final=qty_final, stop_distance=None, sizing_reason="qty_rounded_to_zero")
    stop_distance = None
    if atr is not None and math.isfinite(float(atr)):
        stop_distance = float(stop_atr) * float(atr)
    return EntrySizingResult(qty_raw=qty_raw, qty_final=qty_final, stop_distance=stop_distance, sizing_reason=None)


@dataclass(slots=True)
class StrategyParams:
    rsi_length: int
    atr_length: int
    ema_fast: int
    ema_slow: int
    rsi_entry: float
    rsi_exit: float
    stop_atr: float
    take_profit_atr: float
    max_hold_bars: int

    def indicator_params(self) -> dict:
        return {
            "rsi": {"length": self.rsi_length},
            "atr": {"length": self.atr_length},
            "ema_lengths": [self.ema_fast, self.ema_slow],
        }


class AssetParamResolver:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self._tuned_symbol: str | None = None
        self._tuned_params: StrategyParams | None = None
        self._tuned_path: Path | None = None
        self._tuned_mtime_ns: int | None = None
        self._refresh_tuned_if_needed()

    def _from_config(self, item: StrategyParamsConfig) -> StrategyParams:
        return StrategyParams(
            rsi_length=int(item.rsi_length),
            atr_length=int(item.atr_length),
            ema_fast=int(item.ema_fast),
            ema_slow=int(item.ema_slow),
            rsi_entry=float(item.rsi_entry),
            rsi_exit=float(item.rsi_exit),
            stop_atr=float(item.stop_atr),
            take_profit_atr=float(item.take_profit_atr),
            max_hold_bars=int(item.max_hold_bars),
        )

    def _resolve_tuned_path(self) -> Path:
        path = Path(self.cfg.trading.tuned_params_path)
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
            tuned = payload.get("xrp_strategy_params")
            symbol = payload.get("symbol")
            if isinstance(tuned, dict) and isinstance(symbol, str):
                self._tuned_symbol = symbol
                self._tuned_params = StrategyParams(
                    rsi_length=int(tuned.get("rsi_length", 14)),
                    atr_length=int(tuned.get("atr_length", 14)),
                    ema_fast=int(tuned.get("ema_fast", 20)),
                    ema_slow=int(tuned.get("ema_slow", 50)),
                    rsi_entry=float(tuned.get("rsi_entry", 32.0)),
                    rsi_exit=float(tuned.get("rsi_exit", 65.0)),
                    stop_atr=float(tuned.get("stop_atr", 1.5)),
                    take_profit_atr=float(tuned.get("take_profit_atr", 2.5)),
                    max_hold_bars=int(tuned.get("max_hold_bars", 240)),
                )
                logger.info("Loaded tuned strategy params for %s from %s", symbol, path)
            else:
                self._tuned_symbol = None
                self._tuned_params = None
                logger.warning("Tuned params file missing expected keys: %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed loading tuned params file: %s", exc)

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

    def for_symbol(self, symbol: str) -> StrategyParams:
        self._refresh_tuned_if_needed()

        if symbol in self.cfg.trading.per_asset_params:
            return self._from_config(self.cfg.trading.per_asset_params[symbol])

        if self._tuned_symbol == symbol and self._tuned_params is not None:
            return self._tuned_params

        return self._from_config(self.cfg.trading.default_params)


class TradingRuntime:
    def __init__(self, cfg: AppConfig, candle_repo: CandleRepository, trading_repo: TradingRepository) -> None:
        self.cfg = cfg
        self.candle_repo = candle_repo
        self.trading_repo = trading_repo
        self.params_resolver = AssetParamResolver(cfg)
        self.execution = self._build_execution_adapter()

    def apply_config(self, cfg: AppConfig) -> None:
        old_adapter = self.cfg.trading.execution_adapter
        old_slippage = self.cfg.trading.slippage_bps
        old_provider = self.cfg.providers.default_provider
        old_ccxt_venue = self.cfg.providers.ccxt.venue
        old_ccxt_rate_limit = self.cfg.providers.ccxt.rate_limit
        old_ccxt_api_key = self.cfg.providers.ccxt.api_key
        old_ccxt_api_secret = self.cfg.providers.ccxt.api_secret
        old_ccxt_api_password = self.cfg.providers.ccxt.api_password
        old_ccxt_sandbox = self.cfg.providers.ccxt.sandbox
        old_live_enabled = self.cfg.trading.live_trading_enabled
        old_live_allow_short = self.cfg.trading.live_allow_short
        old_live_max_notional = self.cfg.trading.live_max_order_notional_usd
        old_live_symbols = tuple(self.cfg.trading.live_allowed_symbols)
        old_live_ack_required = self.cfg.trading.live_require_explicit_env_ack
        old_live_ack_name = self.cfg.trading.live_ack_env_var_name
        old_live_ack_value = self.cfg.trading.live_ack_env_var_value

        self.cfg = cfg
        self.params_resolver = AssetParamResolver(cfg)

        execution_changed = (
            old_adapter != cfg.trading.execution_adapter
            or old_slippage != cfg.trading.slippage_bps
            or old_provider != cfg.providers.default_provider
            or old_ccxt_venue != cfg.providers.ccxt.venue
            or old_ccxt_rate_limit != cfg.providers.ccxt.rate_limit
            or old_ccxt_api_key != cfg.providers.ccxt.api_key
            or old_ccxt_api_secret != cfg.providers.ccxt.api_secret
            or old_ccxt_api_password != cfg.providers.ccxt.api_password
            or old_ccxt_sandbox != cfg.providers.ccxt.sandbox
            or old_live_enabled != cfg.trading.live_trading_enabled
            or old_live_allow_short != cfg.trading.live_allow_short
            or old_live_max_notional != cfg.trading.live_max_order_notional_usd
            or old_live_symbols != tuple(cfg.trading.live_allowed_symbols)
            or old_live_ack_required != cfg.trading.live_require_explicit_env_ack
            or old_live_ack_name != cfg.trading.live_ack_env_var_name
            or old_live_ack_value != cfg.trading.live_ack_env_var_value
        )

        if execution_changed:
            self.execution = self._build_execution_adapter()
            logger.info("Trading runtime execution adapter refreshed after config reload")

    def _build_execution_adapter(self):
        if self.cfg.trading.execution_adapter != "real":
            return PaperExecutionAdapter(slippage_bps=self.cfg.trading.slippage_bps)

        try:
            adapter = CcxtExecutionAdapter(
                venue=self.cfg.providers.ccxt.venue,
                rate_limit=self.cfg.providers.ccxt.rate_limit,
                api_key=self.cfg.providers.ccxt.api_key,
                api_secret=self.cfg.providers.ccxt.api_secret,
                api_password=self.cfg.providers.ccxt.api_password,
                sandbox=self.cfg.providers.ccxt.sandbox,
                live_trading_enabled=self.cfg.trading.live_trading_enabled,
                live_allow_short=self.cfg.trading.live_allow_short,
                live_max_order_notional_usd=self.cfg.trading.live_max_order_notional_usd,
                live_allowed_symbols=self.cfg.trading.live_allowed_symbols,
                live_require_explicit_env_ack=self.cfg.trading.live_require_explicit_env_ack,
                live_ack_env_var_name=self.cfg.trading.live_ack_env_var_name,
                live_ack_env_var_value=self.cfg.trading.live_ack_env_var_value,
            )
            logger.warning(
                "REAL execution adapter enabled (venue=%s, sandbox=%s, max_notional=%.4f)",
                self.cfg.providers.ccxt.venue,
                self.cfg.providers.ccxt.sandbox,
                self.cfg.trading.live_max_order_notional_usd,
            )
            return adapter
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falling back to paper execution adapter: %s", exc)
            return PaperExecutionAdapter(slippage_bps=self.cfg.trading.slippage_bps)

    def is_symbol_enabled(self, symbol: str) -> bool:
        control = self.trading_repo.get_or_create_asset_control(
            symbol=symbol,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            default_execution_mode="sim",
            default_trade_side="long_only",
            default_enabled=True,
        )
        return bool(control.enabled)

    def _constraints_for_symbol(self, symbol: str) -> SymbolExecutionConstraints:
        default_cfg = self.cfg.trading.default_constraints
        cfg = self.cfg.trading.per_asset_constraints.get(symbol, default_cfg)
        return SymbolExecutionConstraints(
            min_notional_usd=float(cfg.min_notional_usd),
            qty_step=float(cfg.qty_step),
            price_tick=float(cfg.price_tick) if cfg.price_tick is not None else None,
            fee_bps=float(cfg.fee_bps),
        )

    def _emit_decision_log(
        self,
        *,
        symbol: str,
        timeframe: str,
        ts: datetime,
        decision: str,
        reasons: list[str],
        sizing_mode: str | None = None,
        risk_per_trade_usd: float | None = None,
        stop_distance: float | None = None,
        qty_raw: float | None = None,
        qty_final: float | None = None,
        notional: float | None = None,
        htf_timeframe: str | None = None,
        trend_state: str | None = None,
        chop_state: str | None = None,
        bb_width_norm: float | None = None,
        atr_pct: float | None = None,
    ) -> None:
        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": ts.isoformat(),
            "decision": decision,
            "reasons": reasons,
            "regime_label": None,
            "anomaly_flags": [],
            "rca_event_id": None,
            "sizing_mode": sizing_mode,
            "risk_per_trade_usd": risk_per_trade_usd,
            "stop_distance": stop_distance,
            "qty_raw": qty_raw,
            "qty_final": qty_final,
            "notional": notional,
            "htf_timeframe": htf_timeframe,
            "trend_state": trend_state,
            "chop_state": chop_state,
            "bb_width_norm": bb_width_norm,
            "atr_pct": atr_pct,
        }
        logger.info("decision_event %s", json.dumps(payload, separators=(",", ":"), sort_keys=True))

    @staticmethod
    def _select_htf_up_to(htf_df: pd.DataFrame, decision_ts: datetime) -> pd.DataFrame:
        if htf_df is None or len(htf_df) == 0:
            return htf_df.iloc[0:0]
        frame = htf_df.copy()
        ts_col = pd.to_datetime(frame["ts"]).dt.tz_localize(None)
        mask = ts_col <= decision_ts
        return frame.loc[mask].copy()

    def _current_risk_and_limit(self, *, symbol: str, venue: str, timeframe: str, execution_mode: str, per_symbol_limit: float) -> tuple[float, float]:
        policy = self.cfg.trading.risk_budget_policy
        if policy == "portfolio":
            current_risk = self.trading_repo.current_open_risk_usd(
                symbol=None,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
            )
            return float(current_risk), float(self.cfg.trading.portfolio_soft_risk_limit_usd)

        current_risk = self.trading_repo.current_open_risk_usd(
            symbol=symbol,
            venue=venue,
            timeframe=timeframe,
            execution_mode=execution_mode,
        )
        return float(current_risk), float(per_symbol_limit)

    def evaluate_symbol(self, symbol: str, venue: str) -> None:
        if not self.cfg.trading.enabled:
            return

        control = self.trading_repo.mark_asset_run(
            symbol=symbol,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            poll_delay_seconds=self.cfg.ingestion.poll_delay_seconds,
        )
        if not control.enabled:
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="paused",
                note="Asset is paused",
                log_event=False,
            )
            return

        timeframe = self.cfg.trading.runtime_timeframe
        execution_mode = control.execution_mode
        trade_side_mode = control.trade_side
        params = self.params_resolver.for_symbol(symbol)
        frame = self.candle_repo.get_candles(
            symbol=symbol,
            timeframe=timeframe,
            venue=venue,
            start=None,
            end=None,
            limit=max(400, self.cfg.ingestion.warmup_bars),
            latest=True,
        )
        bars_required_ema = params.ema_slow + 5
        bars_required_rsi = params.rsi_length + 5
        bars_required_atr = params.atr_length + 5
        required_bars = max(bars_required_ema, bars_required_rsi, bars_required_atr)
        available_bars = len(frame)
        if available_bars < required_bars:
            missing_bars = required_bars - available_bars
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="insufficient_bars",
                note=f"Need {required_bars} bars on {timeframe}; have {available_bars} (missing {missing_bars})",
                log_event=True,
            )
            logger.warning(
                "Skipping trading eval for %s due to insufficient bars (timeframe=%s, have=%d, need=%d, missing=%d, requirements={ema:%d,rsi:%d,atr:%d})",
                symbol,
                timeframe,
                available_bars,
                required_bars,
                missing_bars,
                bars_required_ema,
                bars_required_rsi,
                bars_required_atr,
            )
            self._emit_decision_log(
                symbol=symbol,
                timeframe=timeframe,
                ts=datetime.utcnow().replace(microsecond=0),
                decision="hold",
                reasons=[
                    "insufficient_bars",
                    f"have={available_bars}",
                    f"need={required_bars}",
                    f"missing={missing_bars}",
                ],
            )
            return

        latest_ts = pd.to_datetime(frame.iloc[-1]["ts"]).to_pydatetime().replace(tzinfo=None)
        max_stale_age = timeframe_to_timedelta(timeframe) * 3
        if datetime.utcnow().replace(microsecond=0) - latest_ts > max_stale_age:
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="stale_data",
                note=f"Latest candle ts={latest_ts.isoformat()}",
                log_event=True,
            )
            logger.warning(
                "Skipping trading eval for %s because candle data is stale (latest=%s)",
                symbol,
                latest_ts.isoformat(),
            )
            self._emit_decision_log(
                symbol=symbol,
                timeframe=timeframe,
                ts=latest_ts,
                decision="hold",
                reasons=["stale_data"],
            )
            return

        indicators = ["rsi", "atr", f"ema{params.ema_fast}", f"ema{params.ema_slow}"]
        indicator_params = params.indicator_params()
        bb_entry_mode = str(self.cfg.trading.bb_entry_mode)
        if bb_entry_mode != "off":
            indicators.append("bbands")
            indicator_params["bollinger"] = {
                "length": int(self.cfg.indicators.bollinger.length),
                "stdev": float(self.cfg.indicators.bollinger.stdev),
            }
        out = compute(frame, indicators, indicator_params)
        if len(out) < 2:
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="insufficient_signal_rows",
                note=f"indicator_rows={len(out)}",
                log_event=True,
            )
            self._emit_decision_log(
                symbol=symbol,
                timeframe=timeframe,
                ts=datetime.utcnow().replace(microsecond=0),
                decision="hold",
                reasons=["insufficient_signal_rows"],
            )
            return

        prev = out.iloc[-2]
        bar = out.iloc[-1]
        decision_ts = pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None)

        regime = {
            "trend_state": "neutral",
            "chop_state": "unknown",
            "bb_width_norm": None,
            "atr_pct": None,
        }
        htf_timeframe: str | None = None
        if self.cfg.trading.use_regime_filter:
            htf_timeframe = self.cfg.trading.htf_timeframe
            htf_frame = self.candle_repo.get_candles(
                symbol=symbol,
                timeframe=htf_timeframe,
                venue=venue,
                start=None,
                end=None,
                limit=max(500, self.cfg.ingestion.warmup_bars),
                latest=True,
            )
            aligned = self._select_htf_up_to(htf_frame, decision_ts)
            regime = compute_htf_regime(aligned, self.cfg)

        open_position = self.trading_repo.get_open_position(symbol, venue, timeframe, execution_mode)

        constraints = self._constraints_for_symbol(symbol)

        if open_position is None:
            long_allowed = trade_side_mode in {"long_only", "long_short"}
            short_allowed = trade_side_mode in {"short_only", "long_short"}

            long_ok, long_note = self._entry_diagnostics_long(prev, params, bb_entry_mode)
            short_ok, short_note = self._entry_diagnostics_short(prev, params, bb_entry_mode)

            chosen_side: str | None = None
            chosen_note = ""
            if long_allowed and long_ok:
                chosen_side = "long"
                chosen_note = long_note
            elif short_allowed and short_ok:
                chosen_side = "short"
                chosen_note = short_note

            if chosen_side is None:
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="no_entry_signal",
                    note=(
                        f"mode={trade_side_mode}; "
                        f"long[{long_note}] short[{short_note}]"
                    ),
                    log_event=True,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=[f"no_entry_mode={trade_side_mode}", long_note, short_note],
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                return

            if self.cfg.trading.use_regime_filter and regime.get("chop_state") == "chop":
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="chop_blocked",
                    note=(
                        f"htf={htf_timeframe}, trend={regime.get('trend_state')}, chop={regime.get('chop_state')}, "
                        f"bb_width_norm={regime.get('bb_width_norm')}, atr_pct={regime.get('atr_pct')}"
                    ),
                    log_event=True,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=["blocked_by_chop_filter"],
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                return

            if self.cfg.trading.use_regime_filter:
                trend_state = regime.get("trend_state")
                trend_ok = (chosen_side == "long" and trend_state == "bull") or (
                    chosen_side == "short" and trend_state == "bear"
                )
                if not trend_ok:
                    self.trading_repo.set_asset_state(
                        symbol=symbol,
                        default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                        state="regime_blocked",
                        note=(
                            f"htf={htf_timeframe}, side={chosen_side}, trend={regime.get('trend_state')}, "
                            f"chop={regime.get('chop_state')}, bb_width_norm={regime.get('bb_width_norm')}, atr_pct={regime.get('atr_pct')}"
                        ),
                        log_event=True,
                    )
                    self._emit_decision_log(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=decision_ts,
                        decision="hold",
                        reasons=["blocked_by_regime_trend"],
                        htf_timeframe=htf_timeframe,
                        trend_state=regime.get("trend_state"),
                        chop_state=regime.get("chop_state"),
                        bb_width_norm=regime.get("bb_width_norm"),
                        atr_pct=regime.get("atr_pct"),
                    )
                    return

            last_exit = self.trading_repo.get_last_exit(
                symbol=symbol,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
            )
            hour_window_start = decision_ts - timeframe_to_timedelta("1h")
            day_window_start = decision_ts - timeframe_to_timedelta("1d")
            entries_last_hour = self.trading_repo.count_entries(
                symbol=symbol,
                since_ts=hour_window_start,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
            )
            entries_last_day = self.trading_repo.count_entries(
                symbol=symbol,
                since_ts=day_window_start,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
            )
            guard = evaluate_entry_guards(
                decision_ts=decision_ts,
                timeframe=timeframe,
                last_exit_ts=last_exit.ts if last_exit is not None else None,
                last_exit_reason=last_exit.reason if last_exit is not None else None,
                cooldown_bars_after_exit=int(self.cfg.trading.cooldown_bars_after_exit),
                cooldown_bars_after_stop=int(self.cfg.trading.cooldown_bars_after_stop),
                entries_last_hour=entries_last_hour,
                entries_last_day=entries_last_day,
                max_entries_per_hour=int(self.cfg.trading.max_entries_per_hour),
                max_entries_per_day=int(self.cfg.trading.max_entries_per_day),
            )
            if guard.blocked_reason is not None:
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state=guard.blocked_reason,
                    note=guard.details,
                    log_event=True,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=[guard.blocked_reason],
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                return

            raw_entry_price = float(bar["open"])
            atr_for_sizing: float | None = None
            if pd.notna(prev.get("atr")):
                atr_for_sizing = float(prev["atr"])

            sizing_result = compute_entry_sizing(
                sizing_mode=self.cfg.trading.sizing_mode,
                position_size_usd=float(self.cfg.trading.position_size_usd),
                risk_per_trade_usd=float(self.cfg.trading.risk_per_trade_usd),
                max_position_notional_usd=self.cfg.trading.max_position_notional_usd,
                raw_entry_price=raw_entry_price,
                atr=atr_for_sizing,
                stop_atr=float(params.stop_atr),
                qty_step=float(constraints.qty_step),
            )
            qty = sizing_result.qty_final
            if sizing_result.sizing_reason is not None:
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="sizing_invalid",
                    note=(
                        f"mode={self.cfg.trading.sizing_mode}, reason={sizing_result.sizing_reason}, "
                        f"atr={atr_for_sizing}, stop_distance={sizing_result.stop_distance}, "
                        f"qty_raw={sizing_result.qty_raw:.8f}, qty_final={sizing_result.qty_final:.8f}"
                    ),
                    log_event=True,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=["sizing_invalid", f"reason={sizing_result.sizing_reason}"],
                    sizing_mode=self.cfg.trading.sizing_mode,
                    risk_per_trade_usd=float(self.cfg.trading.risk_per_trade_usd),
                    stop_distance=sizing_result.stop_distance,
                    qty_raw=sizing_result.qty_raw,
                    qty_final=sizing_result.qty_final,
                    notional=None,
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                return

            try:
                entry_fill = self.execution.submit_entry(
                    symbol=symbol,
                    raw_price=raw_entry_price,
                    qty=qty,
                    trade_side=chosen_side,
                    constraints=constraints,
                )
            except Exception as exc:  # noqa: BLE001
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="execution_failed",
                    note=f"entry_failed: {exc}",
                    log_event=True,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=["execution_failed", "entry_failed"],
                    sizing_mode=self.cfg.trading.sizing_mode,
                    risk_per_trade_usd=float(self.cfg.trading.risk_per_trade_usd),
                    stop_distance=sizing_result.stop_distance,
                    qty_raw=sizing_result.qty_raw,
                    qty_final=sizing_result.qty_final,
                    notional=None,
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                logger.exception("Execution adapter entry failed for %s: %s", symbol, exc)
                return

            entry_notional = float(entry_fill.price) * float(entry_fill.qty)
            max_position_notional = self.cfg.trading.max_position_notional_usd
            if max_position_notional is not None and max_position_notional > 0 and entry_notional > max_position_notional:
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="max_notional_blocked",
                    note=(
                        f"notional={entry_notional:.4f} > max_position_notional={max_position_notional:.4f}; "
                        f"mode={self.cfg.trading.sizing_mode}, qty_raw={sizing_result.qty_raw:.8f}, qty_final={entry_fill.qty:.8f}"
                    ),
                    log_event=True,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=["max_notional_blocked"],
                    sizing_mode=self.cfg.trading.sizing_mode,
                    risk_per_trade_usd=float(self.cfg.trading.risk_per_trade_usd),
                    stop_distance=sizing_result.stop_distance,
                    qty_raw=sizing_result.qty_raw,
                    qty_final=float(entry_fill.qty),
                    notional=entry_notional,
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                return

            if constraints.min_notional_usd > 0 and entry_notional < constraints.min_notional_usd:
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="min_notional_blocked",
                    note=(
                        f"notional={entry_notional:.4f} < min_notional={constraints.min_notional_usd:.4f}; "
                        f"mode={self.cfg.trading.sizing_mode}, qty_raw={sizing_result.qty_raw:.8f}, qty_final={entry_fill.qty:.8f}"
                    ),
                    log_event=True,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=["min_notional_blocked"],
                    sizing_mode=self.cfg.trading.sizing_mode,
                    risk_per_trade_usd=float(self.cfg.trading.risk_per_trade_usd),
                    stop_distance=sizing_result.stop_distance,
                    qty_raw=sizing_result.qty_raw,
                    qty_final=float(entry_fill.qty),
                    notional=entry_notional,
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                return

            atr = float(prev["atr"])
            if chosen_side == "short":
                stop_price = entry_fill.price + (params.stop_atr * atr)
                take_profit_price = entry_fill.price - (params.take_profit_atr * atr)
                projected_trade_risk = max(stop_price - entry_fill.price, 0.0) * entry_fill.qty + entry_fill.fee_usd
            else:
                stop_price = entry_fill.price - (params.stop_atr * atr)
                take_profit_price = entry_fill.price + (params.take_profit_atr * atr)
                projected_trade_risk = max(entry_fill.price - stop_price, 0.0) * entry_fill.qty + entry_fill.fee_usd

            current_risk, risk_limit = self._current_risk_and_limit(
                symbol=symbol,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
                per_symbol_limit=float(control.soft_risk_limit_usd),
            )
            if risk_limit > 0 and current_risk + projected_trade_risk > risk_limit:
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="risk_blocked",
                    note=f"current={current_risk:.4f}, projected={projected_trade_risk:.4f}, limit={risk_limit:.4f}",
                    log_event=True,
                )
                logger.warning(
                    "Soft risk limit blocked entry for %s: current_risk=%.4f projected_trade_risk=%.4f soft_limit=%.4f",
                    symbol,
                    current_risk,
                    projected_trade_risk,
                    risk_limit,
                )
                self._emit_decision_log(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=decision_ts,
                    decision="hold",
                    reasons=["risk_blocked"],
                    htf_timeframe=htf_timeframe,
                    trend_state=regime.get("trend_state"),
                    chop_state=regime.get("chop_state"),
                    bb_width_norm=regime.get("bb_width_norm"),
                    atr_pct=regime.get("atr_pct"),
                )
                return

            self.trading_repo.open_position(
                symbol=symbol,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
                trade_side=chosen_side,
                entry_ts=pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None),
                entry_price=entry_fill.price,
                qty=entry_fill.qty,
                entry_fee=entry_fill.fee_usd,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                last_price=float(bar["close"]),
            )
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="position_opened",
                note=(
                    f"mode={execution_mode}, side={chosen_side}, fill={entry_fill.price:.6f}, "
                    f"qty={entry_fill.qty:.6f}, fee={entry_fill.fee_usd:.6f}, notional={entry_notional:.6f}, "
                    f"sizing_mode={self.cfg.trading.sizing_mode}, risk_per_trade={self.cfg.trading.risk_per_trade_usd:.4f}, "
                    f"stop_distance={sizing_result.stop_distance}, qty_raw={sizing_result.qty_raw:.8f}; {chosen_note}"
                ),
                log_event=True,
            )
            logger.info(
                "Opened position %s %s mode=%s side=%s @ %.6f qty=%.6f",
                symbol,
                timeframe,
                execution_mode,
                chosen_side,
                entry_fill.price,
                entry_fill.qty,
            )
            self._emit_decision_log(
                symbol=symbol,
                timeframe=timeframe,
                ts=decision_ts,
                decision="enter_long" if chosen_side == "long" else "enter_short",
                reasons=[chosen_note],
                sizing_mode=self.cfg.trading.sizing_mode,
                risk_per_trade_usd=float(self.cfg.trading.risk_per_trade_usd),
                stop_distance=sizing_result.stop_distance,
                qty_raw=sizing_result.qty_raw,
                qty_final=float(entry_fill.qty),
                notional=entry_notional,
                htf_timeframe=htf_timeframe,
                trend_state=regime.get("trend_state"),
                chop_state=regime.get("chop_state"),
                bb_width_norm=regime.get("bb_width_norm"),
                atr_pct=regime.get("atr_pct"),
            )
            return

        self._manage_open_position(open_position, prev, bar, params, constraints)

    def _entry_diagnostics_long(self, prev: pd.Series, params: StrategyParams, bb_entry_mode: str) -> tuple[bool, str]:
        fast_col = f"ema{params.ema_fast}"
        missing: list[str] = []
        if pd.isna(prev.get("rsi")):
            missing.append("rsi")
        if pd.isna(prev.get("atr")):
            missing.append("atr")
        if pd.isna(prev.get(fast_col)):
            missing.append(fast_col)
        if pd.isna(prev.get("close")):
            missing.append("close")
        if bb_entry_mode != "off" and pd.isna(prev.get("bb_lower")):
            missing.append("bb_lower")
        if missing:
            return False, f"missing={','.join(missing)}"

        rsi = float(prev["rsi"])
        atr = float(prev["atr"])
        close = float(prev["close"])
        ema_fast = float(prev[fast_col])
        pass_rsi = rsi <= params.rsi_entry
        pass_trend = close > ema_fast
        pass_bb = True
        bb_note = "bb=off"
        if bb_entry_mode == "touch_revert":
            bb_lower = float(prev["bb_lower"])
            pass_bb = close <= bb_lower
            bb_note = f", close={close:.6f}<=bb_lower={bb_lower:.6f}({pass_bb})"
        note = (
            f"long: rsi={rsi:.2f}<={params.rsi_entry:.2f}({pass_rsi}), "
            f"close={close:.6f}>{ema_fast:.6f}({pass_trend}){bb_note}, atr={atr:.6f}"
        )
        return pass_rsi and pass_trend and pass_bb, note

    def _entry_diagnostics_short(self, prev: pd.Series, params: StrategyParams, bb_entry_mode: str) -> tuple[bool, str]:
        fast_col = f"ema{params.ema_fast}"
        missing: list[str] = []
        if pd.isna(prev.get("rsi")):
            missing.append("rsi")
        if pd.isna(prev.get("atr")):
            missing.append("atr")
        if pd.isna(prev.get(fast_col)):
            missing.append(fast_col)
        if pd.isna(prev.get("close")):
            missing.append("close")
        if bb_entry_mode != "off" and pd.isna(prev.get("bb_upper")):
            missing.append("bb_upper")
        if missing:
            return False, f"short: missing={','.join(missing)}"

        rsi = float(prev["rsi"])
        atr = float(prev["atr"])
        close = float(prev["close"])
        ema_fast = float(prev[fast_col])
        pass_rsi = rsi >= params.rsi_exit
        pass_trend = close < ema_fast
        pass_bb = True
        bb_note = "bb=off"
        if bb_entry_mode == "touch_revert":
            bb_upper = float(prev["bb_upper"])
            pass_bb = close >= bb_upper
            bb_note = f", close={close:.6f}>=bb_upper={bb_upper:.6f}({pass_bb})"
        note = (
            f"short: rsi={rsi:.2f}>={params.rsi_exit:.2f}({pass_rsi}), "
            f"close={close:.6f}<{ema_fast:.6f}({pass_trend}){bb_note}, atr={atr:.6f}"
        )
        return pass_rsi and pass_trend and pass_bb, note

    def _manage_open_position(
        self,
        position,
        prev: pd.Series,
        bar: pd.Series,
        params: StrategyParams,
        constraints: SymbolExecutionConstraints,
    ) -> None:
        fast_col = f"ema{params.ema_fast}"
        hold_bars = int(position.hold_bars) + 1
        is_short = position.trade_side == "short"

        if is_short:
            stop_hit = position.stop_price is not None and float(bar["high"]) >= float(position.stop_price)
            tp_hit = position.take_profit_price is not None and float(bar["low"]) <= float(position.take_profit_price)
        else:
            stop_hit = position.stop_price is not None and float(bar["low"]) <= float(position.stop_price)
            tp_hit = position.take_profit_price is not None and float(bar["high"]) >= float(position.take_profit_price)

        indicator_exit = False
        if pd.notna(prev.get("rsi")) and pd.notna(prev.get(fast_col)) and pd.notna(prev.get("close")):
            if is_short:
                indicator_exit = float(prev["rsi"]) <= params.rsi_entry or float(prev["close"]) > float(prev[fast_col])
            else:
                indicator_exit = float(prev["rsi"]) >= params.rsi_exit or float(prev["close"]) < float(prev[fast_col])

        timed_exit = hold_bars >= params.max_hold_bars
        should_exit = stop_hit or tp_hit or indicator_exit or timed_exit
        if not should_exit:
            self.trading_repo.touch_position(position, hold_bars=hold_bars, last_price=float(bar["close"]))
            summary = [
                f"side={position.trade_side}",
                f"hold_bars={hold_bars}",
                f"stop_hit={stop_hit}",
                f"tp_hit={tp_hit}",
                f"indicator_exit={indicator_exit}",
                f"timed_exit={timed_exit}",
            ]
            if pd.notna(prev.get("rsi")):
                summary.append(f"rsi={float(prev['rsi']):.2f}")
            if pd.notna(prev.get(fast_col)):
                summary.append(f"ema_fast={float(prev[fast_col]):.6f}")
            if pd.notna(prev.get("close")):
                summary.append(f"close={float(prev['close']):.6f}")
            self.trading_repo.set_asset_state(
                symbol=position.symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="position_held",
                note=", ".join(summary),
                log_event=True,
            )
            self._emit_decision_log(
                symbol=position.symbol,
                timeframe=position.timeframe,
                ts=pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None),
                decision="hold",
                reasons=["position_held"],
            )
            return

        if stop_hit:
            reason = "stop"
        elif tp_hit:
            reason = "take_profit"
        elif indicator_exit:
            reason = "signal"
        else:
            reason = "max_hold"

        # Gap-aware exit assumption: if open gaps through stop/TP, fill at the bar open (worse outcome),
        # otherwise fill at the configured stop/TP threshold for that bar.
        raw_exit = gap_aware_raw_exit_price(
            trade_side=position.trade_side,
            reason=reason,
            bar_open=float(bar["open"]),
            stop_price=float(position.stop_price) if position.stop_price is not None else None,
            take_profit_price=float(position.take_profit_price) if position.take_profit_price is not None else None,
        )
        try:
            exit_fill = self.execution.submit_exit(
                symbol=position.symbol,
                raw_price=raw_exit,
                qty=float(position.qty),
                trade_side=position.trade_side,
                constraints=constraints,
            )
        except Exception as exc:  # noqa: BLE001
            self.trading_repo.set_asset_state(
                symbol=position.symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="execution_failed",
                note=f"exit_failed: {exc}",
                log_event=True,
            )
            self._emit_decision_log(
                symbol=position.symbol,
                timeframe=position.timeframe,
                ts=pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None),
                decision="hold",
                reasons=["execution_failed", "exit_failed"],
            )
            logger.exception("Execution adapter exit failed for %s: %s", position.symbol, exc)
            return
        exit_ts = pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None)
        trade = self.trading_repo.close_position(
            position=position,
            exit_ts=exit_ts,
            exit_price=exit_fill.price,
            exit_reason=reason,
            exit_fee=exit_fill.fee_usd,
        )
        self.trading_repo.set_asset_state(
            symbol=trade.symbol,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            state="position_closed",
            note=f"reason={reason}, side={trade.trade_side}, fill={exit_fill.price:.6f}, net_pnl={trade.net_pnl:.6f}",
            log_event=True,
        )
        logger.info(
            "Closed position %s %s @ %.6f reason=%s net_pnl=%.6f",
            trade.symbol,
            trade.timeframe,
            exit_fill.price,
            reason,
            trade.net_pnl,
        )
        self._emit_decision_log(
            symbol=trade.symbol,
            timeframe=trade.timeframe,
            ts=trade.exit_ts,
            decision="exit",
            reasons=[f"reason={reason}", f"side={trade.trade_side}"],
        )
