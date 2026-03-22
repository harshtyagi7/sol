"""Unit tests for the price store (in-memory layer)."""

import pytest
import sol.broker.price_store as store


@pytest.fixture(autouse=True)
def clear_cache():
    store._price_cache.clear()
    yield
    store._price_cache.clear()


class TestPriceStore:
    def test_set_and_get(self):
        store.set_price("NSE:RELIANCE", 2850.0)
        assert store.get_price("NSE:RELIANCE") == 2850.0

    def test_case_insensitive_set(self):
        store.set_price("nse:reliance", 2850.0)
        assert store.get_price("NSE:RELIANCE") == 2850.0

    def test_case_insensitive_get(self):
        store.set_price("NSE:INFY", 1750.0)
        assert store.get_price("nse:infy") == 1750.0

    def test_missing_key_returns_none(self):
        assert store.get_price("NSE:UNKNOWN") is None

    def test_overwrite_price(self):
        store.set_price("NSE:TCS", 4200.0)
        store.set_price("NSE:TCS", 4250.0)
        assert store.get_price("NSE:TCS") == 4250.0

    def test_multiple_instruments(self):
        store.set_price("NSE:RELIANCE", 2850.0)
        store.set_price("NSE:INFY", 1750.0)
        store.set_price("BSE:WIPRO", 520.0)
        assert store.get_price("NSE:RELIANCE") == 2850.0
        assert store.get_price("NSE:INFY") == 1750.0
        assert store.get_price("BSE:WIPRO") == 520.0

    def test_get_all_prices(self):
        store.set_price("NSE:RELIANCE", 2850.0)
        store.set_price("NSE:INFY", 1750.0)
        all_prices = store.get_all_prices()
        assert "NSE:RELIANCE" in all_prices
        assert "NSE:INFY" in all_prices
        assert all_prices["NSE:RELIANCE"] == 2850.0

    def test_get_all_returns_copy(self):
        store.set_price("NSE:RELIANCE", 2850.0)
        all_prices = store.get_all_prices()
        all_prices["NSE:RELIANCE"] = 9999.0
        # Original should not be modified
        assert store.get_price("NSE:RELIANCE") == 2850.0

    @pytest.mark.asyncio
    async def test_async_set_and_get(self):
        await store.set_price_async("NSE:HDFC", 1680.0)
        result = await store.get_price_async("NSE:HDFC")
        assert result == 1680.0

    @pytest.mark.asyncio
    async def test_async_fallback_to_memory(self):
        # Even without Redis, should work via in-memory fallback
        store.set_price("NSE:SBIN", 820.0)
        result = await store.get_price_async("NSE:SBIN")
        assert result == 820.0

    @pytest.mark.asyncio
    async def test_async_missing_returns_none(self):
        result = await store.get_price_async("NSE:DOESNOTEXIST")
        assert result is None
