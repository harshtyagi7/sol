"""
Zerodha Kite Connect wrapper.
Handles OAuth, market data, and order management.
Tokens expire daily at 6 AM IST — user must re-login each day.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pytz

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")


class KiteClient:
    """Wraps kiteconnect.KiteConnect with async-friendly patterns."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._kite = None
        self._access_token: Optional[str] = None

    def _get_kite(self):
        if self._kite is None:
            try:
                from kiteconnect import KiteConnect
                self._kite = KiteConnect(api_key=self.api_key)
            except ImportError:
                raise RuntimeError(
                    "kiteconnect not installed. Run: pip install kiteconnect"
                )
        return self._kite

    def get_login_url(self) -> str:
        return self._get_kite().login_url()

    def complete_oauth(self, request_token: str) -> dict:
        """Exchange request_token for access_token. Returns session data."""
        kite = self._get_kite()
        session = kite.generate_session(request_token, api_secret=self.api_secret)
        self._access_token = session["access_token"]
        kite.set_access_token(self._access_token)
        return session

    def set_access_token(self, token: str):
        self._access_token = token
        self._get_kite().set_access_token(token)

    def is_authenticated(self) -> bool:
        return self._access_token is not None

    # --- Market Data ---

    def get_quote(self, instruments: list[str]) -> dict[str, Any]:
        """Get live quote for a list of instruments (e.g. ['NSE:RELIANCE'])."""
        kite = self._get_kite()
        return kite.quote(instruments)

    def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        """Get last traded price only — faster than full quote."""
        return self._get_kite().ltp(instruments)

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
        continuous: bool = False,
    ) -> list[dict]:
        """
        interval: minute, 3minute, 5minute, 15minute, 30minute, 60minute, day, week, month
        """
        return self._get_kite().historical_data(
            instrument_token, from_date, to_date, interval, continuous
        )

    def get_instruments(self, exchange: str = "NSE") -> list[dict]:
        return self._get_kite().instruments(exchange)

    def get_full_quote(self, instruments: list[str]) -> dict[str, Any]:
        """Full quote including OI, Greeks, IV — needed for option chain.
        Kite allows up to 500 instruments per call.
        """
        return self._get_kite().quote(instruments)

    # --- Portfolio ---

    def get_positions(self) -> dict:
        return self._get_kite().positions()

    def get_holdings(self) -> list[dict]:
        return self._get_kite().holdings()

    def get_funds(self) -> dict:
        return self._get_kite().margins()

    # --- Orders ---

    def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,  # "BUY" | "SELL"
        quantity: int,
        order_type: str,  # "MARKET" | "LIMIT" | "SL" | "SL-M"
        product: str,  # "MIS" | "CNC" | "NRML"
        price: float = 0.0,
        trigger_price: float = 0.0,
        tag: str = "SOL",
    ) -> str:
        """Places an order and returns the order_id."""
        kite = self._get_kite()
        from kiteconnect import KiteConnect

        order_id = kite.place_order(
            variety=KiteConnect.VARIETY_REGULAR,
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=order_type,
            product=product,
            price=price if order_type in ("LIMIT", "SL") else None,
            trigger_price=trigger_price if order_type in ("SL", "SL-M") else None,
            tag=tag,
        )
        logger.info(f"Order placed: {order_id} | {transaction_type} {quantity} {tradingsymbol}")
        return str(order_id)

    def cancel_order(self, order_id: str) -> bool:
        try:
            from kiteconnect import KiteConnect
            self._get_kite().cancel_order(variety=KiteConnect.VARIETY_REGULAR, order_id=order_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_orders(self) -> list[dict]:
        return self._get_kite().orders()

    def get_order_history(self, order_id: str) -> list[dict]:
        return self._get_kite().order_history(order_id)

    def get_trades(self) -> list[dict]:
        return self._get_kite().trades()


# Singleton instance managed by app lifespan
_kite_client: Optional[KiteClient] = None


def get_kite_client() -> KiteClient:
    global _kite_client
    if _kite_client is None:
        from sol.config import get_settings
        s = get_settings()
        _kite_client = KiteClient(s.KITE_API_KEY, s.KITE_API_SECRET)
    return _kite_client
