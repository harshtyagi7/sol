"""Unit tests for the in-process event bus."""

import asyncio
import json
import pytest
from sol.core.event_bus import subscribe, unsubscribe, publish_event


@pytest.fixture(autouse=True)
def clear_subscribers():
    """Ensure a clean subscriber list before/after each test."""
    import sol.core.event_bus as bus
    original = bus._subscribers.copy()
    bus._subscribers.clear()
    yield
    bus._subscribers.clear()
    bus._subscribers.extend(original)


class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscriber_receives_event(self):
        q = subscribe()
        await publish_event("test_event", {"key": "value"})
        payload = q.get_nowait()
        data = json.loads(payload)
        assert data["type"] == "test_event"
        assert data["data"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive(self):
        q1 = subscribe()
        q2 = subscribe()
        await publish_event("broadcast", {"msg": "hello"})
        assert not q1.empty()
        assert not q2.empty()

    @pytest.mark.asyncio
    async def test_unsubscribed_queue_does_not_receive(self):
        q = subscribe()
        unsubscribe(q)
        await publish_event("after_unsub", {"x": 1})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_event_payload_is_json(self):
        q = subscribe()
        await publish_event("data_event", {"price": 2850.0, "symbol": "RELIANCE"})
        payload = q.get_nowait()
        parsed = json.loads(payload)
        assert parsed["data"]["price"] == 2850.0

    @pytest.mark.asyncio
    async def test_no_subscribers_does_not_raise(self):
        # No subscribers registered — should be silent
        await publish_event("orphan_event", {"data": 1})

    @pytest.mark.asyncio
    async def test_full_queue_removes_dead_subscriber(self):
        import sol.core.event_bus as bus
        q = subscribe()
        # Fill the queue to capacity (maxsize=100)
        for i in range(100):
            q.put_nowait(f"item-{i}")
        initial_count = len(bus._subscribers)
        # Next publish should detect full queue and remove it
        await publish_event("overflow", {"x": 1})
        assert len(bus._subscribers) < initial_count

    @pytest.mark.asyncio
    async def test_notify_new_proposal(self):
        from sol.core.event_bus import notify_new_proposal
        q = subscribe()
        await notify_new_proposal({"symbol": "TCS", "direction": "BUY"})
        payload = json.loads(q.get_nowait())
        assert payload["type"] == "new_proposal"
        assert payload["data"]["symbol"] == "TCS"

    @pytest.mark.asyncio
    async def test_notify_risk_alert(self):
        from sol.core.event_bus import notify_risk_alert
        q = subscribe()
        await notify_risk_alert("Daily loss limit hit", level="ERROR")
        payload = json.loads(q.get_nowait())
        assert payload["type"] == "risk_alert"
        assert payload["data"]["level"] == "ERROR"

    @pytest.mark.asyncio
    async def test_notify_trade_executed(self):
        from sol.core.event_bus import notify_trade_executed
        q = subscribe()
        await notify_trade_executed("proposal-123", "ORDER-456")
        payload = json.loads(q.get_nowait())
        assert payload["type"] == "trade_executed"
        assert payload["data"]["proposal_id"] == "proposal-123"
        assert payload["data"]["order_id"] == "ORDER-456"

    @pytest.mark.asyncio
    async def test_datetime_serialized_in_payload(self):
        from datetime import datetime
        q = subscribe()
        await publish_event("ts_event", {"time": datetime(2025, 1, 6, 9, 15)})
        payload = q.get_nowait()
        parsed = json.loads(payload)
        # Should not raise — datetime serialized as string via default=str
        assert "2025" in str(parsed["data"]["time"])
