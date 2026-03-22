"""Exponential backoff retry decorator for external API calls."""

import asyncio
import functools
import logging
from typing import Callable, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator: retry async function with exponential backoff."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_delay)
            raise last_exc

        return wrapper

    return decorator
