"""Portfolio and positions endpoints."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/positions")
async def get_positions():
    from sol.database import get_session
    from sol.models.position import Position
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(Position).where(Position.status == "OPEN"))
        positions = result.scalars().all()
        return [
            {
                "id": p.id,
                "symbol": p.symbol,
                "exchange": p.exchange,
                "direction": p.direction,
                "quantity": p.quantity,
                "avg_price": p.avg_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "product_type": p.product_type,
                "agent_name": p.agent_name,
                "is_virtual": p.is_virtual,
                "opened_at": p.opened_at,
            }
            for p in positions
        ]


@router.post("/positions/{position_id}/close")
async def close_position(position_id: str):
    from sol.database import get_session
    from sol.models.position import Position
    from sol.broker.order_manager import get_order_manager
    from sol.services.position_monitor import _close_position
    from sol.broker.price_store import get_price
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(Position).where(Position.id == position_id))
        pos = result.scalar_one_or_none()
        if not pos:
            raise HTTPException(status_code=404, detail="Position not found")
        if pos.status != "OPEN":
            raise HTTPException(status_code=400, detail=f"Position is already {pos.status}")

        current_price = get_price(f"{pos.exchange}:{pos.symbol}") or pos.avg_price

        om = get_order_manager()
        order_id = await om.close_position(
            symbol=pos.symbol,
            exchange=pos.exchange,
            quantity=pos.quantity,
            direction=pos.direction,
            product_type=pos.product_type,
        )
        await _close_position(db, pos, current_price, "CLOSED")
        await db.flush()

    return {"success": True, "order_id": order_id, "realized_pnl": pos.realized_pnl}


@router.get("/trades")
async def get_trades(limit: int = 100):
    """All closed/exited positions — the trade history book."""
    from sol.database import get_session
    from sol.models.position import Position
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(
            select(Position)
            .where(Position.status != "OPEN")
            .order_by(Position.closed_at.desc())
            .limit(limit)
        )
        positions = result.scalars().all()
        return [
            {
                "id": p.id,
                "symbol": p.symbol,
                "exchange": p.exchange,
                "direction": p.direction,
                "quantity": p.quantity,
                "product_type": p.product_type,
                "option_type": p.option_type,
                "avg_price": float(p.avg_price),
                "close_price": float(p.close_price) if p.close_price else None,
                "stop_loss": float(p.stop_loss) if p.stop_loss else None,
                "take_profit": float(p.take_profit) if p.take_profit else None,
                "realized_pnl": float(p.realized_pnl) if p.realized_pnl is not None else None,
                "status": p.status,
                "agent_name": p.agent_name,
                "is_virtual": p.is_virtual,
                "opened_at": p.opened_at,
                "closed_at": p.closed_at,
            }
            for p in positions
        ]


@router.get("/summary")
async def portfolio_summary():
    """Aggregated portfolio summary — real + virtual."""
    from sol.broker.order_manager import get_order_manager
    from sol.database import get_session
    from sol.models.position import Position
    from sol.config import get_settings
    from sqlalchemy import select, func
    from datetime import datetime
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
    today = datetime.now(IST).date()

    settings = get_settings()
    om = get_order_manager()
    available_capital = om.get_available_capital()

    async with get_session() as db:
        # Open positions
        result = await db.execute(select(Position).where(Position.status == "OPEN"))
        open_positions = result.scalars().all()

        # Today's realized P&L
        result2 = await db.execute(
            select(func.sum(Position.realized_pnl)).where(
                func.date(Position.closed_at) == today
            )
        )
        today_realized = float(result2.scalar() or 0)

    unrealized = sum(p.unrealized_pnl for p in open_positions)
    total_pnl = today_realized + unrealized

    return {
        "mode": "PAPER" if settings.PAPER_TRADING_MODE else "LIVE",
        "available_capital": available_capital,
        "open_positions_count": len(open_positions),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl_today": round(today_realized, 2),
        "total_pnl_today": round(total_pnl, 2),
    }
