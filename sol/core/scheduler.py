"""
APScheduler for market-hours operations.
All times in IST (Asia/Kolkata).
"""

import asyncio
import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=IST)
    return _scheduler


async def run_agent_analysis():
    """Called every 15 minutes during market hours."""
    from sol.utils.market_hours import is_market_open
    if not is_market_open():
        return

    logger.info("Starting agent analysis cycle...")
    try:
        from sol.core.cycle_runner import run_analysis_cycle
        await run_analysis_cycle()
    except Exception as e:
        logger.error(f"Analysis cycle failed: {e}", exc_info=True)


async def run_position_monitor():
    """Called every minute during market hours — checks SL/TP."""
    from sol.utils.market_hours import is_market_open
    if not is_market_open():
        return

    try:
        from sol.services.position_monitor import check_positions
        await check_positions()
    except Exception as e:
        logger.error(f"Position monitor error: {e}", exc_info=True)


async def _run_trail():
    """Called at 2:00 PM — trail profitable MIS stops to breakeven."""
    try:
        from sol.core.position_monitor import trail_intraday_to_breakeven
        await trail_intraday_to_breakeven()
    except Exception as e:
        logger.error(f"Intraday trail error: {e}")


async def run_eod_squareoff():
    """Called at 3:20 PM to square off intraday positions."""
    logger.info("EOD square-off starting...")
    try:
        from sol.services.position_monitor import squareoff_intraday
        await squareoff_intraday()
    except Exception as e:
        logger.error(f"EOD squareoff error: {e}", exc_info=True)


async def run_eod_report():
    """Called at 3:35 PM to generate daily summary."""
    logger.info("Generating EOD report...")
    try:
        from sol.services.eod_reporter import generate_eod_report
        await generate_eod_report()
    except Exception as e:
        logger.error(f"EOD report error: {e}", exc_info=True)


async def run_post_market_kite_sync():
    """
    Called at 3:40 PM — sync any live positions that Kite auto-squared off
    at 3:30 PM but our monitor missed (e.g. session expired, price gap).
    """
    logger.info("Post-market Kite sync starting...")
    try:
        from sol.broker.kite_client import get_kite_client
        from sol.database import get_session
        from sol.models.position import Position
        from sqlalchemy import select
        from datetime import datetime
        import pytz

        client = get_kite_client()
        if not client.is_authenticated():
            logger.warning("Post-market Kite sync skipped — not authenticated")
            return

        kite_positions = client.get_positions()
        kite_trades = client.get_trades()

        # Build lookup: symbol -> day position
        kite_day = {p["tradingsymbol"]: p for p in kite_positions.get("day", [])}
        kite_net = {p["tradingsymbol"]: p for p in kite_positions.get("net", [])}

        # Build closing trade lookup: symbol -> closing fill price
        close_fills: dict = {}
        for t in kite_trades:
            sym = t.get("tradingsymbol", "")
            avg = float(t.get("average_price", 0) or 0)
            if avg > 0:
                close_fills[sym] = avg  # last fill wins

        IST_tz = pytz.timezone("Asia/Kolkata")

        async with get_session() as db:
            result = await db.execute(
                select(Position).where(Position.status == "OPEN", Position.is_virtual == False)
            )
            open_positions = result.scalars().all()

        synced = 0
        for pos in open_positions:
            kp = kite_day.get(pos.symbol)
            kite_qty = abs(int(kp.get("quantity", 0))) if kp else None
            kite_pnl = float(kp.get("pnl", 0)) if kp else None

            is_closed = (kite_qty is not None and kite_qty == 0) or (kp is None and pos.symbol not in kite_net)
            if not is_closed:
                continue

            close_price = close_fills.get(pos.symbol) or float(pos.current_price or pos.avg_price)
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
                    p.closed_at = datetime.now(IST_tz)
                    p.current_price = close_price
                    synced += 1

        if synced:
            logger.info(f"Post-market Kite sync: closed {synced} position(s) that were auto-squared")
        else:
            logger.info("Post-market Kite sync: all positions already up to date")

    except Exception as e:
        logger.error(f"Post-market Kite sync error: {e}", exc_info=True)


