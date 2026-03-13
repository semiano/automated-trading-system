from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from mdtas.db.models import AssetControl, AssetEngineLog, AssetTuningVersion, Position, SimWalletBalance, Trade


@dataclass(slots=True)
class ExitInfo:
    ts: datetime
    reason: str


class TradingRepository:
    def list_all_asset_controls_for_symbol(self, symbol: str) -> list[AssetControl]:
        return self.session.scalars(
            select(AssetControl).where(AssetControl.symbol == symbol)
        ).all()

    def __init__(self, session: Session) -> None:
        self.session = session

    def log_engine_event(self, symbol: str, state: str, note: str | None = None, timeframe: str = "system") -> AssetEngineLog:
        row = AssetEngineLog(symbol=symbol, timeframe=timeframe, state=state, note=note)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def latest_engine_event(
        self,
        symbol: str,
        states: tuple[str, ...] | None = None,
        timeframe: str | None = None,
    ) -> AssetEngineLog | None:
        stmt = select(AssetEngineLog).where(AssetEngineLog.symbol == symbol)
        if timeframe is not None:
            stmt = stmt.where(AssetEngineLog.timeframe == timeframe)
        if states:
            stmt = stmt.where(AssetEngineLog.state.in_(states))
        stmt = stmt.order_by(AssetEngineLog.created_at.desc(), AssetEngineLog.id.desc()).limit(1)
        return self.session.scalar(stmt)

    def get_or_create_asset_control(
        self,
        symbol: str,
        timeframe: str,
        default_soft_risk_limit_usd: float,
        default_execution_mode: str = "sim",
        default_trade_side: str = "long_only",
        default_enabled: bool = True,
    ) -> AssetControl:
        item = self.session.scalar(
            select(AssetControl)
            .where(AssetControl.symbol == symbol, AssetControl.timeframe == timeframe)
            .limit(1)
        )
        if item is None:
            item = AssetControl(
                symbol=symbol,
                timeframe=timeframe,
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
        timeframes: list[str],
        default_soft_risk_limit_usd: float,
        default_execution_mode: str = "sim",
        default_trade_side: str = "long_only",
    ) -> list[AssetControl]:
        out: list[AssetControl] = []
        # Always ensure XRP/USD 1h asset control is present
        extra_symbol = "XRP/USD"
        extra_timeframe = "1h"
        for symbol in symbols:
            for timeframe in timeframes:
                out.append(
                    self.get_or_create_asset_control(
                        symbol=symbol,
                        timeframe=timeframe,
                        default_soft_risk_limit_usd=default_soft_risk_limit_usd,
                        default_execution_mode=default_execution_mode,
                        default_trade_side=default_trade_side,
                        default_enabled=True,
                    )
                )
        # Add XRP/USD 1h if not already present
        if extra_symbol in symbols and extra_timeframe not in timeframes:
            out.append(
                self.get_or_create_asset_control(
                    symbol=extra_symbol,
                    timeframe=extra_timeframe,
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
        timeframe: str,
        default_soft_risk_limit_usd: float,
        enabled: bool | None = None,
        execution_mode: str | None = None,
        trade_side: str | None = None,
        soft_risk_limit_usd: float | None = None,
    ) -> AssetControl:
        item = self.get_or_create_asset_control(
            symbol=symbol,
            timeframe=timeframe,
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

    def mark_asset_run(self, symbol: str, timeframe: str, default_soft_risk_limit_usd: float, poll_delay_seconds: int) -> AssetControl:
        item = self.get_or_create_asset_control(
            symbol=symbol,
            timeframe=timeframe,
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
        timeframe: str,
        default_soft_risk_limit_usd: float,
        state: str,
        note: str | None = None,
        log_event: bool = True,
    ) -> AssetControl:
        note_for_control = note[:256] if note is not None else None
        note_for_log = note[:512] if note is not None else None
        item = self.get_or_create_asset_control(
            symbol=symbol,
            timeframe=timeframe,
            default_soft_risk_limit_usd=default_soft_risk_limit_usd,
        )
        prev_state = item.last_evaluated_state
        prev_note = item.last_evaluated_note
        item.last_evaluated_state = state
        item.last_evaluated_note = note_for_control
        should_log = log_event and (prev_state != state or prev_note != note_for_control)
        if should_log:
            self.session.add(
                AssetEngineLog(
                    symbol=symbol,
                    timeframe=timeframe,
                    state=state,
                    note=note_for_log,
                )
            )
        self.session.commit()
        self.session.refresh(item)
        return item

    def list_asset_logs(self, symbol: str, timeframe: str | None, limit: int) -> list[AssetEngineLog]:
        stmt = select(AssetEngineLog).where(AssetEngineLog.symbol == symbol)
        if timeframe is not None:
            stmt = stmt.where(AssetEngineLog.timeframe == timeframe)
        return self.session.scalars(
            stmt
            .order_by(AssetEngineLog.created_at.desc(), AssetEngineLog.id.desc())
            .limit(limit)
        ).all()

    def latest_asset_tuning_version(self, symbol: str, timeframe: str) -> AssetTuningVersion | None:
        return self.session.scalar(
            select(AssetTuningVersion)
            .where(
                AssetTuningVersion.symbol == symbol,
                AssetTuningVersion.timeframe == timeframe,
                AssetTuningVersion.is_active.is_(True),
            )
            .order_by(AssetTuningVersion.version.desc(), AssetTuningVersion.id.desc())
            .limit(1)
        )

    def list_asset_tuning_versions(self, symbol: str, timeframe: str, limit: int = 50) -> list[AssetTuningVersion]:
        return self.session.scalars(
            select(AssetTuningVersion)
            .where(AssetTuningVersion.symbol == symbol, AssetTuningVersion.timeframe == timeframe)
            .order_by(AssetTuningVersion.version.desc(), AssetTuningVersion.id.desc())
            .limit(limit)
        ).all()

    def create_asset_tuning_version(
        self,
        symbol: str,
        timeframe: str,
        params_json: dict[str, float | int],
        note: str | None = None,
        source: str | None = None,
        updated_by: str | None = None,
    ) -> AssetTuningVersion:
        max_version = self.session.scalar(
            select(func.max(AssetTuningVersion.version)).where(
                AssetTuningVersion.symbol == symbol,
                AssetTuningVersion.timeframe == timeframe,
            )
        )
        next_version = int(max_version or 0) + 1

        self.session.execute(
            update(AssetTuningVersion)
            .where(
                AssetTuningVersion.symbol == symbol,
                AssetTuningVersion.timeframe == timeframe,
                AssetTuningVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )

        row = AssetTuningVersion(
            symbol=symbol,
            timeframe=timeframe,
            version=next_version,
            params_json={k: params_json[k] for k in sorted(params_json.keys())},
            note=note,
            source=source,
            updated_by=updated_by,
            is_active=True,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

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
        entry_spot_price: float | None,
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
            entry_spot_price=entry_spot_price,
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
        exit_spot_price: float | None,
        exit_reason: str,
        exit_fee: float,
        hold_bars_at_exit: int | None = None,
    ) -> Trade:
        # PnL is intentionally computed from executable fills so entry/exit slippage is reflected in returns.
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
            entry_spot_price=float(position.entry_spot_price) if position.entry_spot_price is not None else None,
            exit_spot_price=float(exit_spot_price) if exit_spot_price is not None else None,
            entry_price=position.entry_price,
            exit_price=exit_price,
            qty=position.qty,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            return_pct=return_pct,
            exit_reason=exit_reason,
            hold_bars_at_exit=int(position.hold_bars if hold_bars_at_exit is None else hold_bars_at_exit),
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

    def realized_net_pnl_by_symbol(self, execution_mode: str | None = None) -> dict[str, float]:
        stmt = select(Trade.symbol, func.sum(Trade.net_pnl)).group_by(Trade.symbol)
        if execution_mode is not None:
            stmt = stmt.where(Trade.execution_mode == execution_mode)
        rows = self.session.execute(stmt).all()
        return {str(symbol): float(total or 0.0) for symbol, total in rows}

    def count_entries(
        self,
        symbol: str,
        since_ts: datetime,
        venue: str | None = None,
        timeframe: str | None = None,
        execution_mode: str | None = None,
    ) -> int:
        clauses = [
            Position.symbol == symbol,
            Position.entry_ts >= since_ts,
        ]
        if venue is not None:
            clauses.append(Position.venue == venue)
        if timeframe is not None:
            clauses.append(Position.timeframe == timeframe)
        if execution_mode is not None:
            clauses.append(Position.execution_mode == execution_mode)

        stmt = select(func.count(Position.id)).where(and_(*clauses))
        count = self.session.scalar(stmt)
        return int(count or 0)

    def get_last_exit(
        self,
        symbol: str,
        venue: str | None = None,
        timeframe: str | None = None,
        execution_mode: str | None = None,
    ) -> ExitInfo | None:
        clauses = [Trade.symbol == symbol]
        if venue is not None:
            clauses.append(Trade.venue == venue)
        if timeframe is not None:
            clauses.append(Trade.timeframe == timeframe)
        if execution_mode is not None:
            clauses.append(Trade.execution_mode == execution_mode)

        row = self.session.scalar(
            select(Trade)
            .where(and_(*clauses))
            .order_by(Trade.exit_ts.desc())
            .limit(1)
        )
        if row is None:
            return None
        return ExitInfo(ts=row.exit_ts, reason=row.exit_reason)

    def get_or_create_sim_wallet_balance(self, symbol: str) -> SimWalletBalance:
        row = self.session.scalar(
            select(SimWalletBalance)
            .where(SimWalletBalance.symbol == symbol)
            .limit(1)
        )
        if row is None:
            row = SimWalletBalance(
                symbol=symbol,
                cash_adjustment_usd=0.0,
                asset_adjustment_usd=0.0,
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
        return row

    def list_sim_wallet_balances(self) -> list[SimWalletBalance]:
        return self.session.scalars(
            select(SimWalletBalance).order_by(SimWalletBalance.symbol.asc())
        ).all()

    def augment_sim_wallet_balance(self, *, symbol: str, bucket: str, amount_usd: float) -> SimWalletBalance:
        row = self.get_or_create_sim_wallet_balance(symbol)
        delta = float(amount_usd)
        if bucket == "cash":
            row.cash_adjustment_usd = float(row.cash_adjustment_usd) + delta
        elif bucket == "asset":
            row.asset_adjustment_usd = float(row.asset_adjustment_usd) + delta
        else:
            raise ValueError("bucket must be one of: cash, asset")
        self.session.commit()
        self.session.refresh(row)
        return row
