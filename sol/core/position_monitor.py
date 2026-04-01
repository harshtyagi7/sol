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


async def trail_intraday_to_breakeven() -> None:
    """
    Called at 2:00 PM — for all profitable open MIS positions, move SL to entry
    price (breakeven). This locks in that we won't turn a winning intraday trade
    into a loss in the final hour of trading.
    """
    from sol.database import get_session
    from sol.models.position import Position
    from sqlalchemy import select

    try:
        async with get_session() as db:
            result = await db.execute(
                select(Position).where(
                    Position.status == "OPEN",
                    Position.product_type == "MIS",
                )
            )
            positions = result.scalars().all()

        trailed = 0
        for pos in positions:
            pnl = pos.unrealized_pnl
            if pnl <= 0:
                continue  # Only trail profitable positions

            entry = float(pos.avg_price)
            current_sl = float(pos.stop_loss) if pos.stop_loss else None

            # Only move SL if current SL is below entry (for BUY) or above (for SELL)
            should_trail = False
            if pos.direction == "BUY" and (current_sl is None or current_sl < entry):
                should_trail = True
            elif pos.direction == "SELL" and (current_sl is None or current_sl > entry):
                should_trail = True

            if should_trail:
                async with get_session() as db:
                    result = await db.execute(select(Position).where(Position.id == pos.id))
                    p = result.scalar_one_or_none()
                    if p and p.status == "OPEN":
                        p.stop_loss = entry
                        trailed += 1

        if trailed:
            logger.info(f"[2PM Trail] Moved SL to breakeven for {trailed} profitable MIS position(s)")
    except Exception as e:
        logger.error(f"[2PM Trail] Error: {e}")


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
    # Always try live Kite LTP first — works in both PAPER and LIVE mode
    try:
        from sol.broker.kite_client import get_kite_client  # type: ignore[import]
        client = get_kite_client()
        if client.is_authenticated():
            s = symbol.upper()
            key = f"NFO:{s}" if (s.endswith("CE") or s.endswith("PE") or s.endswith("FUT")) else f"{exchange}:{s}"
            quotes = client.get_ltp([key])
            ltp = quotes.get(key, {}).get("last_price")
            if ltp:
                from sol.broker.price_store import set_price
                set_price(key, float(ltp))
                return float(ltp)
    except Exception as e:
        logger.warning(f"[PositionMonitor] Kite LTP failed for {symbol}: {e}")

    # Fall back to snapshot (paper mode without Kite session)
    snap = snap_map.get(symbol)
    if snap is not None and snap.current_price:
        return float(snap.current_price)

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

    om = get_order_manager()

    # If SL was hit, the SL-M order on Kite already filled — cancel the TP order
    # If TP was hit, the LIMIT TP order already filled — cancel the SL order
    # If agent-triggered close, cancel both
    sl_order_id = getattr(position, 'sl_order_id', None)
    tp_order_id = getattr(position, 'tp_order_id', None)

    if status == "SL_HIT" and tp_order_id:
        await om.cancel_order_safe(tp_order_id)
    elif status == "TP_HIT" and sl_order_id:
        await om.cancel_order_safe(sl_order_id)
    else:
        # Agent/manual close — cancel both and place market close order
        if sl_order_id:
            await om.cancel_order_safe(sl_order_id)
        if tp_order_id:
            await om.cancel_order_safe(tp_order_id)
        try:
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

    # Recalibrate confidence threshold based on updated win rate
    if position.agent_id:
        try:
            from sol.core.agent_feedback import recalibrate_agent_threshold
            new_threshold = await recalibrate_agent_threshold(position.agent_id)
            if new_threshold is not None:
                logger.info(f"[PositionMonitor] Agent {position.agent_id} threshold recalibrated → {new_threshold}%")
        except Exception as e:
            logger.warning(f"[PositionMonitor] Threshold recalibration error for {position.agent_id}: {e}")

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
