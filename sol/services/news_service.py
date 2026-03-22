"""
News service — fetches recent headlines for watchlist stocks.

Two sources (tried in order):
1. Finnhub company news API  — if FINNHUB_API_KEY is set in .env
2. Economic Times RSS feeds  — free, no key required, India-focused

Headlines are returned as plain strings and injected into MarketDataSnapshot
so agents can factor sentiment into their analysis.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol → search term mapping  (ET / Finnhub use company names, not tickers)
# ---------------------------------------------------------------------------
SYMBOL_TO_COMPANY: dict[str, str] = {
    "RELIANCE": "Reliance Industries",
    "INFY": "Infosys",
    "TCS": "TCS Tata Consultancy",
    "HDFCBANK": "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "SBIN": "SBI State Bank",
    "WIPRO": "Wipro",
    "HCLTECH": "HCL Technologies",
    "AXISBANK": "Axis Bank",
    "KOTAKBANK": "Kotak Mahindra Bank",
    "LT": "Larsen Toubro",
    "MARUTI": "Maruti Suzuki",
    "BAJFINANCE": "Bajaj Finance",
    "ASIANPAINT": "Asian Paints",
    "HINDUNILVR": "Hindustan Unilever",
    "NIFTY 50": "Nifty 50 index market",
    "NIFTY BANK": "Bank Nifty index",
}

# Simple in-process cache: symbol → (headlines, fetched_at)
_cache: dict[str, tuple[list[str], datetime]] = {}
_CACHE_TTL_MINUTES = 30


def _is_fresh(symbol: str) -> bool:
    if symbol not in _cache:
        return False
    _, fetched_at = _cache[symbol]
    return (datetime.utcnow() - fetched_at).total_seconds() < _CACHE_TTL_MINUTES * 60


# ---------------------------------------------------------------------------
# Finnhub (optional — requires FINNHUB_API_KEY in .env)
# ---------------------------------------------------------------------------

async def _fetch_finnhub(client: httpx.AsyncClient, symbol: str, api_key: str) -> list[str]:
    """Fetch last 5 company news headlines from Finnhub."""
    # Finnhub uses US-style tickers; map Indian symbols best-effort
    finnhub_ticker = symbol.replace(" ", "")  # rough normalisation
    to_date = datetime.utcnow().strftime("%Y-%m-%d")
    from_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = (
        f"https://finnhub.io/api/v1/company-news"
        f"?symbol={finnhub_ticker}&from={from_date}&to={to_date}&token={api_key}"
    )
    try:
        resp = await client.get(url, timeout=8.0)
        resp.raise_for_status()
        articles = resp.json()
        headlines = [a["headline"] for a in articles[:5] if a.get("headline")]
        return headlines
    except Exception as e:
        logger.debug(f"Finnhub fetch failed for {symbol}: {e}")
        return []


# ---------------------------------------------------------------------------
# Economic Times RSS (free, no key)
# ---------------------------------------------------------------------------

_ET_RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rss.cms",
    "https://economictimes.indiatimes.com/markets/rss.cms",
]


async def _fetch_et_rss(client: httpx.AsyncClient, symbol: str) -> list[str]:
    """Search ET RSS feed titles for mentions of the symbol or company name."""
    company = SYMBOL_TO_COMPANY.get(symbol, symbol)
    # Build search terms: both ticker and company name
    terms = {symbol.lower()}
    for word in company.lower().split():
        if len(word) > 3:
            terms.add(word)

    matched: list[str] = []
    for feed_url in _ET_RSS_FEEDS:
        try:
            resp = await client.get(feed_url, timeout=8.0)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is None or not title_el.text:
                    continue
                title = title_el.text.strip()
                title_lower = title.lower()
                if any(term in title_lower for term in terms):
                    matched.append(title)
                if len(matched) >= 5:
                    break
        except Exception as e:
            logger.debug(f"ET RSS fetch failed ({feed_url}): {e}")

        if matched:
            break  # stop after first feed that gives results

    return matched


# ---------------------------------------------------------------------------
# Moneycontrol / NSE announcements RSS (secondary fallback)
# ---------------------------------------------------------------------------

_MC_MARKET_RSS = "https://www.moneycontrol.com/rss/latestnews.xml"


async def _fetch_mc_rss(client: httpx.AsyncClient, symbol: str) -> list[str]:
    """Search Moneycontrol RSS for symbol mentions."""
    company = SYMBOL_TO_COMPANY.get(symbol, symbol)
    terms = {symbol.lower()}
    for word in company.lower().split():
        if len(word) > 3:
            terms.add(word)

    matched: list[str] = []
    try:
        resp = await client.get(_MC_MARKET_RSS, timeout=8.0)
        resp.raise_for_status()
        # MC RSS sometimes has encoding declarations — strip them
        xml_text = re.sub(r"<\?xml[^>]+\?>", "", resp.text).strip()
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip()
            if any(term in title.lower() for term in terms):
                matched.append(title)
            if len(matched) >= 5:
                break
    except Exception as e:
        logger.debug(f"MC RSS fetch failed: {e}")

    return matched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_news_for_symbol(symbol: str) -> list[str]:
    """
    Return up to 5 recent news headlines for a given NSE symbol.
    Results are cached for CACHE_TTL_MINUTES to avoid hammering feeds on every cycle.
    """
    if _is_fresh(symbol):
        return _cache[symbol][0]

    from sol.config import get_settings
    settings = get_settings()
    finnhub_key: str = getattr(settings, "FINNHUB_API_KEY", "")

    headlines: list[str] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": "Sol-Trading-Bot/1.0 (market research)"},
        follow_redirects=True,
    ) as client:
        if finnhub_key:
            headlines = await _fetch_finnhub(client, symbol, finnhub_key)

        if not headlines:
            headlines = await _fetch_et_rss(client, symbol)

        if not headlines:
            headlines = await _fetch_mc_rss(client, symbol)

    _cache[symbol] = (headlines, datetime.utcnow())
    if headlines:
        logger.debug(f"[news] {symbol}: {len(headlines)} headlines fetched")
    return headlines


async def get_news_for_symbols(symbols: list[str]) -> dict[str, list[str]]:
    """Fetch news for multiple symbols concurrently."""
    results = await asyncio.gather(
        *[get_news_for_symbol(s) for s in symbols],
        return_exceptions=True,
    )
    out: dict[str, list[str]] = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.warning(f"[news] Failed for {symbol}: {result}")
            out[symbol] = []
        else:
            out[symbol] = result  # type: ignore[assignment]
    return out
