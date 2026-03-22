"""
In-memory (+ Redis) price store.
Stores latest prices keyed as "NSE:RELIANCE" -> float.
Redis is the primary store; in-memory dict is fallback.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_price_cache: dict[str, float] = {}
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            from sol.config import get_settings
            _redis_client = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning(f"Redis not available for price store: {e}")
    return _redis_client


def set_price(instrument_key: str, price: float):
    """Update in-memory price cache."""
    _price_cache[instrument_key.upper()] = price


def get_price(instrument_key: str) -> Optional[float]:
    """Get last known price from in-memory cache."""
    return _price_cache.get(instrument_key.upper())


def get_all_prices() -> dict[str, float]:
    return dict(_price_cache)


async def set_price_async(instrument_key: str, price: float):
    """Update price in Redis (async) and in-memory."""
    key = instrument_key.upper()
    _price_cache[key] = price
    r = _get_redis()
    if r:
        try:
            await r.setex(f"price:{key}", 300, str(price))  # 5 min TTL
        except Exception:
            pass  # fallback to in-memory


async def get_price_async(instrument_key: str) -> Optional[float]:
    """Get price from Redis first, fallback to in-memory."""
    key = instrument_key.upper()
    r = _get_redis()
    if r:
        try:
            val = await r.get(f"price:{key}")
            if val:
                price = float(val)
                _price_cache[key] = price
                return price
        except Exception:
            pass
    return _price_cache.get(key)
