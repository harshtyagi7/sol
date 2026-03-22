"""
Strategy executor — runs all trades in an approved strategy autonomously.
Enforces the user's max-loss cap after every trade closes.
No user confirmation needed per-trade once strategy is approved.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class StrategyExecutor:

    async def execute_strategy(self, strategy_id: str):
        """
        Execute all PENDING trades in a strategy in sequence order.
        Stops immediately if the max-loss cap is hit after any trade.
        Runs as a background task — does not block the caller.
        """
        asyncio.create_task(self._run(strategy_id))

    async def _run(self, strategy_id: str):
        from sol.database import get_session
        from sol.models.strategy import Strategy, StrategyTrade
        from sol.core.event_bus import publish_event
        from sqlalchemy import select

        logger.info(f"Strategy executor starting for {strategy_id}")

        async with get_session() as db:
            s_result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
            strategy = s_result.scalar_one_or_none()
            if not strategy or strategy.status != "ACTIVE":
                return

            t_result = await db.execute(
                select(StrategyTrade)
                .where(StrategyTrade.strategy_id == strategy_id, StrategyTrade.status == "PENDING")
                .order_by(StrategyTrade.sequence)
            )
            trades = t_result.scalars().all()

        for trade in trades:
            # Re-check strategy is still active before each trade
            cap_hit = await self._is_cap_hit(strategy_id)
            if cap_hit:
                await self._cancel_remaining(strategy_id, "Max loss cap reached")
                return

            await self._execute_trade(strategy_id, trade.id)

        # Mark complete if all trades processed
        await self._try_complete(strategy_id)

    async def _execute_trade(self, strategy_id: str, trade_id: str):
        from sol.database import get_session
        from sol.models.strategy import Strategy, StrategyTrade
        from sol.models.position import Position
        from sol.broker.order_manager import get_order_manager
        from sol.core.risk_engine import RiskEngine
        from sol.services.risk_service import get_risk_service
        from sol.schemas.trade import TradeProposalCreate
        from sol.core.event_bus import publish_event
        from sqlalchemy import select

        async with get_session() as db:
            t_result = await db.execute(select(StrategyTrade).where(StrategyTrade.id == trade_id))
            trade = t_result.scalar_one_or_none()
            if not trade or trade.status != "PENDING":
                return

            s_result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
            strategy = s_result.scalar_one_or_none()

            # Build a TradeProposalCreate for risk validation
            proposal_create = TradeProposalCreate(
                symbol=trade.symbol,
                exchange=trade.exchange,
                direction=trade.direction,
                order_type=trade.order_type,
                product_type=trade.product_type,
                quantity=trade.quantity,
                entry_price=trade.entry_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                rationale=trade.rationale,
            )

            risk_service = get_risk_service()
            risk_report = await risk_service.validate_proposal(proposal_create)

            if not risk_report.approved:
                trade.status = "SKIPPED"
                trade.skip_reason = f"Risk check failed: {'; '.join(risk_report.violations)}"
                await db.flush()
                logger.warning(
                    f"Trade {trade.symbol} in strategy '{strategy.name}' skipped: {trade.skip_reason}"
                )
                await publish_event("strategy_trade_skipped", {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy.name,
                    "symbol": trade.symbol,
                    "reason": trade.skip_reason,
                })
                return

            # Execute
            trade.status = "EXECUTING"
            await db.flush()

        try:
            om = get_order_manager()

            class _FakeProposal:
                pass

            fp = _FakeProposal()
            fp.id = trade_id
            fp.symbol = trade.symbol
            fp.exchange = trade.exchange
            fp.direction = trade.direction
            fp.order_type = trade.order_type
            fp.product_type = trade.product_type
            fp.quantity = trade.quantity
            fp.entry_price = trade.entry_price
            fp.stop_loss = trade.stop_loss
            fp.take_profit = trade.take_profit
            fp.rationale = trade.rationale

            order_id = await om.execute_proposal(fp, risk_report)

            async with get_session() as db:
                t_result = await db.execute(select(StrategyTrade).where(StrategyTrade.id == trade_id))
                trade = t_result.scalar_one()
                trade.status = "EXECUTED"
                trade.kite_order_id = order_id
                trade.executed_at = datetime.now(IST)

                # Create position record
                actual_qty = risk_report.modified_quantity or trade.quantity
                position = Position(
                    proposal_id=trade_id,
                    agent_id=trade.agent_id,
                    agent_name=strategy.agent_name,
                    is_virtual=strategy.is_virtual,
                    symbol=trade.symbol,
                    exchange=trade.exchange,
                    direction=trade.direction,
                    product_type=trade.product_type,
                    quantity=actual_qty,
                    avg_price=trade.entry_price or 0.0,
                    stop_loss=trade.stop_loss,
                    take_profit=trade.take_profit,
                    opened_at=datetime.now(IST),
                    status="OPEN",
                )
                db.add(position)
                await db.flush()
                trade.position_id = position.id

            logger.info(
                f"[Strategy '{strategy.name}'] Executed: "
                f"{trade.direction} {actual_qty} {trade.exchange}:{trade.symbol} → {order_id}"
            )
            await publish_event("strategy_trade_executed", {
                "strategy_id": strategy_id,
                "strategy_name": strategy.name,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "quantity": actual_qty,
                "order_id": order_id,
            })

        except Exception as e:
            logger.error(f"Trade execution failed for {trade.symbol} in strategy {strategy_id}: {e}")
            async with get_session() as db:
                t_result = await db.execute(select(StrategyTrade).where(StrategyTrade.id == trade_id))
                t = t_result.scalar_one_or_none()
                if t:
                    t.status = "FAILED"
                    t.skip_reason = str(e)

    async def on_trade_closed(self, strategy_id: str, realized_pnl: float):
        """
        Called by position monitor when a strategy position closes.
        Updates loss tracking and cancels remaining trades if cap hit.
        """
        from sol.services.strategy_service import get_strategy_service
        svc = get_strategy_service()
        cap_hit = await svc.update_actual_loss(strategy_id, realized_pnl)
        if cap_hit:
            await self._cancel_remaining(strategy_id, "Max loss cap reached")

    async def _is_cap_hit(self, strategy_id: str) -> bool:
        from sol.database import get_session
        from sol.models.strategy import Strategy
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
            s = result.scalar_one_or_none()
            if not s:
                return True
            if s.status not in ("ACTIVE",):
                return True
            cap = float(s.max_loss_approved or 0)
            actual = float(s.actual_loss or 0)
            return cap > 0 and actual >= cap

    async def _cancel_remaining(self, strategy_id: str, reason: str):
        from sol.database import get_session
        from sol.models.strategy import StrategyTrade
        from sqlalchemy import update

        async with get_session() as db:
            await db.execute(
                update(StrategyTrade)
                .where(StrategyTrade.strategy_id == strategy_id, StrategyTrade.status == "PENDING")
                .values(status="CANCELLED", skip_reason=reason)
            )

    async def _try_complete(self, strategy_id: str):
        from sol.database import get_session
        from sol.models.strategy import Strategy, StrategyTrade
        from sqlalchemy import select, func

        async with get_session() as db:
            # Only complete if no OPEN positions remain for this strategy
            result = await db.execute(
                select(func.count()).select_from(StrategyTrade).where(
                    StrategyTrade.strategy_id == strategy_id,
                    StrategyTrade.status.in_(["PENDING", "EXECUTING"]),
                )
            )
            pending = result.scalar() or 0
            if pending == 0:
                s_result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
                strategy = s_result.scalar_one_or_none()
                if strategy and strategy.status == "ACTIVE":
                    strategy.status = "COMPLETED"
                    strategy.completed_at = datetime.now(IST)
                    logger.info(f"Strategy '{strategy.name}' completed all trades")


_executor: Optional[StrategyExecutor] = None


def get_strategy_executor() -> StrategyExecutor:
    global _executor
    if _executor is None:
        _executor = StrategyExecutor()
    return _executor
