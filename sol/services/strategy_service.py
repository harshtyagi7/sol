"""
Strategy service — approval, loss tracking, and lifecycle management.
This is the new approval gate: user approves a max-loss cap on a full strategy,
then all trades within execute autonomously until the cap is hit.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import pytz

from sol.schemas.strategy import StrategyOut, StrategyProposal

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class StrategyService:

    async def save_strategy(
        self,
        proposal: StrategyProposal,
        agent_id: str,
        agent_name: str,
        is_virtual: bool,
    ) -> str:
        """Persist a strategy proposal from an agent. Returns strategy id."""
        from sol.database import get_session
        from sol.models.strategy import Strategy, StrategyTrade

        async with get_session() as db:
            strategy = Strategy(
                agent_id=agent_id,
                agent_name=agent_name,
                name=proposal.name,
                description=proposal.description,
                rationale=proposal.rationale,
                duration_days=proposal.duration_days,
                max_loss_possible=proposal.max_loss_possible,
                status="PENDING_APPROVAL",
                proposed_at=datetime.now(IST),
                is_virtual=is_virtual,
            )
            db.add(strategy)
            await db.flush()  # get strategy.id

            for trade in sorted(proposal.trades, key=lambda t: t.sequence):
                risk = 0.0
                if trade.entry_price and trade.stop_loss:
                    risk = round(abs(trade.entry_price - trade.stop_loss) * trade.quantity, 2)
                db.add(StrategyTrade(
                    strategy_id=strategy.id,
                    agent_id=agent_id,
                    sequence=trade.sequence,
                    symbol=trade.symbol,
                    exchange=trade.exchange,
                    direction=trade.direction,
                    order_type=trade.order_type,
                    product_type=trade.product_type,
                    quantity=trade.quantity,
                    entry_price=trade.entry_price,
                    stop_loss=trade.stop_loss,
                    take_profit=trade.take_profit,
                    risk_amount=risk,
                    rationale=trade.rationale,
                    status="PENDING",
                ))

            return strategy.id

    async def approve(self, strategy_id: str, max_loss_approved: float, note: Optional[str] = None) -> dict:
        """
        User approves a strategy with a loss cap.
        Immediately triggers autonomous execution of all pending trades.
        """
        from sol.database import get_session
        from sol.models.strategy import Strategy
        from sol.core.strategy_executor import get_strategy_executor
        from sqlalchemy import select

        if max_loss_approved <= 0:
            return {"success": False, "reason": "max_loss_approved must be greater than 0"}

        async with get_session() as db:
            result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
            strategy = result.scalar_one_or_none()
            if not strategy:
                return {"success": False, "reason": f"Strategy {strategy_id} not found"}
            if strategy.status != "PENDING_APPROVAL":
                return {"success": False, "reason": f"Strategy is already {strategy.status}"}

            strategy.max_loss_approved = max_loss_approved
            strategy.status = "ACTIVE"
            strategy.approved_at = datetime.now(IST)
            strategy.user_note = note

        logger.info(
            f"Strategy '{strategy.name}' approved. Max loss cap: ₹{max_loss_approved:.2f}"
        )

        # Kick off autonomous execution in the background
        executor = get_strategy_executor()
        await executor.execute_strategy(strategy_id)

        return {"success": True, "strategy_id": strategy_id, "max_loss_approved": max_loss_approved}

    async def reject(self, strategy_id: str, note: Optional[str] = None) -> dict:
        from sol.database import get_session
        from sol.models.strategy import Strategy, StrategyTrade
        from sqlalchemy import select, update

        async with get_session() as db:
            result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
            strategy = result.scalar_one_or_none()
            if not strategy:
                return {"success": False, "reason": "Not found"}

            strategy.status = "CANCELLED"
            strategy.user_note = note

            await db.execute(
                update(StrategyTrade)
                .where(StrategyTrade.strategy_id == strategy_id, StrategyTrade.status == "PENDING")
                .values(status="CANCELLED", skip_reason="Strategy rejected by user")
            )

        return {"success": True}

    async def get_pending(self) -> list[StrategyOut]:
        from sol.database import get_session
        from sol.models.strategy import Strategy, StrategyTrade
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(Strategy)
                .where(Strategy.status == "PENDING_APPROVAL")
                .order_by(Strategy.proposed_at.desc())
            )
            strategies = result.scalars().all()
            return [await self._to_out(s, db) for s in strategies]

    async def get_all(self, limit: int = 50) -> list[StrategyOut]:
        from sol.database import get_session
        from sol.models.strategy import Strategy
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(Strategy).order_by(Strategy.proposed_at.desc()).limit(limit)
            )
            strategies = result.scalars().all()
            return [await self._to_out(s, db) for s in strategies]

    async def _to_out(self, strategy, db) -> StrategyOut:
        from sol.models.strategy import StrategyTrade
        from sol.schemas.strategy import StrategyTradeOut
        from sqlalchemy import select

        result = await db.execute(
            select(StrategyTrade)
            .where(StrategyTrade.strategy_id == strategy.id)
            .order_by(StrategyTrade.sequence)
        )
        trades = [StrategyTradeOut.model_validate(t) for t in result.scalars().all()]
        out = StrategyOut.model_validate(strategy)
        out.trades = trades
        return out

    async def update_actual_loss(self, strategy_id: str, pnl_delta: float) -> bool:
        """
        Called when a strategy trade closes with a loss.
        Returns True if the loss cap has been hit (caller should halt remaining trades).
        """
        from sol.database import get_session
        from sol.models.strategy import Strategy
        from sol.core.event_bus import notify_risk_alert, publish_event
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
            strategy = result.scalar_one_or_none()
            if not strategy or strategy.status != "ACTIVE":
                return False

            if pnl_delta < 0:
                strategy.actual_loss = round(float(strategy.actual_loss or 0) - pnl_delta, 2)

            cap = float(strategy.max_loss_approved or 0)
            actual = float(strategy.actual_loss or 0)
            cap_hit = cap > 0 and actual >= cap

            if cap_hit:
                strategy.status = "MAX_LOSS_HIT"
                strategy.completed_at = datetime.now(IST)
                logger.warning(
                    f"Strategy '{strategy.name}' hit max loss cap: "
                    f"₹{actual:.2f} >= ₹{cap:.2f}"
                )
                await notify_risk_alert(
                    f"Strategy '{strategy.name}' stopped — max loss of ₹{cap:.2f} reached.",
                    level="ERROR",
                )

            await db.flush()
            return cap_hit


_strategy_service: Optional[StrategyService] = None


def get_strategy_service() -> StrategyService:
    global _strategy_service
    if _strategy_service is None:
        _strategy_service = StrategyService()
    return _strategy_service
