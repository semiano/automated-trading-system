from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal, Protocol

import ccxt


TradeActionSide = Literal["buy", "sell"]
PositionSide = Literal["long", "short"]
ExitReason = Literal["stop", "take_profit", "signal", "max_hold"]

logger = logging.getLogger(__name__)


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
        symbol: str,
        raw_price: float,
        qty: float,
        trade_side: PositionSide,
        constraints: SymbolExecutionConstraints,
    ) -> Fill:
        ...

    def submit_exit(
        self,
        *,
        symbol: str,
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
        symbol: str,
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
        symbol: str,
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


class CcxtExecutionAdapter:
    def __init__(
        self,
        *,
        venue: str,
        rate_limit: bool,
        api_key: str | None,
        api_secret: str | None,
        api_password: str | None,
        sandbox: bool,
        live_trading_enabled: bool,
        live_allow_short: bool,
        live_max_order_notional_usd: float,
        live_allowed_symbols: list[str],
        live_require_explicit_env_ack: bool,
        live_ack_env_var_name: str,
        live_ack_env_var_value: str,
    ) -> None:
        if not live_trading_enabled:
            raise ValueError("live_trading_enabled must be true for real execution")
        if not api_key or not api_secret:
            raise ValueError("EXCHANGE_API_KEY and EXCHANGE_API_SECRET are required for real execution")
        if live_require_explicit_env_ack:
            ack_value = os.getenv(live_ack_env_var_name, "")
            if ack_value != live_ack_env_var_value:
                raise ValueError(
                    f"Real execution requires env {live_ack_env_var_name}={live_ack_env_var_value}"
                )

        venue_cls = getattr(ccxt, venue)
        kwargs: dict[str, object] = {
            "enableRateLimit": bool(rate_limit),
            "apiKey": api_key,
            "secret": api_secret,
        }
        if api_password:
            kwargs["password"] = api_password

        self.exchange = venue_cls(kwargs)
        if sandbox and hasattr(self.exchange, "set_sandbox_mode"):
            self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()

        self.live_allow_short = bool(live_allow_short)
        self.live_max_order_notional_usd = float(live_max_order_notional_usd)
        self.live_allowed_symbols = set(live_allowed_symbols)
        self.venue = venue

    def _validate_request(self, *, symbol: str, raw_price: float, qty: float, trade_side: PositionSide) -> None:
        if qty <= 0:
            raise ValueError("Order quantity must be > 0")
        if raw_price <= 0:
            raise ValueError("Raw price must be > 0")
        if self.live_allowed_symbols and symbol not in self.live_allowed_symbols:
            raise ValueError(f"Symbol {symbol} is not in live_allowed_symbols")
        notional = float(raw_price) * float(qty)
        if self.live_max_order_notional_usd > 0 and notional > self.live_max_order_notional_usd:
            raise ValueError(
                f"Order notional {notional:.8f} exceeds live_max_order_notional_usd {self.live_max_order_notional_usd:.8f}"
            )
        if trade_side == "short" and not self.live_allow_short:
            raise ValueError("Short trading disabled by live_allow_short=false")

    def _submit_market_order(self, *, symbol: str, side: TradeActionSide, qty: float, raw_price: float) -> dict:
        create_kwargs: dict[str, object] = {
            "symbol": symbol,
            "type": "market",
            "side": side,
            "amount": float(qty),
        }
        if side == "buy":
            create_kwargs["price"] = float(raw_price)

        order = self.exchange.create_order(**create_kwargs)
        if not isinstance(order, dict):
            raise ValueError("Exchange returned non-dict order response")
        return order

    @staticmethod
    def _extract_fee(order: dict) -> float:
        fee_obj = order.get("fee")
        if isinstance(fee_obj, dict) and fee_obj.get("cost") is not None:
            return float(fee_obj.get("cost"))
        fees_obj = order.get("fees")
        if isinstance(fees_obj, list):
            total = 0.0
            for item in fees_obj:
                if isinstance(item, dict) and item.get("cost") is not None:
                    total += float(item.get("cost"))
            return total
        return 0.0

    @staticmethod
    def _extract_fill(order: dict, *, side: TradeActionSide, fallback_price: float, fallback_qty: float) -> Fill:
        filled_qty = float(order.get("filled") or fallback_qty)
        average = order.get("average")
        cost = order.get("cost")
        if average is not None:
            price = float(average)
        elif cost is not None and filled_qty > 0:
            price = float(cost) / float(filled_qty)
        else:
            price = float(fallback_price)
        notional = float(cost) if cost is not None else float(price) * float(filled_qty)
        fee = CcxtExecutionAdapter._extract_fee(order)
        return Fill(side=side, price=float(price), qty=float(filled_qty), notional_usd=float(notional), fee_usd=float(fee))

    def submit_entry(
        self,
        *,
        symbol: str,
        raw_price: float,
        qty: float,
        trade_side: PositionSide,
        constraints: SymbolExecutionConstraints,
    ) -> Fill:
        self._validate_request(symbol=symbol, raw_price=raw_price, qty=qty, trade_side=trade_side)
        side: TradeActionSide = "buy" if trade_side == "long" else "sell"
        order = self._submit_market_order(symbol=symbol, side=side, qty=qty, raw_price=raw_price)
        fill = self._extract_fill(order, side=side, fallback_price=raw_price, fallback_qty=qty)
        logger.warning(
            "LIVE ENTRY %s %s side=%s qty=%.8f price=%.8f notional=%.8f fee=%.8f",
            self.venue,
            symbol,
            side,
            fill.qty,
            fill.price,
            fill.notional_usd,
            fill.fee_usd,
        )
        return fill

    def submit_exit(
        self,
        *,
        symbol: str,
        raw_price: float,
        qty: float,
        trade_side: PositionSide,
        constraints: SymbolExecutionConstraints,
    ) -> Fill:
        self._validate_request(symbol=symbol, raw_price=raw_price, qty=qty, trade_side=trade_side)
        side: TradeActionSide = "sell" if trade_side == "long" else "buy"
        order = self._submit_market_order(symbol=symbol, side=side, qty=qty, raw_price=raw_price)
        fill = self._extract_fill(order, side=side, fallback_price=raw_price, fallback_qty=qty)
        logger.warning(
            "LIVE EXIT %s %s side=%s qty=%.8f price=%.8f notional=%.8f fee=%.8f",
            self.venue,
            symbol,
            side,
            fill.qty,
            fill.price,
            fill.notional_usd,
            fill.fee_usd,
        )
        return fill


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
