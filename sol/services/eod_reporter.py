"""End-of-day report generator."""

import logging
from datetime import datetime

import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


async def generate_eod_report():
    from sol.database import get_session
    from sol.models.position import Position
    from sol.models.trade import TradeProposal
    from sol.core.orchestrator import get_orchestrator
    from sol.core.event_bus import notify_eod_report
    from sqlalchemy import select, func

    today = datetime.now(IST).date()

    async with get_session() as db:
        # Get today's closed positions
        result = await db.execute(
            select(Position).where(
                func.date(Position.closed_at) == today,
                Position.status != "OPEN",
            )
        )
        closed_positions = result.scalars().all()

        # Get today's executed trades
        result2 = await db.execute(
            select(TradeProposal).where(
                TradeProposal.status == "EXECUTED",
                func.date(TradeProposal.executed_at) == today,
            )
        )
        executed_trades = result2.scalars().all()

    trades_data = [
        {
            "symbol": t.symbol,
            "direction": t.direction,
            "quantity": t.quantity,
            "agent": t.agent_name,
        }
        for t in executed_trades
    ]

    positions_data = [
        {
            "symbol": p.symbol,
            "direction": p.direction,
            "status": p.status,
            "realized_pnl": p.realized_pnl or 0,
            "agent": p.agent_name,
        }
        for p in closed_positions
    ]

    orchestrator = get_orchestrator()
    report = await orchestrator.generate_eod_report(trades_data, positions_data)

    total_pnl = sum(p.realized_pnl or 0 for p in closed_positions)
    logger.info(f"EOD Report generated. Total P&L today: ₹{total_pnl:.2f}")

    await notify_eod_report(report)
    return report
