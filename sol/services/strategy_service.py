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
        from sol.broker.order_manager import get_order_manager

        # Cap max_loss_possible at actual available capital
        try:
            available_capital = get_order_manager().get_available_capital()
        except Exception:
            available_capital = None

        max_loss = proposal.max_loss_possible
        if max_loss and available_capital and max_loss > available_capital:
            logger.warning(
                f"Strategy '{proposal.name}' max_loss_possible ₹{max_loss:.0f} "
                f"exceeds available capital ₹{available_capital:.0f} — capping"
            )
            max_loss = round(available_capital * 0.90)  # cap at 90% of capital

        async with get_session() as db:
            strategy = Strategy(
                agent_id=agent_id,
                agent_name=agent_name,
                name=proposal.name,
                description=proposal.description,
                rationale=proposal.rationale,
                duration_days=proposal.duration_days,
                max_loss_possible=max_loss,
                status="PENDING_APPROVAL",
                proposed_at=datetime.now(IST),
                is_virtual=is_virtual,
            )
            db.add(strategy)
            await db.flush()  # get strategy.id

            for trade in sorted(proposal.trades, key=lambda t: t.sequence):
                # Resolve lot size
                lot_size = 1
                if trade.exchange == "NFO":
                    from sol.services.option_chain_service import DEFAULT_LOT_SIZES
                    for name, ls in DEFAULT_LOT_SIZES.items():
                        if trade.symbol.startswith(name):
                            lot_size = ls
                            break
                    if lot_size == 1:
                        lot_size = 75  # safe fallback (NIFTY)

                # Cap quantity so notional stays within available capital
                qty = trade.quantity
                if trade.entry_price and available_capital:
                    entry = float(trade.entry_price)
                    notional = entry * lot_size  # cost of 1 lot / 1 share
                    if notional > 0:
                        max_affordable_qty = int(available_capital / notional)
                        if max_affordable_qty < 1 and notional <= available_capital * 2:
                            max_affordable_qty = 1  # allow 1 if close enough
                        if max_affordable_qty < 1:
                            logger.warning(
                                f"Trade {trade.symbol} unaffordable: 1 lot costs ₹{notional:.0f}, capital ₹{available_capital:.0f} — skipping"
                            )
                            continue
                        if qty > max_affordable_qty:
                            logger.info(
                                f"Reducing {trade.symbol} qty from {qty} to {max_affordable_qty} lots (capital constraint: ₹{available_capital:.0f})"
                            )
                            qty = max_affordable_qty

                risk = 0.0
                if trade.entry_price and trade.stop_loss:
                    risk = round(abs(float(trade.entry_price) - float(trade.stop_loss)) * qty * lot_size, 2)
                db.add(StrategyTrade(
                    strategy_id=strategy.id,
                    agent_id=agent_id,
                    sequence=trade.sequence,
                    symbol=trade.symbol,
                    exchange=trade.exchange,
                    direction=trade.direction,
                    order_type=trade.order_type,
                    product_type=trade.product_type,
                    quantity=qty,
                    entry_price=trade.entry_price,
                    stop_loss=trade.stop_loss,
                    take_profit=trade.take_profit,
                    risk_amount=risk,
                    rationale=trade.rationale,
                    status="PENDING",
                ))

            return strategy.id

    async def _check_staleness(self, strategy_id: str) -> Optional[str]:
        """
        Check if trade entry prices are still valid at approval time.
        Returns an error string if stale, None if OK.
        """
        from sol.database import get_session
        from sol.models.strategy import StrategyTrade
        from sol.broker.price_store import get_price
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(StrategyTrade).where(
                    StrategyTrade.strategy_id == strategy_id,
                    StrategyTrade.status == "PENDING",
                )
            )
            trades = result.scalars().all()

        stale = []
        for trade in trades:
            if trade.entry_price is None:
                continue  # MARKET order — no staleness check possible

            entry = float(trade.entry_price)
            sl = float(trade.stop_loss) if trade.stop_loss else None
            tp = float(trade.take_profit) if trade.take_profit else None

            # Try price store (in-memory cache updated each cycle)
            key = f"{trade.exchange}:{trade.symbol}"
            current = get_price(key)
            if current is None:
                continue  # No price data — skip check rather than block

            current = float(current)
            threshold = 0.01  # 1% max adverse move from intended entry

            if trade.direction == "BUY":
                if sl and current <= sl:
                    stale.append(f"{trade.symbol}: price ₹{current:.2f} already at/below SL ₹{sl:.2f}")
                elif tp and current >= tp:
                    stale.append(f"{trade.symbol}: price ₹{current:.2f} already at/above TP ₹{tp:.2f}")
                elif current > entry * (1 + threshold):
                    stale.append(
                        f"{trade.symbol}: price ₹{current:.2f} is {((current/entry)-1)*100:.1f}% "
                        f"above proposed entry ₹{entry:.2f} — entry missed, R:R broken"
                    )
            else:  # SELL
                if sl and current >= sl:
                    stale.append(f"{trade.symbol}: price ₹{current:.2f} already at/above SL ₹{sl:.2f}")
                elif tp and current <= tp:
                    stale.append(f"{trade.symbol}: price ₹{current:.2f} already at/below TP ₹{tp:.2f}")
                elif current < entry * (1 - threshold):
                    stale.append(
                        f"{trade.symbol}: price ₹{current:.2f} is {((entry/current)-1)*100:.1f}% "
                        f"below proposed entry ₹{entry:.2f} — entry missed, R:R broken"
                    )

        if stale:
            return "Stale entry prices: " + "; ".join(stale)
        return None

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

        stale_reason = await self._check_staleness(strategy_id)
        if stale_reason:
            return {"success": False, "reason": stale_reason, "stale": True}

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
