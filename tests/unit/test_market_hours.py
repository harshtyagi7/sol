"""Tests for market hours utilities."""

import pytest
from datetime import datetime
import pytz
from sol.utils.market_hours import is_market_open, is_market_day, market_status_str

IST = pytz.timezone("Asia/Kolkata")


def ist(year, month, day, hour, minute, second=0):
    return IST.localize(datetime(year, month, day, hour, minute, second))


class TestMarketHours:
    def test_market_open_during_hours(self):
        # Monday 10:30 AM IST
        dt = ist(2025, 1, 6, 10, 30)
        assert is_market_open(dt) is True

    def test_market_open_at_915(self):
        dt = ist(2025, 1, 6, 9, 15)
        assert is_market_open(dt) is True

    def test_market_open_at_1530(self):
        dt = ist(2025, 1, 6, 15, 30)
        assert is_market_open(dt) is True

    def test_market_closed_at_1531(self):
        dt = ist(2025, 1, 6, 15, 31)
        assert is_market_open(dt) is False

    def test_market_closed_before_open(self):
        dt = ist(2025, 1, 6, 9, 14)
        assert is_market_open(dt) is False

    def test_market_closed_on_saturday(self):
        # Saturday 11 AM
        dt = ist(2025, 1, 4, 11, 0)
        assert is_market_open(dt) is False

    def test_market_closed_on_sunday(self):
        dt = ist(2025, 1, 5, 11, 0)
        assert is_market_open(dt) is False

    def test_weekday_check(self):
        assert is_market_day(ist(2025, 1, 6, 9, 0)) is True   # Monday
        assert is_market_day(ist(2025, 1, 10, 9, 0)) is True  # Friday
        assert is_market_day(ist(2025, 1, 11, 9, 0)) is False  # Saturday
        assert is_market_day(ist(2025, 1, 12, 9, 0)) is False  # Sunday
