"""Proposal service — CRUD for trade proposals."""

import logging
from datetime import datetime
from typing import Optional

import pytz

from sol.schemas.trade import TradeProposalOut

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class ProposalService:
    async def get_pending(self) -> list[TradeProposalOut]:
        from sol.database import get_session
        from sol.models.trade import TradeProposal
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(TradeProposal)
                .where(TradeProposal.status == "PENDING")
                .order_by(TradeProposal.proposed_at.desc())
            )
            proposals = result.scalars().all()
            return [TradeProposalOut.model_validate(p) for p in proposals]

    async def get_all(self, limit: int = 50) -> list[TradeProposalOut]:
        from sol.database import get_session
        from sol.models.trade import TradeProposal
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(TradeProposal)
                .order_by(TradeProposal.proposed_at.desc())
                .limit(limit)
            )
            proposals = result.scalars().all()
            return [TradeProposalOut.model_validate(p) for p in proposals]

    async def approve(self, proposal_id: str, note: Optional[str] = None) -> dict:
        """Approve and execute a trade proposal."""
        from sol.database import get_session
        from sol.models.trade import TradeProposal
        from sol.models.position import Position
        from sol.services.risk_service import get_risk_service
        from sol.broker.order_manager import get_order_manager
        from sol.schemas.trade import TradeProposalCreate
        from sol.core.event_bus import notify_trade_executed
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(select(TradeProposal).where(TradeProposal.id == proposal_id))
            proposal = result.scalar_one_or_none()

            if not proposal:
                raise ValueError(f"Proposal {proposal_id} not found")
            if proposal.status != "PENDING":
                raise ValueError(f"Proposal {proposal_id} is not in PENDING state (current: {proposal.status})")

            # Re-validate risk at execution time
            proposal_create = TradeProposalCreate(
                symbol=proposal.symbol,
                exchange=proposal.exchange,
                direction=proposal.direction,
                order_type=proposal.order_type,
                product_type=proposal.product_type,
                quantity=proposal.quantity,
                entry_price=proposal.entry_price,
                stop_loss=proposal.stop_loss,
                take_profit=proposal.take_profit,
                rationale=proposal.rationale,
            )

            risk_service = get_risk_service()
            risk_report = await risk_service.validate_proposal(proposal_create)

            if not risk_report.approved:
                proposal.status = "BLOCKED"
                proposal.risk_violations = str(risk_report.violations)
                proposal.reviewed_at = datetime.now(IST)
                await db.flush()
                return {"success": False, "reason": risk_report.message, "violations": risk_report.violations}

            # Execute the order
            om = get_order_manager()
            order_id = await om.execute_proposal(proposal, risk_report)

            # Update proposal
            proposal.status = "EXECUTED"
            proposal.kite_order_id = order_id
            proposal.reviewed_at = datetime.now(IST)
            proposal.executed_at = datetime.now(IST)
            proposal.user_note = note

            # Create position record
            position = Position(
                proposal_id=proposal.id,
                agent_id=proposal.agent_id,
                agent_name=proposal.agent_name,
                is_virtual=proposal.is_virtual,
                symbol=proposal.symbol,
                exchange=proposal.exchange,
                direction=proposal.direction,
                product_type=proposal.product_type,
                quantity=risk_report.modified_quantity or proposal.quantity,
                avg_price=proposal.entry_price or 0.0,
                stop_loss=proposal.stop_loss,
                take_profit=proposal.take_profit,
                opened_at=datetime.now(IST),
                status="OPEN",
            )
            db.add(position)
            await db.flush()

            await notify_trade_executed(proposal_id, order_id)
            logger.info(f"Proposal {proposal_id} approved and executed as {order_id}")

            return {
                "success": True,
                "order_id": order_id,
                "position_id": position.id,
                "quantity": position.quantity,
            }

    async def reject(self, proposal_id: str, note: Optional[str] = None) -> dict:
        from sol.database import get_session
        from sol.models.trade import TradeProposal
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(select(TradeProposal).where(TradeProposal.id == proposal_id))
            proposal = result.scalar_one_or_none()

            if not proposal:
                raise ValueError(f"Proposal {proposal_id} not found")

            proposal.status = "REJECTED"
            proposal.user_note = note
            proposal.reviewed_at = datetime.now(IST)
            await db.flush()

        return {"success": True}


_proposal_service: Optional[ProposalService] = None


def get_proposal_service() -> ProposalService:
    global _proposal_service
    if _proposal_service is None:
        _proposal_service = ProposalService()
    return _proposal_service
