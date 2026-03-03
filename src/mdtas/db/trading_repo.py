from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from mdtas.db.models import AssetControl, AssetEngineLog, Position, Trade


class TradingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_asset_control(
        self,
        symbol: str,
        default_soft_risk_limit_usd: float,
        default_execution_mode: str = "sim",
        default_trade_side: str = "long_only",
        default_enabled: bool = True,
    ) -> AssetControl:
        item = self.session.scalar(select(AssetControl).where(AssetControl.symbol == symbol).limit(1))
        if item is None:
            item = AssetControl(
                symbol=symbol,
                enabled=default_enabled,
                execution_mode=default_execution_mode,
                trade_side=default_trade_side,
                soft_risk_limit_usd=float(default_soft_risk_limit_usd),
            )
            self.session.add(item)
            self.session.commit()
            self.session.refresh(item)
        return item

    def list_asset_controls(
        self,
        symbols: list[str],
        default_soft_risk_limit_usd: float,
        default_execution_mode: str = "sim",
        default_trade_side: str = "long_only",
    ) -> list[AssetControl]:
        out: list[AssetControl] = []
        for symbol in symbols:
            out.append(
                self.get_or_create_asset_control(
                    symbol=symbol,
                    default_soft_risk_limit_usd=default_soft_risk_limit_usd,
                    default_execution_mode=default_execution_mode,
                    default_trade_side=default_trade_side,
                    default_enabled=True,
                )
            )
        return out

    def update_asset_control(
        self,
        symbol: str,
        default_soft_risk_limit_usd: float,
        enabled: bool | None = None,
        execution_mode: str | None = None,
        trade_side: str | None = None,
        soft_risk_limit_usd: float | None = None,
    ) -> AssetControl:
        item = self.get_or_create_asset_control(
            symbol=symbol,
            default_soft_risk_limit_usd=default_soft_risk_limit_usd,
        )
        if enabled is not None:
            item.enabled = bool(enabled)
        if execution_mode is not None:
            item.execution_mode = execution_mode
        if trade_side is not None:
            item.trade_side = trade_side
        if soft_risk_limit_usd is not None:
            item.soft_risk_limit_usd = float(soft_risk_limit_usd)
        self.session.commit()
        self.session.refresh(item)
        return item

    def mark_asset_run(self, symbol: str, default_soft_risk_limit_usd: float, poll_delay_seconds: int) -> AssetControl:
        item = self.get_or_create_asset_control(
            symbol=symbol,
            default_soft_risk_limit_usd=default_soft_risk_limit_usd,
        )
        now = datetime.utcnow().replace(microsecond=0)
        item.last_run_ts = now
        item.next_run_ts = now + timedelta(seconds=max(1, poll_delay_seconds))
        self.session.commit()
        self.session.refresh(item)
        return item

    def set_asset_state(
        self,
        symbol: str,
        default_soft_risk_limit_usd: float,
        state: str,
        note: str | None = None,
        log_event: bool = True,
    ) -> AssetControl:
        item = self.get_or_create_asset_control(
            symbol=symbol,
            default_soft_risk_limit_usd=default_soft_risk_limit_usd,
        )
        item.last_evaluated_state = state
        item.last_evaluated_note = note
        if log_event:
            self.session.add(
                AssetEngineLog(
                    symbol=symbol,
                    state=state,
                    note=note,
                )
            )
        self.session.commit()
        self.session.refresh(item)
        return item

    def list_asset_logs(self, symbol: str, limit: int) -> list[AssetEngineLog]:
        return self.session.scalars(
            select(AssetEngineLog)
            .where(AssetEngineLog.symbol == symbol)
            .order_by(AssetEngineLog.created_at.desc(), AssetEngineLog.id.desc())
            .limit(limit)
        ).all()

    def get_open_position(
        self,
        symbol: str,
        venue: str,
        timeframe: str,
        execution_mode: str,
    ) -> Position | None:
        return self.session.scalar(
            select(Position)
            .where(
                and_(
                    Position.symbol == symbol,
                    Position.venue == venue,
                    Position.timeframe == timeframe,
                    Position.execution_mode == execution_mode,
                    Position.status == "open",
                )
            )
            .order_by(Position.opened_at.desc())
            .limit(1)
        )

    def list_open_positions(
        self,
        symbol: str | None = None,
        venue: str | None = None,
        timeframe: str | None = None,
        execution_mode: str | None = None,
    ) -> list[Position]:
        clauses = [Position.status == "open"]
        if symbol:
            clauses.append(Position.symbol == symbol)
        if venue:
            clauses.append(Position.venue == venue)
        if timeframe:
            clauses.append(Position.timeframe == timeframe)
        if execution_mode:
            clauses.append(Position.execution_mode == execution_mode)
        return self.session.scalars(select(Position).where(and_(*clauses)).order_by(Position.opened_at.desc())).all()

    def list_closed_trades(
        self,
        symbol: str | None,
        venue: str | None,
        timeframe: str | None,
        execution_mode: str | None,
        limit: int,
    ) -> list[Trade]:
        clauses = []
        if symbol:
            clauses.append(Trade.symbol == symbol)
        if venue:
            clauses.append(Trade.venue == venue)
        if timeframe:
            clauses.append(Trade.timeframe == timeframe)
        if execution_mode:
            clauses.append(Trade.execution_mode == execution_mode)

        stmt = select(Trade)
        if clauses:
            stmt = stmt.where(and_(*clauses))
        stmt = stmt.order_by(Trade.exit_ts.desc()).limit(limit)
        return self.session.scalars(stmt).all()

    def open_position(
        self,
        symbol: str,
        venue: str,
        timeframe: str,
        execution_mode: str,
        trade_side: str,
        entry_ts: datetime,
        entry_price: float,
        qty: float,
        entry_fee: float,
        stop_price: float | None,
        take_profit_price: float | None,
        last_price: float,
    ) -> Position:
        position = Position(
            symbol=symbol,
            venue=venue,
            timeframe=timeframe,
            execution_mode=execution_mode,
            trade_side=trade_side,
            status="open",
            entry_ts=entry_ts,
            entry_price=entry_price,
            qty=qty,
            entry_fee=entry_fee,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            hold_bars=0,
            last_price=last_price,
        )
        self.session.add(position)
        self.session.commit()
        self.session.refresh(position)
        return position

    def touch_position(self, position: Position, hold_bars: int, last_price: float) -> Position:
        position.hold_bars = hold_bars
        position.last_price = last_price
        self.session.commit()
        self.session.refresh(position)
        return position

    def close_position(
        self,
        position: Position,
        exit_ts: datetime,
        exit_price: float,
        exit_reason: str,
        exit_fee: float,
    ) -> Trade:
        gross_pnl = (exit_price - position.entry_price) * position.qty
        if position.trade_side == "short":
            gross_pnl = (position.entry_price - exit_price) * position.qty
        fees = position.entry_fee + exit_fee
        net_pnl = gross_pnl - fees
        notional = position.entry_price * position.qty
        return_pct = (net_pnl / notional) * 100.0 if notional > 0 else 0.0

        position.status = "closed"
        position.closed_at = exit_ts
        position.last_price = exit_price

        trade = Trade(
            symbol=position.symbol,
            venue=position.venue,
            timeframe=position.timeframe,
            execution_mode=position.execution_mode,
            trade_side=position.trade_side,
            entry_ts=position.entry_ts,
            exit_ts=exit_ts,
            entry_price=position.entry_price,
            exit_price=exit_price,
            qty=position.qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            return_pct=return_pct,
            exit_reason=exit_reason,
        )
        self.session.add(trade)
        self.session.commit()
        self.session.refresh(trade)
        return trade

    def current_open_risk_usd(
        self,
        symbol: str | None = None,
        venue: str | None = None,
        timeframe: str | None = None,
        execution_mode: str | None = None,
    ) -> float:
        items = self.list_open_positions(
            symbol=symbol,
            venue=venue,
            timeframe=timeframe,
            execution_mode=execution_mode,
        )
        total = 0.0
        for item in items:
            entry_price = float(item.entry_price)
            stop_price = float(item.stop_price) if item.stop_price is not None else entry_price
            if item.trade_side == "short":
                unit_risk = max(stop_price - entry_price, 0.0)
            else:
                unit_risk = max(entry_price - stop_price, 0.0)
            total += (unit_risk * float(item.qty)) + float(item.entry_fee)
        return float(total)
