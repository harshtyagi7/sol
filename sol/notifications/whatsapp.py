"""
WhatsApp notifications via Twilio.
Sends alerts for key trading events: new strategies, position closes, cycle summaries.
"""

import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)

DAILY_LIMIT = 10
_sent_count: int = 0
_sent_date: date = date.min


async def send_whatsapp(message: str) -> bool:
    """Send a WhatsApp message via Twilio REST API. Returns True on success."""
    global _sent_count, _sent_date

    today = date.today()
    if _sent_date != today:
        _sent_count = 0
        _sent_date = today

    if _sent_count >= DAILY_LIMIT:
        logger.warning(f"[WhatsApp] Daily limit of {DAILY_LIMIT} messages reached — skipping")
        return False

    from sol.config import get_settings
    s = get_settings()

    if not s.TWILIO_ACCOUNT_SID or not s.TWILIO_AUTH_TOKEN or not s.TWILIO_WHATSAPP_TO:
        return False  # Not configured — silently skip

    url = f"https://api.twilio.com/2010-04-01/Accounts/{s.TWILIO_ACCOUNT_SID}/Messages.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                auth=(s.TWILIO_ACCOUNT_SID, s.TWILIO_AUTH_TOKEN),
                data={
                    "From": s.TWILIO_WHATSAPP_FROM,
                    "To": s.TWILIO_WHATSAPP_TO,
                    "Body": message,
                },
            )
        if resp.status_code in (200, 201):
            _sent_count += 1
            logger.debug(f"[WhatsApp] Sent ({_sent_count}/{DAILY_LIMIT}): {message[:80]}")
            return True
        else:
            logger.warning(f"[WhatsApp] Twilio error {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.warning(f"[WhatsApp] Send failed: {e}")
        return False


def _fmt_inr(amount: float) -> str:
    """Format a rupee amount with sign."""
    sign = "+" if amount >= 0 else ""
    return f"₹{sign}{amount:,.2f}"


async def notify_new_strategy(event: dict) -> None:
    win_rate = event.get("backtest_win_rate")
    if win_rate is None or win_rate < 70:
        logger.debug(
            f"[WhatsApp] Skipping strategy notification — backtest win rate "
            f"{win_rate}% < 70% (strategy: {event.get('name', '?')})"
        )
        return

    name = event.get("name", "?")
    agent = event.get("agent", "?")
    trades = event.get("trade_count", 0)
    max_loss = event.get("max_loss_possible", 0)
    await send_whatsapp(
        f"📋 *New Strategy Pending Approval*\n"
        f"Agent: {agent}\n"
        f"Strategy: {name}\n"
        f"Backtest win rate: {win_rate}%\n"
        f"Trades: {trades} | Max loss: {_fmt_inr(max_loss)}\n"
        f"→ Open Sol to approve or reject."
    )


async def notify_position_closed(event: dict) -> None:
    symbol = event.get("symbol", "?")
    status = event.get("status", "CLOSED")
    reason = event.get("reason", "")
    pnl = event.get("realized_pnl", 0)
    price = event.get("close_price", 0)
    emoji = "✅" if pnl >= 0 else "🔴"
    status_label = {
        "SL_HIT": "Stop-loss hit",
        "TP_HIT": "Take-profit hit",
        "SQUAREDOFF": "Agent exit",
    }.get(status, status)
    await send_whatsapp(
        f"{emoji} *Position Closed — {symbol}*\n"
        f"Reason: {status_label}\n"
        f"Exit price: ₹{price:,.2f}\n"
        f"P&L: {_fmt_inr(pnl)}\n"
        f"Note: {reason}"
    )


async def notify_cycle_summary(event: dict) -> None:
    summary = event.get("summary", "")
    count = event.get("strategy_count", 0)
    await send_whatsapp(
        f"🔄 *Sol Cycle Complete — {count} strategy/strategies pending*\n\n"
        f"{summary[:600]}"
    )


async def notify_peer_rejected(event: dict) -> None:
    name = event.get("name", "?")
    agent = event.get("agent", "?")
    reviewer = event.get("reviewer", "?")
    reason = event.get("reason", "")
    await send_whatsapp(
        f"🚫 *Strategy Rejected by Peer Review*\n"
        f"Strategy: {name} (by {agent})\n"
        f"Reviewer: {reviewer}\n"
        f"Reason: {reason}"
    )
