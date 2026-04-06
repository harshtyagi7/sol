"""Dashboard aggregation endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard():
    """Single endpoint that returns everything the dashboard needs."""
    from sol.broker.order_manager import get_order_manager
    from sol.agents.agent_manager import get_agent_manager
    from sol.services.risk_service import get_risk_service
    from sol.utils.market_hours import market_status_str, is_market_open
    from sol.database import get_session
    from sol.models.position import Position
    from sol.models.trade import TradeProposal
    from sqlalchemy import select, func
    from datetime import datetime
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
    today = datetime.now(IST).date()

    from sol.core.trading_mode import get_paper_mode
    om = get_order_manager()
    risk_service = get_risk_service()
    is_virtual = get_paper_mode()

    available_capital = om.get_available_capital()
    risk_summary = await risk_service.get_exposure_report()
    agent_performance = await get_agent_manager().get_all_performance()

    async with get_session() as db:
        # Open positions — filtered by current mode
        result = await db.execute(
            select(Position).where(Position.status == "OPEN", Position.is_virtual == is_virtual)
        )
        open_positions = result.scalars().all()

        # Pending proposals
        result2 = await db.execute(
            select(func.count()).select_from(TradeProposal).where(TradeProposal.status == "PENDING")
        )
        pending_count = result2.scalar() or 0

        # Today's executed trades
        result3 = await db.execute(
            select(func.count()).select_from(TradeProposal).where(
                TradeProposal.status == "EXECUTED",
                func.date(TradeProposal.executed_at) == today,
            )
        )
        executed_today = result3.scalar() or 0

        # Today's P&L — filtered by current mode
        result4 = await db.execute(
            select(func.sum(Position.realized_pnl)).where(
                func.date(Position.closed_at) == today,
                Position.is_virtual == is_virtual,
            )
        )
        realized_pnl = float(result4.scalar() or 0)

    unrealized_pnl = sum(p.unrealized_pnl for p in open_positions)

    return {
        "market": {
            "status": market_status_str(),
            "is_open": is_market_open(),
            "time_ist": datetime.now(IST).strftime("%H:%M:%S"),
        },
        "mode": "PAPER" if is_virtual else "LIVE",
        "portfolio": {
            "available_capital": available_capital,
            "open_positions": len(open_positions),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "realized_pnl_today": round(realized_pnl, 2),
            "total_pnl_today": round(realized_pnl + unrealized_pnl, 2),
        },
        "risk": risk_summary,
        "activity": {
            "pending_proposals": pending_count,
            "executed_today": executed_today,
        },
        "agents": agent_performance,
    }
