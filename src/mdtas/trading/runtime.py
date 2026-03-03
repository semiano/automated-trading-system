from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from mdtas.config import AppConfig, StrategyParamsConfig
from mdtas.db.repo import CandleRepository
from mdtas.db.trading_repo import TradingRepository
from mdtas.indicators.engine import compute
from mdtas.utils.timeframes import timeframe_to_timedelta

logger = logging.getLogger(__name__)


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
        self._load_tuned_file()

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

    def _load_tuned_file(self) -> None:
        path = Path(self.cfg.trading.tuned_params_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed loading tuned params file: %s", exc)

    def for_symbol(self, symbol: str) -> StrategyParams:
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

    def is_symbol_enabled(self, symbol: str) -> bool:
        control = self.trading_repo.get_or_create_asset_control(
            symbol=symbol,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            default_execution_mode="sim",
            default_enabled=True,
        )
        return bool(control.enabled)

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
        if len(frame) < max(params.ema_slow + 5, params.rsi_length + 5, params.atr_length + 5):
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="insufficient_bars",
                note=f"Need more bars for runtime timeframe {timeframe}",
                log_event=False,
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
            return

        indicators = ["rsi", "atr", f"ema{params.ema_fast}", f"ema{params.ema_slow}"]
        out = compute(frame, indicators, params.indicator_params())
        if len(out) < 2:
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="insufficient_signal_rows",
                note=f"indicator_rows={len(out)}",
                log_event=True,
            )
            return

        prev = out.iloc[-2]
        bar = out.iloc[-1]
        open_position = self.trading_repo.get_open_position(symbol, venue, timeframe, execution_mode)

        fee = self.cfg.trading.fee_bps / 10000.0
        slippage = self.cfg.trading.slippage_bps / 10000.0

        if open_position is None:
            long_allowed = trade_side_mode in {"long_only", "long_short"}
            short_allowed = trade_side_mode in {"short_only", "long_short"}

            long_ok, long_note = self._entry_diagnostics_long(prev, params)
            short_ok, short_note = self._entry_diagnostics_short(prev, params)

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
                return

            exec_price = float(bar["open"]) * (1.0 + slippage)
            notional = max(self.cfg.trading.position_size_usd, 1.0)
            qty = notional / (exec_price * (1.0 + fee))
            entry_fee = (exec_price * qty) * fee
            atr = float(prev["atr"])
            if chosen_side == "short":
                stop_price = exec_price + (params.stop_atr * atr)
                take_profit_price = exec_price - (params.take_profit_atr * atr)
                projected_trade_risk = max(stop_price - exec_price, 0.0) * qty + entry_fee
            else:
                stop_price = exec_price - (params.stop_atr * atr)
                take_profit_price = exec_price + (params.take_profit_atr * atr)
                projected_trade_risk = max(exec_price - stop_price, 0.0) * qty + entry_fee
            soft_limit = float(control.soft_risk_limit_usd)
            current_risk = self.trading_repo.current_open_risk_usd(
                symbol=symbol,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
            )
            if current_risk + projected_trade_risk > soft_limit:
                self.trading_repo.set_asset_state(
                    symbol=symbol,
                    default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                    state="risk_blocked",
                    note=f"current={current_risk:.4f}, projected={projected_trade_risk:.4f}, limit={soft_limit:.4f}",
                    log_event=True,
                )
                logger.warning(
                    "Soft risk limit blocked entry for %s: current_risk=%.4f projected_trade_risk=%.4f soft_limit=%.4f",
                    symbol,
                    current_risk,
                    projected_trade_risk,
                    soft_limit,
                )
                return

            self.trading_repo.open_position(
                symbol=symbol,
                venue=venue,
                timeframe=timeframe,
                execution_mode=execution_mode,
                trade_side=chosen_side,
                entry_ts=pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None),
                entry_price=exec_price,
                qty=qty,
                entry_fee=entry_fee,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                last_price=float(bar["close"]),
            )
            self.trading_repo.set_asset_state(
                symbol=symbol,
                default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
                state="position_opened",
                note=f"mode={execution_mode}, side={chosen_side}, {chosen_note}",
                log_event=True,
            )
            logger.info(
                "Opened position %s %s mode=%s side=%s @ %.6f qty=%.6f",
                symbol,
                timeframe,
                execution_mode,
                chosen_side,
                exec_price,
                qty,
            )
            return

        self._manage_open_position(open_position, prev, bar, params, fee, slippage)

    def _entry_diagnostics_long(self, prev: pd.Series, params: StrategyParams) -> tuple[bool, str]:
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
        if missing:
            return False, f"missing={','.join(missing)}"

        rsi = float(prev["rsi"])
        atr = float(prev["atr"])
        close = float(prev["close"])
        ema_fast = float(prev[fast_col])
        pass_rsi = rsi <= params.rsi_entry
        pass_trend = close > ema_fast
        note = (
            f"long: rsi={rsi:.2f}<={params.rsi_entry:.2f}({pass_rsi}), "
            f"close={close:.6f}>{ema_fast:.6f}({pass_trend}), atr={atr:.6f}"
        )
        return pass_rsi and pass_trend, note

    def _entry_diagnostics_short(self, prev: pd.Series, params: StrategyParams) -> tuple[bool, str]:
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
        if missing:
            return False, f"short: missing={','.join(missing)}"

        rsi = float(prev["rsi"])
        atr = float(prev["atr"])
        close = float(prev["close"])
        ema_fast = float(prev[fast_col])
        pass_rsi = rsi >= params.rsi_exit
        pass_trend = close < ema_fast
        note = (
            f"short: rsi={rsi:.2f}>={params.rsi_exit:.2f}({pass_rsi}), "
            f"close={close:.6f}<{ema_fast:.6f}({pass_trend}), atr={atr:.6f}"
        )
        return pass_rsi and pass_trend, note

    def _manage_open_position(
        self,
        position,
        prev: pd.Series,
        bar: pd.Series,
        params: StrategyParams,
        fee: float,
        slippage: float,
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
            return

        if stop_hit:
            raw_exit = float(position.stop_price)
            reason = "stop"
        elif tp_hit:
            raw_exit = float(position.take_profit_price)
            reason = "take_profit"
        elif indicator_exit:
            raw_exit = float(bar["open"])
            reason = "signal"
        else:
            raw_exit = float(bar["open"])
            reason = "max_hold"

        exec_exit = raw_exit * (1.0 - slippage)
        exit_fee = (exec_exit * float(position.qty)) * fee
        exit_ts = pd.to_datetime(bar["ts"]).to_pydatetime().replace(tzinfo=None)
        trade = self.trading_repo.close_position(
            position=position,
            exit_ts=exit_ts,
            exit_price=exec_exit,
            exit_reason=reason,
            exit_fee=exit_fee,
        )
        self.trading_repo.set_asset_state(
            symbol=trade.symbol,
            default_soft_risk_limit_usd=self.cfg.trading.soft_portfolio_risk_limit_usd,
            state="position_closed",
            note=f"reason={reason}, net_pnl={trade.net_pnl:.6f}",
            log_event=True,
        )
        logger.info(
            "Closed position %s %s @ %.6f reason=%s net_pnl=%.6f",
            trade.symbol,
            trade.timeframe,
            exec_exit,
            reason,
            trade.net_pnl,
        )
