"""
Position monitor — runs each analysis cycle during market hours.

For every open position:
1. Fetch current price and update DB.
2. Mechanical check: if SL or TP is hit, exit immediately (no agent needed).
3. If still open, ask the originating agent: EXIT or HOLD?
4. If agent says EXIT, place close order and mark position closed.
"""

import logging
from datetime import datetime, timezone

import pytz  # type: ignore[import]

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


async def run_position_monitor(snapshots: list) -> None:
    """Called from cycle_runner once per cycle, before new strategy proposals."""
    try:
        from sol.database import get_session  # type: ignore[import]
        from sol.models.position import Position  # type: ignore[import]
        from sqlalchemy import select  # type: ignore[import]

        async with get_session() as db:
            result = await db.execute(select(Position).where(Position.status == "OPEN"))
            positions = result.scalars().all()
    except Exception as e:
        logger.error(f"[PositionMonitor] Could not fetch open positions: {e}")
        return

    if not positions:
        return

    logger.info(f"[PositionMonitor] Checking {len(positions)} open position(s)")

    snap_map: dict = {s.symbol: s for s in snapshots}

    for position in positions:
        try:
            await _check_position(position, snap_map)
        except Exception as e:
            logger.error(f"[PositionMonitor] Error checking {position.symbol}: {e}")


async def _get_current_price(symbol: str, exchange: str, snap_map: dict):
    snap = snap_map.get(symbol)
    if snap is not None:
        return float(snap.current_price)

    try:
        from sol.broker.kite_client import get_kite_client  # type: ignore[import]
        client = get_kite_client()
        if not client.is_authenticated():
            return None
        s = symbol.upper()
        key = f"NFO:{s}" if (s.endswith("CE") or s.endswith("PE") or s.endswith("FUT")) else f"{exchange}:{s}"
        quotes = client.get_ltp([key])
        ltp = quotes.get(key, {}).get("last_price")
        return float(ltp) if ltp is not None else None
    except Exception as e:
        logger.warning(f"[PositionMonitor] Could not fetch LTP for {symbol}: {e}")
        return None


async def _check_position(position, snap_map: dict) -> None:
    from sol.database import get_session  # type: ignore[import]
    from sol.models.position import Position  # type: ignore[import]
    from sol.core.event_bus import publish_event  # type: ignore[import]
    from sqlalchemy import select  # type: ignore[import]

    cur_price: float | None = await _get_current_price(position.symbol, position.exchange, snap_map)  # type: ignore[assignment]
    if cur_price is None:
        logger.warning(f"[PositionMonitor] No price for {position.symbol} — skipping")
        return

    # Update current_price in DB
    async with get_session() as db:
        result = await db.execute(select(Position).where(Position.id == position.id))
        pos = result.scalar_one_or_none()
        if pos is None or pos.status != "OPEN":
            return
        pos.current_price = cur_price

    unrealized_pnl = _calc_pnl(position.direction, cur_price, float(position.avg_price), position.quantity)

    # --- Mechanical SL/TP check ---
    sl = float(position.stop_loss) if position.stop_loss else None
    tp = float(position.take_profit) if position.take_profit else None

    if position.direction == "BUY":
        if sl and cur_price <= sl:
            await _close_position(position, cur_price, unrealized_pnl, "SL_HIT",
                                  f"Stop-loss hit at ₹{cur_price:.2f} (SL: ₹{sl:.2f})")
            return
        if tp and cur_price >= tp:
            await _close_position(position, cur_price, unrealized_pnl, "TP_HIT",
                                  f"Take-profit hit at ₹{cur_price:.2f} (TP: ₹{tp:.2f})")
            return
    else:
        if sl and cur_price >= sl:
            await _close_position(position, cur_price, unrealized_pnl, "SL_HIT",
                                  f"Stop-loss hit at ₹{cur_price:.2f} (SL: ₹{sl:.2f})")
            return
        if tp and cur_price <= tp:
            await _close_position(position, cur_price, unrealized_pnl, "TP_HIT",
                                  f"Take-profit hit at ₹{cur_price:.2f} (TP: ₹{tp:.2f})")
            return

    # --- Agent EXIT/HOLD review ---
    original_rationale = await _get_original_rationale(position)
    hours_held = _hours_since(position.opened_at)

    position_dict = {
        "symbol": position.symbol,
        "exchange": position.exchange,
        "direction": position.direction,
        "quantity": position.quantity,
        "avg_price": float(position.avg_price),
        "current_price": cur_price,
        "stop_loss": sl,
        "take_profit": tp,
        "unrealized_pnl": unrealized_pnl,
        "hours_held": round(hours_held, 1),  # type: ignore[call-overload]
        "original_rationale": original_rationale,
    }

    symbol_context = _build_symbol_context(position.symbol, position.exchange, cur_price, snap_map)

    agent = await _get_agent(position.agent_id)
    if agent is None:
        return

    should_exit, reason = await agent.should_exit(position_dict, symbol_context)  # type: ignore[union-attr]
    if should_exit:
        logger.info(f"[PositionMonitor] [{agent.name}] EXIT {position.symbol}: {reason}")  # type: ignore[union-attr]
        await _close_position(position, cur_price, unrealized_pnl, "SQUAREDOFF", reason)
        await publish_event("position_exited_by_agent", {
            "symbol": position.symbol,
            "agent": agent.name,  # type: ignore[union-attr]
            "reason": reason,
            "pnl": round(unrealized_pnl, 2),  # type: ignore[call-overload]
        })
    else:
        logger.info(
            f"[PositionMonitor] [{agent.name}] HOLD {position.symbol}: {reason} "  # type: ignore[union-attr]
            f"(P&L: ₹{unrealized_pnl:.2f})"
        )


