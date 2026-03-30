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

    logger.info("Scheduler configured with all market-hours jobs")
    return scheduler
