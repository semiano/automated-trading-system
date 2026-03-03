from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


TradeActionSide = Literal["buy", "sell"]
PositionSide = Literal["long", "short"]
ExitReason = Literal["stop", "take_profit", "signal", "max_hold"]


def apply_slippage(price: float, side: TradeActionSide, slip: float) -> float:
    if side == "buy":
        return float(price) * (1.0 + float(slip))
    return float(price) * (1.0 - float(slip))


def round_down_to_step(value: float, step: float | None) -> float:
    if step is None or step <= 0:
        return float(value)
    scaled = int(float(value) / float(step))
    return float(scaled * float(step))


def apply_price_tick(price: float, side: TradeActionSide, tick: float | None) -> float:
    if tick is None or tick <= 0:
        return float(price)
    scaled = float(price) / float(tick)
    if side == "buy":
        adjusted = int(-(-scaled // 1))
    else:
        adjusted = int(scaled // 1)
    return float(adjusted * float(tick))


@dataclass(slots=True)
class SymbolExecutionConstraints:
    min_notional_usd: float = 0.0
    qty_step: float = 0.0
    price_tick: float | None = None
    fee_bps: float = 6.0


@dataclass(slots=True)
class Fill:
    side: TradeActionSide
    price: float
    qty: float
    notional_usd: float
    fee_usd: float


class ExecutionAdapter(Protocol):
    def submit_entry(
        self,
        *,
        raw_price: float,
        qty: float,
        trade_side: PositionSide,
        constraints: SymbolExecutionConstraints,
    ) -> Fill:
        ...

    def submit_exit(
        self,
        *,
        raw_price: float,
        qty: float,
        trade_side: PositionSide,
        constraints: SymbolExecutionConstraints,
    ) -> Fill:
        ...


class PaperExecutionAdapter:
    def __init__(self, slippage_bps: float) -> None:
        self.slip = float(slippage_bps) / 10000.0

    def submit_entry(
        self,
        *,
        raw_price: float,
        qty: float,
        trade_side: PositionSide,
        constraints: SymbolExecutionConstraints,
    ) -> Fill:
        side: TradeActionSide = "buy" if trade_side == "long" else "sell"
        price = apply_slippage(raw_price, side=side, slip=self.slip)
        price = apply_price_tick(price, side=side, tick=constraints.price_tick)
        notional = float(price) * float(qty)
        fee = notional * (float(constraints.fee_bps) / 10000.0)
        return Fill(side=side, price=float(price), qty=float(qty), notional_usd=float(notional), fee_usd=float(fee))

    def submit_exit(
        self,
        *,
        raw_price: float,
        qty: float,
        trade_side: PositionSide,
        constraints: SymbolExecutionConstraints,
    ) -> Fill:
        side: TradeActionSide = "sell" if trade_side == "long" else "buy"
        price = apply_slippage(raw_price, side=side, slip=self.slip)
        price = apply_price_tick(price, side=side, tick=constraints.price_tick)
        notional = float(price) * float(qty)
        fee = notional * (float(constraints.fee_bps) / 10000.0)
        return Fill(side=side, price=float(price), qty=float(qty), notional_usd=float(notional), fee_usd=float(fee))


def gap_aware_raw_exit_price(
    *,
    trade_side: PositionSide,
    reason: ExitReason,
    bar_open: float,
    stop_price: float | None,
    take_profit_price: float | None,
) -> float:
    if reason == "stop":
        if trade_side == "long":
            return min(float(bar_open), float(stop_price)) if stop_price is not None else float(bar_open)
        return max(float(bar_open), float(stop_price)) if stop_price is not None else float(bar_open)

    if reason == "take_profit":
        if trade_side == "long":
            return max(float(bar_open), float(take_profit_price)) if take_profit_price is not None else float(bar_open)
        return min(float(bar_open), float(take_profit_price)) if take_profit_price is not None else float(bar_open)

    return float(bar_open)
