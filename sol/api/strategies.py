"""Strategy endpoints — list pending strategies, approve with loss cap, reject."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from sol.schemas.strategy import StrategyApproval, StrategyOut

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyOut])
async def list_strategies(status: Optional[str] = Query(None)):
    from sol.services.strategy_service import get_strategy_service
    svc = get_strategy_service()
    if status == "pending":
        return await svc.get_pending()
    return await svc.get_all()


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get_strategy(strategy_id: str):
    from sol.database import get_session
    from sol.models.strategy import Strategy
    from sol.services.strategy_service import get_strategy_service
    from sqlalchemy import select

    svc = get_strategy_service()
    async with get_session() as db:
        result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
        strategy = result.scalar_one_or_none()
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return await svc._to_out(strategy, db)


@router.post("/{strategy_id}/approve")
async def approve_strategy(strategy_id: str, body: StrategyApproval):
    from sol.services.strategy_service import get_strategy_service
    svc = get_strategy_service()
    result = await svc.approve(strategy_id, body.max_loss_approved, body.note)
    if not result["success"]:
        raise HTTPException(status_code=422, detail=result.get("reason", "Approval failed"))
    return result


@router.post("/{strategy_id}/reject")
async def reject_strategy(strategy_id: str, note: Optional[str] = None):
    from sol.services.strategy_service import get_strategy_service
    svc = get_strategy_service()
    result = await svc.reject(strategy_id, note)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("reason", "Not found"))
    return result


@router.post("/clear-all")
async def clear_all_strategies():
    """Cancel and delete all non-active strategies (PENDING_APPROVAL and already-done ones)."""
    from sol.database import get_session
    from sol.models.strategy import Strategy, StrategyTrade
    from sqlalchemy import select, delete

    async with get_session() as db:
        result = await db.execute(
            select(Strategy).where(Strategy.status.in_(["PENDING_APPROVAL", "COMPLETED", "CANCELLED", "MAX_LOSS_HIT"]))
        )
        strategies = result.scalars().all()
        ids = [s.id for s in strategies]
        if ids:
            await db.execute(delete(StrategyTrade).where(StrategyTrade.strategy_id.in_(ids)))
            await db.execute(delete(Strategy).where(Strategy.id.in_(ids)))
    return {"deleted": len(ids)}


@router.post("/{strategy_id}/backtest")
async def backtest_strategy(strategy_id: str):
    """Run the strategy's trades against 90 days of historical OHLCV and return win/loss stats."""
    from sol.services.backtest_service import backtest_strategy as run_backtest
    result = await run_backtest(strategy_id)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result
