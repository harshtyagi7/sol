"""Portfolio and positions endpoints."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/positions")
async def get_positions():
    from sol.database import get_session
    from sol.models.position import Position
    from sol.core.trading_mode import get_paper_mode
    from sqlalchemy import select

    is_virtual = get_paper_mode()
    async with get_session() as db:
        result = await db.execute(
            select(Position).where(Position.status == "OPEN", Position.is_virtual == is_virtual)
        )
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
    from sol.core.trading_mode import get_paper_mode
    from sqlalchemy import select

    is_virtual = get_paper_mode()
    async with get_session() as db:
        result = await db.execute(
            select(Position)
            .where(Position.status != "OPEN", Position.is_virtual == is_virtual)
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


@router.post("/sync-from-kite")
async def sync_positions_from_kite():
    """
    Reconcile our DB with Kite's actual position data.
    For every live OPEN position in DB, check if Kite shows it as closed/squared off.
    Useful after market close or if the position monitor missed an exit.
    """
    from sol.database import get_session
    from sol.models.position import Position
    from sol.broker.kite_client import get_kite_client
    from sqlalchemy import select
    from datetime import datetime
    import pytz

    IST = pytz.timezone("Asia/Kolkata")

    # Always reload the latest token from DB to handle re-logins
    from sol.database import get_session as _gs
    from sol.models.session import KiteSession
    from sol.utils.encryption import decrypt
    from sol.config import get_settings
    from sqlalchemy import select as _sel
    _settings = get_settings()
    async with _gs() as _db:
        _result = await _db.execute(
            _sel(KiteSession).where(KiteSession.is_valid == True).order_by(KiteSession.created_at.desc()).limit(1)
        )
        _session = _result.scalar_one_or_none()
    if not _session:
        raise HTTPException(status_code=400, detail="Kite not authenticated — please login first")
    client = get_kite_client()
    client.set_access_token(decrypt(_session.access_token_encrypted, _settings.SECRET_KEY))

    # Fetch Kite's current position snapshot
    try:
        kite_positions = client.get_positions()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite API error: {e}")

    # Build lookup: symbol -> kite position data (day + net)
    kite_day: dict = {}
    kite_net: dict = {}
    for p in kite_positions.get("day", []):
        key = p["tradingsymbol"]
        kite_day[key] = p
    for p in kite_positions.get("net", []):
        key = p["tradingsymbol"]
        kite_net[key] = p

    # Also fetch today's executed trades from Kite for fill prices
    try:
        kite_trades = client.get_trades()
    except Exception:
        kite_trades = []

    # Build trade lookup: symbol -> list of trades
    kite_trade_map: dict = {}
    for t in kite_trades:
        sym = t.get("tradingsymbol", "")
        kite_trade_map.setdefault(sym, []).append(t)

    # Fetch our live OPEN positions
    async with get_session() as db:
        result = await db.execute(
            select(Position).where(Position.status == "OPEN", Position.is_virtual == False)
        )
        open_positions = result.scalars().all()

    if not open_positions:
        return {"synced": 0, "message": "No open live positions to sync"}

    synced = []
    for pos in open_positions:
        kp_day = kite_day.get(pos.symbol)
        kp_net = kite_net.get(pos.symbol)

        # A MIS position that's been squared off shows quantity=0 in day positions
        # A position not found in Kite at all also means it's closed
        kite_qty = None
        kite_pnl = None
        kite_last_price = None

        if kp_day is not None:
            kite_qty = abs(int(kp_day.get("quantity", 0)))
            kite_pnl = float(kp_day.get("pnl", 0))
            kite_last_price = float(kp_day.get("last_price", 0)) or None

        # Determine close price: use last known trade fill price if available
        close_price = kite_last_price or float(pos.current_price or pos.avg_price)
        trades_for_sym = kite_trade_map.get(pos.symbol, [])
        # Find the closing trade (opposite direction to our entry)
        close_direction = "BUY" if pos.direction == "SELL" else "SELL"
        closing_trades = [t for t in trades_for_sym if t.get("transaction_type") == close_direction]
        if closing_trades:
            # Use the most recent closing trade's average price
            closing_trades.sort(key=lambda t: t.get("order_timestamp", ""), reverse=True)
            avg_fill = closing_trades[0].get("average_price")
            if avg_fill and float(avg_fill) > 0:
                close_price = float(avg_fill)

        # If Kite shows qty=0 for this symbol, it's been squared off
        is_squared_off = (kite_qty is not None and kite_qty == 0)
        # Or if the symbol doesn't appear in day positions at all (e.g. expired/delisted)
        not_in_kite = (kp_day is None and kp_net is None)

        if is_squared_off or not_in_kite:
            realized = kite_pnl if kite_pnl is not None else (
                (close_price - float(pos.avg_price)) * pos.quantity * (1 if pos.direction == "BUY" else -1)
            )

            async with get_session() as db:
                result = await db.execute(select(Position).where(Position.id == pos.id))
                p = result.scalar_one_or_none()
                if p and p.status == "OPEN":
                    p.status = "SQUAREDOFF"
                    p.close_price = close_price
                    p.realized_pnl = realized
                    p.closed_at = datetime.now(IST)
                    p.current_price = close_price

            synced.append({
                "symbol": pos.symbol,
                "direction": pos.direction,
                "close_price": close_price,
                "realized_pnl": round(realized, 2),
                "source": "kite_sync",
            })

    return {
        "synced": len(synced),
        "positions": synced,
        "message": f"Synced {len(synced)} position(s) from Kite" if synced else "All positions already up to date",
    }


@router.get("/summary")
async def portfolio_summary():
    """Aggregated portfolio summary — real + virtual."""
    from sol.broker.order_manager import get_order_manager
    from sol.database import get_session
    from sol.models.position import Position
    from sqlalchemy import select, func
    from datetime import datetime
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
    today = datetime.now(IST).date()

    from sol.core.trading_mode import get_paper_mode
    is_virtual = get_paper_mode()

    om = get_order_manager()
    available_capital = om.get_available_capital()

    async with get_session() as db:
        # Open positions for current mode only
        result = await db.execute(
            select(Position).where(Position.status == "OPEN", Position.is_virtual == is_virtual)
        )
        open_positions = result.scalars().all()

        # Today's realized P&L for current mode only
        result2 = await db.execute(
            select(func.sum(Position.realized_pnl)).where(
                func.date(Position.closed_at) == today,
                Position.is_virtual == is_virtual,
            )
        )
        today_realized = float(result2.scalar() or 0)

    unrealized = sum(p.unrealized_pnl for p in open_positions)
    total_pnl = today_realized + unrealized

    return {
        "mode": "PAPER" if is_virtual else "LIVE",
        "available_capital": available_capital,
        "open_positions_count": len(open_positions),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl_today": round(today_realized, 2),
        "total_pnl_today": round(total_pnl, 2),
    }
