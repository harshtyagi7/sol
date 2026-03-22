"""Unit tests for position monitor SL/TP logic and P&L calculation."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
import pytz

from sol.services.position_monitor import _close_position

IST = pytz.timezone("Asia/Kolkata")


def make_position(direction="BUY", avg_price=2850.0, quantity=10,
                  stop_loss=2800.0, take_profit=2950.0, current_price=2850.0):
    pos = MagicMock()
    pos.direction = direction
    pos.avg_price = avg_price
    pos.quantity = quantity
    pos.stop_loss = stop_loss
    pos.take_profit = take_profit
    pos.current_price = current_price
    pos.symbol = "RELIANCE"
    pos.exchange = "NSE"
    pos.product_type = "MIS"
    pos.status = "OPEN"
    pos.unrealized_pnl = (
        (current_price - avg_price) * quantity
        if direction == "BUY"
        else (avg_price - current_price) * quantity
    )
    return pos


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_close_long_profit(self):
        db = MagicMock()
        pos = make_position(direction="BUY", avg_price=2800.0, quantity=10, current_price=None)
        await _close_position(db, pos, close_price=2900.0, status="SL_HIT")
        assert pos.status == "SL_HIT"
        assert pos.close_price == 2900.0
        assert abs(pos.realized_pnl - 1000.0) < 0.01  # 10 * 100

    @pytest.mark.asyncio
    async def test_close_long_loss(self):
        db = MagicMock()
        pos = make_position(direction="BUY", avg_price=2850.0, quantity=10, current_price=None)
        await _close_position(db, pos, close_price=2800.0, status="SL_HIT")
        assert abs(pos.realized_pnl - (-500.0)) < 0.01  # 10 * -50

    @pytest.mark.asyncio
    async def test_close_short_profit(self):
        db = MagicMock()
        pos = make_position(direction="SELL", avg_price=1800.0, quantity=5, current_price=None)
        await _close_position(db, pos, close_price=1750.0, status="TP_HIT")
        assert abs(pos.realized_pnl - 250.0) < 0.01  # 5 * 50

    @pytest.mark.asyncio
    async def test_close_short_loss(self):
        db = MagicMock()
        pos = make_position(direction="SELL", avg_price=1800.0, quantity=5, current_price=None)
        await _close_position(db, pos, close_price=1850.0, status="SL_HIT")
        assert abs(pos.realized_pnl - (-250.0)) < 0.01

    @pytest.mark.asyncio
    async def test_status_is_set(self):
        db = MagicMock()
        pos = make_position()
        await _close_position(db, pos, close_price=2900.0, status="SQUAREDOFF")
        assert pos.status == "SQUAREDOFF"

    @pytest.mark.asyncio
    async def test_closed_at_is_set(self):
        db = MagicMock()
        pos = make_position()
        await _close_position(db, pos, close_price=2900.0, status="CLOSED")
        assert pos.closed_at is not None

    @pytest.mark.asyncio
    async def test_current_price_updated(self):
        db = MagicMock()
        pos = make_position()
        await _close_position(db, pos, close_price=2875.0, status="CLOSED")
        assert pos.current_price == 2875.0

    @pytest.mark.asyncio
    async def test_zero_pnl_at_avg_price(self):
        db = MagicMock()
        pos = make_position(direction="BUY", avg_price=2850.0, quantity=10)
        await _close_position(db, pos, close_price=2850.0, status="CLOSED")
        assert pos.realized_pnl == 0.0

    @pytest.mark.asyncio
    async def test_pnl_is_rounded(self):
        db = MagicMock()
        pos = make_position(direction="BUY", avg_price=2850.33, quantity=3)
        await _close_position(db, pos, close_price=2855.78, status="CLOSED")
        # Should be rounded to 2 decimal places
        assert isinstance(pos.realized_pnl, float)
        assert pos.realized_pnl == round(3 * (2855.78 - 2850.33), 2)


class TestSLTPDetectionLogic:
    """Test the SL/TP trigger conditions directly from the monitor logic."""

    def _check_triggers(self, direction, current_price, stop_loss=None, take_profit=None):
        """Replicate the SL/TP logic from check_positions."""
        if direction == "BUY":
            sl_hit = stop_loss is not None and current_price <= stop_loss
            tp_hit = take_profit is not None and current_price >= take_profit
        else:
            sl_hit = stop_loss is not None and current_price >= stop_loss
            tp_hit = take_profit is not None and current_price <= take_profit
        return sl_hit, tp_hit

    def test_long_sl_hit_exact(self):
        sl, tp = self._check_triggers("BUY", current_price=2800.0, stop_loss=2800.0)
        assert sl is True
        assert tp is False

    def test_long_sl_hit_below(self):
        sl, tp = self._check_triggers("BUY", current_price=2795.0, stop_loss=2800.0)
        assert sl is True

    def test_long_sl_not_hit(self):
        sl, tp = self._check_triggers("BUY", current_price=2801.0, stop_loss=2800.0)
        assert sl is False

    def test_long_tp_hit_exact(self):
        sl, tp = self._check_triggers("BUY", current_price=2950.0, take_profit=2950.0)
        assert tp is True

    def test_long_tp_hit_above(self):
        sl, tp = self._check_triggers("BUY", current_price=2960.0, take_profit=2950.0)
        assert tp is True

    def test_long_tp_not_hit(self):
        sl, tp = self._check_triggers("BUY", current_price=2940.0, take_profit=2950.0)
        assert tp is False

    def test_long_neither_sl_nor_tp(self):
        sl, tp = self._check_triggers("BUY", 2900.0, stop_loss=2800.0, take_profit=2950.0)
        assert sl is False
        assert tp is False

    def test_short_sl_hit_exact(self):
        sl, tp = self._check_triggers("SELL", current_price=1850.0, stop_loss=1850.0)
        assert sl is True

    def test_short_sl_hit_above(self):
        sl, tp = self._check_triggers("SELL", current_price=1860.0, stop_loss=1850.0)
        assert sl is True

    def test_short_sl_not_hit(self):
        sl, tp = self._check_triggers("SELL", current_price=1840.0, stop_loss=1850.0)
        assert sl is False

    def test_short_tp_hit(self):
        sl, tp = self._check_triggers("SELL", current_price=1700.0, take_profit=1750.0)
        assert tp is True

    def test_short_tp_not_hit(self):
        sl, tp = self._check_triggers("SELL", current_price=1760.0, take_profit=1750.0)
        assert tp is False

    def test_no_sl_defined_never_triggers(self):
        sl, tp = self._check_triggers("BUY", 2700.0, stop_loss=None)
        assert sl is False

    def test_no_tp_defined_never_triggers(self):
        sl, tp = self._check_triggers("BUY", 3100.0, take_profit=None)
        assert tp is False
