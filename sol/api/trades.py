"""Trade proposal endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from sol.schemas.trade import TradeReviewAction

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/proposals")
async def list_proposals(status: Optional[str] = Query(None)):
    from sol.services.proposal_service import get_proposal_service
    svc = get_proposal_service()
    if status == "pending" or status is None:
        return await svc.get_pending()
    return await svc.get_all()


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str):
    from sol.database import get_session
    from sol.models.trade import TradeProposal
    from sol.schemas.trade import TradeProposalOut
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(TradeProposal).where(TradeProposal.id == proposal_id))
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return TradeProposalOut.model_validate(proposal)


@router.post("/proposals/{proposal_id}/review")
async def review_proposal(proposal_id: str, action: TradeReviewAction):
    from sol.services.proposal_service import get_proposal_service

    svc = get_proposal_service()

    if action.action == "approve":
        result = await svc.approve(proposal_id, note=action.note)
        if not result["success"]:
            raise HTTPException(status_code=422, detail=result.get("reason", "Risk validation failed"))
        return result

    elif action.action == "reject":
        return await svc.reject(proposal_id, note=action.note)

    elif action.action == "modify":
        # Update proposal fields then approve
        from sol.database import get_session
        from sol.models.trade import TradeProposal
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(select(TradeProposal).where(TradeProposal.id == proposal_id))
            proposal = result.scalar_one_or_none()
            if not proposal:
                raise HTTPException(status_code=404, detail="Proposal not found")

            if action.quantity:
                proposal.quantity = action.quantity
            if action.stop_loss:
                proposal.stop_loss = action.stop_loss
            if action.take_profit:
                proposal.take_profit = action.take_profit
            if action.entry_price:
                proposal.entry_price = action.entry_price
            await db.flush()

        return await svc.approve(proposal_id, note=action.note)

    raise HTTPException(status_code=400, detail="Invalid action")


@router.get("/history")
async def trade_history(limit: int = Query(50, le=200)):
    from sol.services.proposal_service import get_proposal_service
    svc = get_proposal_service()
    return await svc.get_all(limit=limit)
