"""Unit tests for PaperBroker."""

import pytest
from sol.broker.paper_broker import PaperBroker
import sol.broker.price_store as price_store


@pytest.fixture(autouse=True)
def clear_price_cache():
    """Reset price cache before each test."""
    price_store._price_cache.clear()
    yield
    price_store._price_cache.clear()


@pytest.fixture
def broker():
    return PaperBroker()


class TestPaperBrokerOrders:
    def test_place_market_order_returns_paper_id(self, broker):
        price_store.set_price("NSE:RELIANCE", 2850.0)
        order_id = broker.place_order("RELIANCE", "NSE", "BUY", 10, "MARKET", "MIS")
        assert order_id.startswith("PAPER-")

    def test_place_limit_order_uses_given_price(self, broker):
        order_id = broker.place_order("RELIANCE", "NSE", "BUY", 10, "LIMIT", "MIS", price=2800.0)
        orders = broker.get_orders()
        order = next(o for o in orders if o["order_id"] == order_id)
        assert order["price"] == 2800.0

    def test_market_buy_applies_slippage(self, broker):
        price_store.set_price("NSE:INFY", 1750.0)
        order_id = broker.place_order("INFY", "NSE", "BUY", 5, "MARKET", "MIS")
        orders = broker.get_orders()
        order = next(o for o in orders if o["order_id"] == order_id)
        # Buy fill should be slightly above market price (slippage)
        assert order["price"] > 1750.0
        assert order["price"] < 1752.0  # 0.05% slippage max

    def test_market_sell_applies_slippage(self, broker):
        price_store.set_price("NSE:INFY", 1750.0)
        order_id = broker.place_order("INFY", "NSE", "SELL", 5, "MARKET", "MIS")
        orders = broker.get_orders()
        order = next(o for o in orders if o["order_id"] == order_id)
        # Sell fill should be slightly below market price
        assert order["price"] < 1750.0
        assert order["price"] > 1748.0

    def test_order_status_complete(self, broker):
        price_store.set_price("NSE:TCS", 4200.0)
        order_id = broker.place_order("TCS", "NSE", "BUY", 2, "MARKET", "MIS")
        orders = broker.get_orders()
        order = next(o for o in orders if o["order_id"] == order_id)
        assert order["status"] == "COMPLETE"

    def test_cancel_order(self, broker):
        price_store.set_price("NSE:TCS", 4200.0)
        order_id = broker.place_order("TCS", "NSE", "BUY", 2, "MARKET", "MIS")
        result = broker.cancel_order(order_id)
        assert result is True
        orders = broker.get_orders()
        order = next(o for o in orders if o["order_id"] == order_id)
        assert order["status"] == "CANCELLED"

    def test_cancel_nonexistent_order(self, broker):
        result = broker.cancel_order("PAPER-NONEXISTENT")
        assert result is False

    def test_market_order_no_price_fills_zero(self, broker):
        # No price in store — fill price should be 0
        order_id = broker.place_order("UNKNOWN", "NSE", "BUY", 1, "MARKET", "MIS")
        orders = broker.get_orders()
        order = next(o for o in orders if o["order_id"] == order_id)
        assert order["price"] == 0.0

    def test_multiple_orders_all_tracked(self, broker):
        price_store.set_price("NSE:RELIANCE", 2850.0)
        price_store.set_price("NSE:INFY", 1750.0)
        id1 = broker.place_order("RELIANCE", "NSE", "BUY", 5, "MARKET", "MIS")
        id2 = broker.place_order("INFY", "NSE", "SELL", 3, "MARKET", "MIS")
        orders = broker.get_orders()
        assert len(orders) == 2
        assert {o["order_id"] for o in orders} == {id1, id2}


class TestPaperBrokerPositions:
    def test_buy_creates_position(self, broker):
        price_store.set_price("NSE:RELIANCE", 2850.0)
        broker.place_order("RELIANCE", "NSE", "BUY", 10, "MARKET", "MIS")
        positions = broker.get_positions()
        assert len(positions["net"]) == 1
        assert positions["net"][0]["tradingsymbol"] == "RELIANCE"
        assert positions["net"][0]["quantity"] == 10

    def test_sell_reduces_position(self, broker):
        price_store.set_price("NSE:RELIANCE", 2850.0)
        broker.place_order("RELIANCE", "NSE", "BUY", 10, "MARKET", "MIS")
        broker.place_order("RELIANCE", "NSE", "SELL", 5, "MARKET", "MIS")
        positions = broker.get_positions()
        pos = next(p for p in positions["net"] if p["tradingsymbol"] == "RELIANCE")
        assert pos["quantity"] == 5

    def test_full_exit_removes_from_active_positions(self, broker):
        price_store.set_price("NSE:RELIANCE", 2850.0)
        broker.place_order("RELIANCE", "NSE", "BUY", 10, "MARKET", "MIS")
        broker.place_order("RELIANCE", "NSE", "SELL", 10, "MARKET", "MIS")
        positions = broker.get_positions()
        active = [p for p in positions["net"] if p["tradingsymbol"] == "RELIANCE"]
        assert len(active) == 0

    def test_average_price_on_multiple_buys(self, broker):
        # Buy 10 @ 2800, buy 10 @ 2900 → avg = 2850
        broker.place_order("RELIANCE", "NSE", "BUY", 10, "LIMIT", "MIS", price=2800.0)
        broker.place_order("RELIANCE", "NSE", "BUY", 10, "LIMIT", "MIS", price=2900.0)
        pos_key = "NSE:RELIANCE:MIS"
        pos = broker._positions[pos_key]
        assert abs(pos["average_price"] - 2850.0) < 0.01
        assert pos["quantity"] == 20

    def test_positions_returns_kite_compatible_format(self, broker):
        price_store.set_price("NSE:HDFC", 1680.0)
        broker.place_order("HDFC", "NSE", "BUY", 5, "MARKET", "MIS")
        positions = broker.get_positions()
        assert "net" in positions
        assert "day" in positions

    def test_is_always_authenticated(self, broker):
        assert broker.is_authenticated() is True

    def test_funds_returns_capital(self, broker):
        funds = broker.get_funds()
        balance = funds["equity"]["available"]["live_balance"]
        assert balance == 1_000_000.0

    def test_different_products_tracked_separately(self, broker):
        broker.place_order("RELIANCE", "NSE", "BUY", 5, "LIMIT", "MIS", price=2850.0)
        broker.place_order("RELIANCE", "NSE", "BUY", 5, "LIMIT", "CNC", price=2850.0)
        assert "NSE:RELIANCE:MIS" in broker._positions
        assert "NSE:RELIANCE:CNC" in broker._positions
