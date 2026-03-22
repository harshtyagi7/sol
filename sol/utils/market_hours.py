"""
Market hours utilities for NSE/BSE.
All logic in IST (Asia/Kolkata, UTC+5:30).
"""

from datetime import date, datetime, time

import pytz

IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_MARKET_OPEN = time(9, 0)
INTRADAY_SQUAREOFF = time(15, 15)  # Square off intraday before close


def now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open(dt: datetime | None = None) -> bool:
    """Returns True if the market is currently open."""
    dt = dt or now_ist()
    dt_ist = dt.astimezone(IST)
    if dt_ist.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    t = dt_ist.time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_market_day(dt: datetime | date | None = None) -> bool:
    """Returns True if today is a weekday (basic check — no holiday calendar)."""
    d = (dt or now_ist()).date() if isinstance(dt, datetime) else (dt or now_ist().date())
    return d.weekday() < 5


def seconds_to_market_open() -> float:
    """Seconds until market opens (0 if already open)."""
    now = now_ist()
    if is_market_open(now):
        return 0.0
    target = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now.time() > MARKET_CLOSE:
        # Next day
        from datetime import timedelta
        target = target + timedelta(days=1)
        while target.weekday() >= 5:
            target = target + timedelta(days=1)
    delta = (target - now).total_seconds()
    return max(0.0, delta)


def is_near_close(minutes_before: int = 20) -> bool:
    """True if we're within N minutes of market close."""
    now = now_ist()
    close_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
    delta = (close_dt - now).total_seconds() / 60
    return 0 <= delta <= minutes_before


def market_status_str() -> str:
    if is_market_open():
        return "OPEN"
    now = now_ist()
    if now.weekday() >= 5:
        return "CLOSED (Weekend)"
    if now.time() < MARKET_OPEN:
        return "PRE-MARKET"
    return "CLOSED (After Hours)"
