"""
Position monitor — runs every minute during market hours.
Checks stop-loss and take-profit triggers.
Handles EOD square-off for intraday positions.
"""

import logging
from datetime import datetime
from typing import Optional

import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


async def check_positions():
    """
    Check all open positions against their SL/TP.
    SL hit → auto-exit and notify.
    TP hit → notify user (don't auto-sell, let user decide).
    """
    from sol.database import get_session
    from sol.models.position import Position
    from sol.broker.price_store import get_price
    from sol.core.event_bus import notify_position_update, notify_risk_alert
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(Position).where(Position.status == "OPEN"))
        positions = result.scalars().all()

        for pos in positions:
            key = f"{pos.exchange}:{pos.symbol}"
            current_price = get_price(key)
            if not current_price:
                continue

            pos.current_price = current_price

            sl = pos.stop_loss
            tp = pos.take_profit

            if pos.direction == "BUY":
                sl_hit = sl and current_price <= sl
                tp_hit = tp and current_price >= tp
            else:
                sl_hit = sl and current_price >= sl
                tp_hit = tp and current_price <= tp

            if sl_hit:
                logger.warning(f"SL HIT: {pos.symbol} @ {current_price:.2f} (SL: {sl:.2f})")
                await _close_position(db, pos, current_price, "SL_HIT")
                await notify_risk_alert(
                    f"Stop-loss hit on {pos.symbol}: sold @ ₹{current_price:.2f} | "
                    f"P&L: ₹{pos.unrealized_pnl:.2f}",
                    level="WARNING"
                )

            elif tp_hit:
                await notify_position_update({
                    "type": "TP_REACHED",
                    "position_id": pos.id,
                    "symbol": pos.symbol,
                    "current_price": current_price,
                    "take_profit": tp,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "message": f"Take-profit target reached on {pos.symbol}! Consider exiting.",
                })
            else:
                await notify_position_update({
                    "type": "PRICE_UPDATE",
                    "position_id": pos.id,
                    "symbol": pos.symbol,
                    "current_price": current_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                })

        await db.flush()


async def squareoff_intraday():
    """
    Square off all MIS (intraday) open positions at 3:20 PM.
    CNC (delivery) positions are kept overnight.
    """
    from sol.database import get_session
    from sol.models.position import Position
    from sol.broker.price_store import get_price
    from sol.core.event_bus import notify_risk_alert
    from sol.broker.order_manager import get_order_manager
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(
            select(Position).where(
                Position.status == "OPEN",
                Position.product_type == "MIS",
            )
        )
        positions = result.scalars().all()

        if not positions:
            return

        logger.info(f"EOD square-off: closing {len(positions)} intraday positions")
        om = get_order_manager()

        for pos in positions:
            current_price = get_price(f"{pos.exchange}:{pos.symbol}") or pos.avg_price
            try:
                # Cancel any pending SL/TP orders before placing close order
                # to avoid double-close (our order + Kite's SL-M both firing)
                if pos.sl_order_id:
                    await om.cancel_order_safe(pos.sl_order_id)
                if pos.tp_order_id:
                    await om.cancel_order_safe(pos.tp_order_id)

                await om.close_position(
                    symbol=pos.symbol,
                    exchange=pos.exchange,
                    quantity=pos.quantity,
                    direction=pos.direction,
                    product_type=pos.product_type,
                )
                await _close_position(db, pos, current_price, "CLOSED")
            except Exception as e:
                logger.error(f"Failed to square off {pos.symbol}: {e}")

        await notify_risk_alert(
            f"EOD square-off complete: {len(positions)} intraday positions closed.",
            level="INFO"
        )
        await db.flush()


async def _close_position(db, position, close_price: float, status: str):
    """Update position to closed state and notify strategy executor if applicable."""
    multiplier = 1 if position.direction == "BUY" else -1
    realized_pnl = multiplier * (close_price - position.avg_price) * position.quantity

    position.status = status
    position.close_price = close_price
    position.closed_at = datetime.now(IST)
    position.realized_pnl = round(realized_pnl, 2)
    position.current_price = close_price

    logger.info(
        f"Position closed: {position.symbol} {status} @ {close_price:.2f} | P&L: {realized_pnl:.2f}"
    )

    # Notify strategy executor so it can update loss tracking and enforce the cap
    if position.proposal_id:
        try:
            from sol.models.strategy import StrategyTrade
            from sqlalchemy import select
            result = await db.execute(
                select(StrategyTrade).where(StrategyTrade.id == position.proposal_id)
            )
            trade = result.scalar_one_or_none()
            if trade and trade.strategy_id:
                trade.actual_pnl = round(realized_pnl, 2)
                from sol.core.strategy_executor import get_strategy_executor
                executor = get_strategy_executor()
                await executor.on_trade_closed(trade.strategy_id, realized_pnl)
        except Exception as e:
            logger.error(f"Failed to notify strategy executor for position {position.id}: {e}")