async def check_kite_session():
    """Called at 8:45 AM — alert if Kite session is invalid."""
    try:
        from sol.core.event_bus import publish_event
        from sol.broker.kite_client import get_kite_client
        client = get_kite_client()
        if not client.is_authenticated():
            await publish_event("system_alert", {
                "level": "WARNING",
                "message": "Kite session not authenticated. Please login at /api/auth/login before market opens.",
            })
            logger.warning("Kite session check failed — not authenticated")
    except Exception as e:
        logger.error(f"Session check error: {e}")


async def send_morning_login_reminder():
    """Called at 9:00 AM — WhatsApp reminder to login to Sol before market opens."""
    try:
        from sol.broker.kite_client import get_kite_client
        from sol.notifications.whatsapp import send_whatsapp
        from sol.config import get_settings

        client = get_kite_client()
        settings = get_settings()
        app_url = settings.APP_URL.rstrip("/")

        if client.is_authenticated():
            msg = (
                f"☀️ Good morning! Sol is ready.\n"
                f"Kite session is active — market opens at 9:15 AM.\n"
                f"📊 Dashboard: {app_url}"
            )
        else:
            msg = (
                f"⚠️ Sol needs you to login before the market opens.\n"
                f"👉 Login here: {app_url}/api/auth/login\n\n"
                f"Market opens at 9:15 AM IST."
            )
        await send_whatsapp(msg)
    except Exception as e:
        logger.error(f"Morning reminder error: {e}")


def setup_scheduler():
    """Register all scheduled jobs."""
    scheduler = get_scheduler()

    # Session check — 8:45 AM IST on weekdays
    scheduler.add_job(
        check_kite_session,
        CronTrigger(hour=8, minute=45, day_of_week="mon-fri", timezone=IST),
        id="session_check",
        replace_existing=True,
    )

    # Morning WhatsApp reminder — 9:00 AM IST on weekdays
    scheduler.add_job(
        send_morning_login_reminder,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone=IST),
        id="morning_reminder",
        replace_existing=True,
    )

    # Agent analysis — 9:15 AM, then every 15 min until 3:15 PM
    scheduler.add_job(
        run_agent_analysis,
        CronTrigger(
            hour="9-15", minute="*/15", day_of_week="mon-fri", timezone=IST
        ),
        id="agent_analysis",
        replace_existing=True,
    )

    # Position monitor — every minute, 9:15 AM to 3:30 PM
    scheduler.add_job(
        run_position_monitor,
        CronTrigger(
            hour="9-15", minute="*", day_of_week="mon-fri", timezone=IST
        ),
        id="position_monitor",
        replace_existing=True,
    )

    # 2:00 PM trail — move SL to breakeven for profitable MIS positions
    scheduler.add_job(
        _run_trail,
        CronTrigger(hour=14, minute=0, day_of_week="mon-fri", timezone=IST),
        id="intraday_trail",
        replace_existing=True,
    )

    # EOD square-off — 3:20 PM
    scheduler.add_job(
        run_eod_squareoff,
        CronTrigger(hour=15, minute=20, day_of_week="mon-fri", timezone=IST),
        id="eod_squareoff",
        replace_existing=True,
    )

    # EOD report — 3:35 PM
    scheduler.add_job(
        run_eod_report,
        CronTrigger(hour=15, minute=35, day_of_week="mon-fri", timezone=IST),
        id="eod_report",
        replace_existing=True,
    )

    # Post-market Kite sync — 3:40 PM (after Kite auto-squares all MIS at 3:30 PM)
    scheduler.add_job(
        run_post_market_kite_sync,
        CronTrigger(hour=15, minute=40, day_of_week="mon-fri", timezone=IST),
        id="post_market_kite_sync",
        replace_existing=True,
    )

    logger.info("Scheduler configured with all market-hours jobs")
    return scheduler
