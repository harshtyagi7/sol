"""
Order manager — routes to real Kite or Paper broker.
Always re-validates risk before execution.
"""

import logging
from datetime import datetime
from typing import Optional

import pytz

from sol.config import get_settings
from sol.schemas.trade import RiskReport, TradeProposalCreate

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class OrderManager:
    def __init__(self):
        self.settings = get_settings()

    def _get_broker(self):
        from sol.core.trading_mode import get_paper_mode
        if get_paper_mode():
            from sol.broker.paper_broker import get_paper_broker
            return get_paper_broker()
        else:
            from sol.broker.kite_client import get_kite_client
            client = get_kite_client()
            if not client.is_authenticated():
                raise RuntimeError("Kite session not authenticated. Please login via /api/auth/login")
            return client

    async def execute_proposal(
        self,
        proposal,  # TradeProposal ORM model
        risk_report: RiskReport,
    ) -> str:
        """
        Execute a trade proposal.
        Returns order_id.
        Raises on failure.
        """
        if not risk_report.approved:
            raise ValueError(f"Risk not approved: {risk_report.violations}")

        broker = self._get_broker()
        qty = risk_report.modified_quantity or proposal.quantity

        # Zerodha API rejects plain MARKET orders on equity — convert to aggressive LIMIT
        order_type = proposal.order_type
        price = float(proposal.entry_price or 0.0)
        if order_type == "MARKET" and proposal.exchange in ("NSE", "BSE") and price > 0:
            order_type = "LIMIT"
            # Aggressive limit: 0.5% above for buys, 0.5% below for sells to ensure fill
            tick = 0.05
            if proposal.direction == "BUY":
                price = round(round(price * 1.005 / tick) * tick, 2)
            else:
                price = round(round(price * 0.995 / tick) * tick, 2)
            logger.info(f"Converted MARKET to LIMIT @ ₹{price} for {proposal.symbol} (Zerodha API requirement)")

        order_id = broker.place_order(
            tradingsymbol=proposal.symbol,
            exchange=proposal.exchange,
            transaction_type=proposal.direction,
            quantity=qty,
            order_type=order_type,
            product=proposal.product_type,
            price=price,
            tag="SOL",
        )

        logger.info(
            f"Executed proposal {proposal.id}: {proposal.direction} {qty} "
            f"{proposal.exchange}:{proposal.symbol} -> order_id={order_id}"
        )
        return order_id

    async def close_position(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        direction: str,  # original direction — we sell/buy opposite
        product_type: str,
    ) -> str:
        """Close an open position by placing the reverse trade."""
        broker = self._get_broker()
        close_direction = "SELL" if direction == "BUY" else "BUY"
        order_id = broker.place_order(
            tradingsymbol=symbol,
            exchange=exchange,
            transaction_type=close_direction,
            quantity=quantity,
            order_type="MARKET",
            product=product_type,
            tag="SOL_CLOSE",
        )
        logger.info(f"Closed position: {close_direction} {quantity} {exchange}:{symbol} -> {order_id}")
        return order_id

    async def place_sl_tp_orders(
        self,
        symbol: str,
        exchange: str,
        direction: str,        # original entry direction (BUY or SELL)
        quantity: int,
        product_type: str,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Place SL-M order and LIMIT TP order on Kite after entry.
        Returns (sl_order_id, tp_order_id). None for paper mode.
        """
        from sol.core.trading_mode import get_paper_mode
        if get_paper_mode():
            return None, None

        # Close direction is opposite of entry
        close_direction = "BUY" if direction == "SELL" else "SELL"
        tick = 0.05
        broker = self._get_broker()
        sl_order_id = None
        tp_order_id = None

        try:
            sl_trigger = round(round(stop_loss / tick) * tick, 2)
            sl_order_id = broker.place_order(
                tradingsymbol=symbol,
                exchange=exchange,
                transaction_type=close_direction,
                quantity=quantity,
                order_type="SL-M",
                product=product_type,
                trigger_price=sl_trigger,
                tag="SOL_SL",
            )
            logger.info(f"SL order placed: {sl_order_id} | {close_direction} {quantity} {symbol} trigger ₹{sl_trigger}")
        except Exception as e:
            logger.error(f"Failed to place SL order for {symbol}: {e}")

        try:
            tp_price = round(round(take_profit / tick) * tick, 2)
            tp_order_id = broker.place_order(
                tradingsymbol=symbol,
                exchange=exchange,
                transaction_type=close_direction,
                quantity=quantity,
                order_type="LIMIT",
                product=product_type,
                price=tp_price,
                tag="SOL_TP",
            )
            logger.info(f"TP order placed: {tp_order_id} | {close_direction} {quantity} {symbol} @ ₹{tp_price}")
        except Exception as e:
            logger.error(f"Failed to place TP order for {symbol}: {e}")

        return sl_order_id, tp_order_id

    async def cancel_order_safe(self, order_id: str) -> None:
        """Cancel a Kite order, ignoring errors (order may already be filled/cancelled)."""
        try:
            from sol.core.trading_mode import get_paper_mode
            if get_paper_mode():
                return
            self._get_broker().cancel_order(order_id)
            logger.info(f"Cancelled order {order_id}")
        except Exception as e:
            logger.warning(f"Could not cancel order {order_id}: {e}")

    async def get_order_fill_price(self, order_id: str) -> Optional[float]:
        """Fetch the actual average fill price from Kite for a completed order."""
        try:
            from sol.core.trading_mode import get_paper_mode
            if get_paper_mode():
                return None
            broker = self._get_broker()
            history = broker.get_order_history(order_id)
            if history:
                final = history[-1]
                avg = final.get("average_price")
                if avg and float(avg) > 0:
                    return float(avg)
        except Exception as e:
            logger.warning(f"Could not fetch fill price for order {order_id}: {e}")
        return None

    def get_available_capital(self) -> float:
        """Returns available cash balance."""
        try:
            broker = self._get_broker()
            funds = broker.get_funds()
            return float(funds.get("equity", {}).get("available", {}).get("live_balance", 0))
        except Exception as e:
            logger.error(f"Could not fetch funds: {e}")
            return 0.0


_order_manager: OrderManager | None = None


def get_order_manager() -> OrderManager:
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager()
    return _order_manager
