"""
Event bus for real-time notifications to WebSocket clients.
Uses asyncio.Queue for in-process pub/sub.
Redis pubsub can be layered on top if needed.
"""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# All connected WebSocket clients subscribe to this queue
_subscribers: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    """Register a new WebSocket client and return its event queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    logger.debug(f"New subscriber. Total: {len(_subscribers)}")
    return q


def unsubscribe(q: asyncio.Queue):
    """Remove a WebSocket client subscription."""
    if q in _subscribers:
        _subscribers.remove(q)
        logger.debug(f"Subscriber removed. Total: {len(_subscribers)}")


async def publish_event(event_type: str, data: Any):
    """Broadcast an event to all connected WebSocket clients."""
    payload = json.dumps({"type": event_type, "data": data}, default=str)
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
        except Exception as e:
            logger.error(f"Event publish error: {e}")
            dead.append(q)
    for q in dead:
        unsubscribe(q)


# Convenience helpers for common events
async def notify_new_proposal(proposal_data: dict):
    await publish_event("new_proposal", proposal_data)


async def notify_trade_executed(proposal_id: str, order_id: str):
    await publish_event("trade_executed", {"proposal_id": proposal_id, "order_id": order_id})


async def notify_position_update(position_data: dict):
    await publish_event("position_update", position_data)


async def notify_risk_alert(message: str, level: str = "WARNING"):
    await publish_event("risk_alert", {"message": message, "level": level})


async def notify_eod_report(report: str):
    await publish_event("eod_report", {"report": report})
