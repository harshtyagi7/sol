"""
Paper trading broker — same interface as KiteClient.
Simulates order fills using live/last-known prices.
All orders saved to DB with is_virtual=True.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

import pytz

from sol.broker.price_store import get_price

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class PaperBroker:
    """Simulates Kite order execution without real API calls."""

    def __init__(self):
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}

    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str,
        product: str,
        price: float = 0.0,
        trigger_price: float = 0.0,
        tag: str = "SOL_PAPER",
    ) -> str:
        order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
        fill_price = price if order_type == "LIMIT" and price > 0 else self._get_fill_price(
            f"{exchange}:{tradingsymbol}", order_type, transaction_type
        )

        self._orders[order_id] = {
            "order_id": order_id,
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "order_type": order_type,
            "product": product,
            "price": fill_price,
            "status": "COMPLETE",
            "filled_at": datetime.now(IST).isoformat(),
            "tag": tag,
        }

        # Update paper position
        key = f"{exchange}:{tradingsymbol}:{product}"
        if key not in self._positions:
            self._positions[key] = {
                "tradingsymbol": tradingsymbol,
                "exchange": exchange,
                "product": product,
                "quantity": 0,
                "average_price": 0.0,
            }

        pos = self._positions[key]
        if transaction_type == "BUY":
            total_cost = pos["average_price"] * pos["quantity"] + fill_price * quantity
            pos["quantity"] += quantity
            pos["average_price"] = total_cost / pos["quantity"] if pos["quantity"] else 0
        else:
            pos["quantity"] -= quantity
            if pos["quantity"] == 0:
                pos["average_price"] = 0.0

        logger.info(
            f"[PAPER] {transaction_type} {quantity} {exchange}:{tradingsymbol} @ {fill_price:.2f} | {order_id}"
        )
        return order_id

    def _get_fill_price(self, instrument_key: str, order_type: str, side: str) -> float:
        """Get simulated fill price from price store."""
        price = get_price(instrument_key)
        if price:
            # Add small slippage for realism
            slippage = 0.0005  # 0.05%
            if side == "BUY":
                return round(price * (1 + slippage), 2)
            else:
                return round(price * (1 - slippage), 2)
        return 0.0

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
            return True
        return False

    def get_orders(self) -> list[dict]:
        return list(self._orders.values())

    def get_positions(self) -> dict:
        """Returns positions in Kite-compatible format."""
        day_positions = [p for p in self._positions.values() if p["quantity"] != 0]
        return {"net": day_positions, "day": day_positions}

    def get_funds(self) -> dict:
        return {"equity": {"available": {"live_balance": 1_000_000.0}}}

    def is_authenticated(self) -> bool:
        return True


_paper_broker: Optional[PaperBroker] = None


def get_paper_broker() -> PaperBroker:
    global _paper_broker
    if _paper_broker is None:
        _paper_broker = PaperBroker()
    return _paper_broker