async def _close_position(position, cur_price: float, pnl: float, status: str, reason: str) -> None:
    from sol.database import get_session  # type: ignore[import]
    from sol.models.position import Position  # type: ignore[import]
    from sol.broker.order_manager import get_order_manager  # type: ignore[import]
    from sol.core.strategy_executor import get_strategy_executor  # type: ignore[import]
    from sol.core.event_bus import publish_event  # type: ignore[import]
    from sqlalchemy import select  # type: ignore[import]

    try:
        om = get_order_manager()
        await om.close_position(
            symbol=position.symbol,
            exchange=position.exchange,
            quantity=position.quantity,
            direction=position.direction,
            product_type=position.product_type,
        )
    except Exception as e:
        logger.error(f"[PositionMonitor] Failed to place close order for {position.symbol}: {e}")
        return

    async with get_session() as db:
        result = await db.execute(select(Position).where(Position.id == position.id))
        pos = result.scalar_one_or_none()
        if pos:
            pos.status = status
            pos.close_price = cur_price
            pos.realized_pnl = pnl
            pos.closed_at = datetime.now(IST)

    if position.proposal_id:
        try:
            from sol.models.strategy import StrategyTrade  # type: ignore[import]
            from sol.database import get_session as _gs  # type: ignore[import]
            from sqlalchemy import select as _sel  # type: ignore[import]
            async with _gs() as db:
                result = await db.execute(_sel(StrategyTrade).where(StrategyTrade.id == position.proposal_id))
                trade = result.scalar_one_or_none()
                if trade and trade.strategy_id:
                    trade.actual_pnl = pnl
                    executor = get_strategy_executor()
                    await executor.on_trade_closed(trade.strategy_id, pnl)
        except Exception as e:
            logger.warning(f"[PositionMonitor] Could not update strategy loss for {position.symbol}: {e}")

    await publish_event("position_closed", {
        "symbol": position.symbol,
        "status": status,
        "reason": reason,
        "close_price": cur_price,
        "realized_pnl": round(pnl, 2),  # type: ignore[call-overload]
    })
    logger.info(f"[PositionMonitor] Closed {position.symbol} [{status}] P&L: ₹{pnl:.2f} — {reason}")


def _calc_pnl(direction: str, cur: float, avg: float, qty: int) -> float:
    mult = 1 if direction == "BUY" else -1
    return mult * (cur - avg) * qty


def _hours_since(opened_at) -> float:
    if opened_at is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    return (now - opened_at).total_seconds() / 3600


async def _get_original_rationale(position) -> str:
    try:
        from sol.database import get_session  # type: ignore[import]
        from sol.models.strategy import StrategyTrade  # type: ignore[import]
        from sqlalchemy import select  # type: ignore[import]
        async with get_session() as db:
            result = await db.execute(select(StrategyTrade).where(StrategyTrade.id == position.proposal_id))
            trade = result.scalar_one_or_none()
            if trade:
                return str(trade.rationale)
    except Exception:
        pass
    return "unknown"


async def _get_agent(agent_id: str):
    try:
        from sol.agents.agent_manager import get_agent_manager  # type: ignore[import]
        return get_agent_manager().get_agent(agent_id)
    except Exception:
        return None


def _build_symbol_context(symbol: str, exchange: str, cur_price: float, snap_map: dict) -> str:
    snap = snap_map.get(symbol)
    if snap is None:
        return f"{exchange}:{symbol} — LTP: ₹{cur_price:.2f} (no additional data)"

    lines = [f"{exchange}:{symbol} — LTP: ₹{cur_price:.2f}"]
    if getattr(snap, "indicators", None):
        import json
        lines.append(f"Indicators: {json.dumps(snap.indicators)}")
    if getattr(snap, "ohlcv_daily", None):
        for c in snap.ohlcv_daily[-3:]:
            lines.append(f"  {c.get('date','')}: C={c.get('close',0):.2f} V={c.get('volume',0)}")
    if getattr(snap, "news_headlines", None):
        lines.append("News:")
        for h in snap.news_headlines[:3]:
            lines.append(f"  - {h}")
    return "\n".join(lines)
