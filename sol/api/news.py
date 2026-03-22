"""News API — fetch recent headlines for watchlist symbols."""

from fastapi import APIRouter, Query

from sol.services.news_service import get_news_for_symbol, get_news_for_symbols
from sol.services.market_data_service import DEFAULT_WATCHLIST

router = APIRouter(prefix="/news", tags=["news"])


@router.get("")
async def get_market_news():
    """Fetch headlines for the default watchlist symbols."""
    symbols = [s for s, _ in DEFAULT_WATCHLIST]
    news_map = await get_news_for_symbols(symbols)
    return {
        "symbols": [
            {"symbol": symbol, "headlines": headlines}
            for symbol, headlines in news_map.items()
        ]
    }


@router.get("/{symbol}")
async def get_symbol_news(symbol: str):
    """Fetch headlines for a specific symbol (e.g. INFY, TCS)."""
    headlines = await get_news_for_symbol(symbol.upper())
    return {"symbol": symbol.upper(), "headlines": headlines}
