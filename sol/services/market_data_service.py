"""
Market data service — builds MarketDataSnapshot for agents.

Fetches live LTP + historical OHLCV from Kite whenever authenticated.
Paper trading mode only affects order execution, not data quality.
Falls back to mock data only when no Kite session is available.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pytz

from sol.agents.base_agent import MarketDataSnapshot
from sol.broker.price_store import set_price

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Default watchlist — mid/small-cap stocks where retail trading dominates.
# Deliberately avoids Nifty 50 heavyweights that are saturated with institutional
# algos and HFTs. These Nifty Midcap/Smallcap names still show clean technical
# patterns because most participants are human traders and small fund managers.
# NIFTY 50 is kept solely for market regime detection — agents do not trade it.
DEFAULT_WATCHLIST = [
    # --- Index (regime detection only, not traded) ---
    ("NIFTY 50", "NSE"),

    # --- Nifty Midcap 100 — liquid, retail-driven ---
    ("DIXON", "NSE"),           # Electronics EMS — strong momentum stock
    ("IRCTC", "NSE"),           # Rail ticketing monopoly — clean patterns
    ("PERSISTENT", "NSE"),      # Mid-cap IT — trending well
    ("VOLTAS", "NSE"),          # Consumer durables — seasonal patterns
    ("TATACOMM", "NSE"),        # Telecom infrastructure — range-bound patterns
    ("GODREJPROP", "NSE"),      # Real estate — news-driven moves
    ("FEDERALBNK", "NSE"),      # Private bank — underanalysed
    ("RADICO", "NSE"),          # Spirits FMCG — steady patterns
    ("KFINTECH", "NSE"),        # Fintech mid-cap — low algo coverage
    ("ANGELONE", "NSE"),        # Broking — retail sentiment proxy

    # --- Nifty Smallcap 100 — even less algo penetration ---
    ("RVNL", "NSE"),            # Rail infra PSU — high retail interest
    ("IRFC", "NSE"),            # Rail finance — steady trending
    ("SJVN", "NSE"),            # Power PSU — low volatility patterns
    ("RAILTEL", "NSE"),         # Rail telecom — low coverage
    ("HFCL", "NSE"),            # Telecom products — breakout history
]

# Some symbols have different tradingsymbol values in the Kite instruments list
SYMBOL_ALIASES: dict[str, str] = {
    "BANKNIFTY": "NIFTY BANK",
}

# --- Instrument token cache ---
# Separate cache per exchange so NFO loads don't evict NSE tokens.
# Maps exchange → {"EXCHANGE:SYMBOL" → instrument_token}
_token_cache: dict[str, dict[str, int]] = {}
_token_cache_loaded_at: dict[str, Optional[datetime]] = {}
_CACHE_TTL_SECONDS = 86_400  # 24 hours


def _ensure_token_cache(client, exchange: str = "NSE") -> None:
    """Load (or refresh) the instrument token cache for *exchange*."""
    now = datetime.now(IST)
    loaded_at = _token_cache_loaded_at.get(exchange)
    if loaded_at is not None and (now - loaded_at).total_seconds() < _CACHE_TTL_SECONDS:
        return  # still fresh

    try:
        instruments = client.get_instruments(exchange)
        cache = {}
        for inst in instruments:
            key = f"{exchange}:{inst['tradingsymbol']}"
            cache[key] = inst["instrument_token"]
        _token_cache[exchange] = cache
        _token_cache_loaded_at[exchange] = now
        logger.info(f"Instrument token cache loaded ({len(instruments)} symbols, exchange={exchange})")
    except Exception as e:
        logger.error(f"Failed to load instruments for {exchange}: {e}")


def _get_token(client, symbol: str, exchange: str) -> Optional[int]:
    """Return the instrument token for a given symbol, loading cache if needed."""
    canonical = SYMBOL_ALIASES.get(symbol, symbol)
    key = f"{exchange}:{canonical}"
    exchange_cache = _token_cache.get(exchange, {})
    if key not in exchange_cache:
        _ensure_token_cache(client, exchange)
        exchange_cache = _token_cache.get(exchange, {})
    return exchange_cache.get(key)


# --- Indicator computation ---

def _compute_indicators(candles: list[dict]) -> dict:
    """
    Compute technical indicators from a list of OHLCV dicts.
    Requires at least 20 candles; returns {} if insufficient data.
    """
    try:
        import pandas as pd

        if len(candles) < 20:
            return {}

        df = pd.DataFrame(candles)
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)

        # RSI-14 (Wilder's smoothing via EWM)
        delta = close.diff()
        avg_gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        avg_loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = round(float((100 - 100 / (1 + rs)).iloc[-1]), 1)

        # SMAs
        sma_20 = round(float(close.rolling(20).mean().iloc[-1]), 2)
        sma_50 = (
            round(float(close.rolling(50).mean().iloc[-1]), 2)
            if len(df) >= 50 else None
        )

        # MACD (12, 26, 9)
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema_12 - ema_26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        # Bollinger Bands (20, ±2σ)
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = round(float((bb_mid + 2 * bb_std).iloc[-1]), 2)
        bb_lower = round(float((bb_mid - 2 * bb_std).iloc[-1]), 2)

        # Volume
        vol_sma_20 = int(volume.rolling(20).mean().iloc[-1])
        vol_ratio = round(float(volume.iloc[-1]) / vol_sma_20, 2) if vol_sma_20 else 1.0

        indicators: dict = {
            "rsi_14": rsi,
            "sma_20": sma_20,
            "macd_line": round(float(macd_line.iloc[-1]), 2),
            "macd_signal": round(float(macd_signal.iloc[-1]), 2),
            "macd_histogram": round(float(macd_hist.iloc[-1]), 2),
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "volume_sma_20": vol_sma_20,
            "volume_ratio": vol_ratio,  # >1 = above average volume
        }
        if sma_50 is not None:
            indicators["sma_50"] = sma_50

        return indicators

    except Exception as e:
        logger.warning(f"Indicator computation failed: {e}")
        return {}


def _kite_candles_to_dicts(raw: list[dict]) -> list[dict]:
    """Normalise kiteconnect candle dicts to plain serialisable dicts."""
    result = []
    for c in raw:
        result.append({
            "date": c["date"].strftime("%Y-%m-%d") if hasattr(c["date"], "strftime") else str(c["date"]),
            "open": round(float(c["open"]), 2),
            "high": round(float(c["high"]), 2),
            "low": round(float(c["low"]), 2),
            "close": round(float(c["close"]), 2),
            "volume": int(c["volume"]),
        })
    return result


def _kite_candles_to_dicts_intraday(raw: list[dict]) -> list[dict]:
    """Same as above but preserves time in date field for intraday candles."""
    result = []
    for c in raw:
        result.append({
            "date": c["date"].strftime("%Y-%m-%d %H:%M") if hasattr(c["date"], "strftime") else str(c["date"]),
            "open": round(float(c["open"]), 2),
            "high": round(float(c["high"]), 2),
            "low": round(float(c["low"]), 2),
            "close": round(float(c["close"]), 2),
            "volume": int(c["volume"]),
        })
    return result


# --- Public entry point ---

async def get_market_snapshots(
    watchlist: Optional[list[tuple[str, str]]] = None,
) -> list[MarketDataSnapshot]:
    """
    Fetch market data for the watchlist and return snapshots.
    Uses real Kite data whenever authenticated; falls back to mock otherwise.
    """
    from sol.broker.kite_client import get_kite_client

    symbols = watchlist or DEFAULT_WATCHLIST
    client = get_kite_client()

    if client.is_authenticated():
        return await _get_live_snapshots(symbols, client)
    else:
        logger.warning("Kite not authenticated — using paper mock snapshots")
        return await _get_paper_snapshots(symbols)


async def _get_live_snapshots(symbols: list[tuple[str, str]], client) -> list[MarketDataSnapshot]:
    """Fetch live LTP + historical OHLCV + indicators + news for each symbol."""
    from sol.services.news_service import get_news_for_symbols

    instrument_keys = [f"{exchange}:{symbol}" for symbol, exchange in symbols]

    # Live prices
    try:
        quotes = client.get_ltp(instrument_keys)
    except Exception as e:
        logger.error(f"LTP fetch failed: {e} — falling back to paper snapshots")
        return await _get_paper_snapshots(symbols)

    now = datetime.now(IST)
    daily_from = now - timedelta(days=90)   # 90 days → ~60 trading days
    intraday_from = now - timedelta(days=5)

    from sol.services.option_chain_service import FO_UNDERLYINGS, get_option_chain

    # Fetch news for all symbols concurrently (non-blocking — empty list on failure)
    symbol_list = [s for s, _ in symbols]
    news_map = await get_news_for_symbols(symbol_list)

    # Collect live LTPs first so option chain fetch has spot prices
    ltp_map: dict[str, float] = {}
    for symbol, exchange in symbols:
        key = f"{exchange}:{symbol}"
        ltp = float(quotes.get(key, {}).get("last_price", 0))
        if ltp:
            set_price(key, ltp)
        ltp_map[symbol] = ltp

    # Fetch option chains for index underlyings concurrently
    import asyncio
    fo_symbols = [s for s, _ in symbols if s in FO_UNDERLYINGS and ltp_map.get(s)]
    option_chain_results = await asyncio.gather(
        *[get_option_chain(s, ltp_map[s], client) for s in fo_symbols],
        return_exceptions=True,
    )
    option_chain_map: dict[str, dict] = {}
    for sym, result in zip(fo_symbols, option_chain_results):
        if isinstance(result, Exception):
            logger.warning(f"Option chain fetch failed for {sym}: {result}")
        elif result:
            option_chain_map[sym] = result

    snapshots = []
    for symbol, exchange in symbols:
        ltp = ltp_map[symbol]

        # Historical daily OHLCV
        ohlcv_daily: list[dict] = []
        ohlcv_15min: list[dict] = []
        try:
            token = _get_token(client, symbol, exchange)
            if token:
                raw_daily = client.get_historical_data(
                    token, daily_from, now, interval="day"
                )
                ohlcv_daily = _kite_candles_to_dicts(raw_daily)

                raw_15min = client.get_historical_data(
                    token, intraday_from, now, interval="15minute"
                )
                ohlcv_15min = _kite_candles_to_dicts_intraday(raw_15min)
            else:
                logger.warning(f"No instrument token found for {exchange}:{symbol}")
        except Exception as e:
            logger.warning(f"Historical data failed for {symbol}: {e}")

        indicators = _compute_indicators(ohlcv_daily) if ohlcv_daily else {}
        headlines = news_map.get(symbol, [])
        fo_data = option_chain_map.get(symbol, {})

        snapshots.append(MarketDataSnapshot(
            symbol=symbol,
            exchange=exchange,
            current_price=ltp,
            ohlcv_daily=ohlcv_daily,
            ohlcv_15min=ohlcv_15min,
            indicators=indicators,
            news_headlines=headlines,
            option_chain=fo_data.get("strikes", []),
            futures_price=fo_data.get("futures_price"),
            pcr=fo_data.get("pcr"),
        ))
        logger.debug(
            f"{exchange}:{symbol}: ltp={ltp} daily_bars={len(ohlcv_daily)} "
            f"15m_bars={len(ohlcv_15min)} indicators={list(indicators.keys())} "
            f"news={len(headlines)} option_strikes={len(fo_data.get('strikes', []))}"
        )

    return snapshots


def _mock_option_chain(spot: float, interval: float, lot_size: int, pcr: float) -> list[dict]:
    """Generate a realistic mock option chain around ATM for paper trading."""
    import random
    atm = round(round(spot / interval) * interval, 0)
    iv_base = random.uniform(12.0, 20.0)
    chain = []
    for i in range(-8, 9):
        strike = atm + i * interval
        moneyness = abs(i)
        ce_iv = round(iv_base + moneyness * 0.3 + random.uniform(-0.5, 0.5), 1)
        pe_iv = round(iv_base + moneyness * 0.3 + random.uniform(-0.5, 0.5), 1)
        # Rough Black-Scholes approximation for premium
        ce_ltp = round(max(spot - strike, 0) + spot * ce_iv / 100 * 0.2, 1)
        pe_ltp = round(max(strike - spot, 0) + spot * pe_iv / 100 * 0.2, 1)
        ce_oi = int(random.uniform(0.5, 3.0) * 1_000_000)
        pe_oi = int(ce_oi * (pcr if i <= 0 else 1 / pcr))
        chain.append({
            "strike": strike,
            "ce": {"ltp": ce_ltp, "oi": ce_oi, "iv": ce_iv, "delta": round(0.5 - i * 0.05, 2)},
            "pe": {"ltp": pe_ltp, "oi": pe_oi, "iv": pe_iv, "delta": round(-0.5 + i * 0.05, 2)},
        })
    return chain


async def _get_paper_snapshots(symbols: list[tuple[str, str]]) -> list[MarketDataSnapshot]:
    """
    Generate realistic mock snapshots for paper trading without a Kite session.
    Uses real news + mock option chain for index underlyings so agents can propose F&O.
    """
    from sol.broker.price_store import get_price
    from sol.services.news_service import get_news_for_symbols
    import random

    symbol_list = [s for s, _ in symbols]
    news_map = await get_news_for_symbols(symbol_list)

    base_prices = {
        "NIFTY 50": 24500.0, "NIFTY BANK": 52000.0,
        "DIXON": 15000.0, "IRCTC": 780.0, "PERSISTENT": 5200.0,
        "VOLTAS": 1450.0, "TATACOMM": 1700.0, "GODREJPROP": 2800.0,
        "FEDERALBNK": 195.0, "RADICO": 2100.0, "KFINTECH": 980.0,
        "ANGELONE": 2800.0, "RVNL": 420.0, "IRFC": 185.0,
        "SJVN": 110.0, "RAILTEL": 380.0, "HFCL": 120.0,
    }

    snapshots = []
    for symbol, exchange in symbols:
        base = base_prices.get(symbol, 1000.0)
        stored = get_price(f"{exchange}:{symbol}")
        if not stored:
            stored = base * (1 + random.uniform(-0.02, 0.02))
            set_price(f"{exchange}:{symbol}", stored)
        ltp = stored

        # 60 days of mock daily OHLCV
        ohlcv: list[dict] = []
        price = base
        for i in range(60):
            change = random.uniform(-0.015, 0.015)
            op = price
            cl = price * (1 + change)
            hi = max(op, cl) * (1 + random.uniform(0, 0.008))
            lo = min(op, cl) * (1 - random.uniform(0, 0.008))
            ohlcv.append({
                "date": (now - timedelta(days=60 - i)).strftime("%Y-%m-%d")
                if (now := datetime.now(IST)) else "",
                "open": round(op, 2), "high": round(hi, 2),
                "low": round(lo, 2), "close": round(cl, 2),
                "volume": random.randint(500_000, 5_000_000),
            })
            price = cl

        # Mock F&O data for index underlyings so agents can propose options in paper mode
        option_chain: list[dict] = []
        futures_price: float | None = None
        pcr: float | None = None
        if symbol == "NIFTY 50":
            pcr = round(random.uniform(0.7, 1.4), 2)
            option_chain = _mock_option_chain(ltp, 50.0, 50, pcr)
            futures_price = round(ltp * (1 + random.uniform(0.001, 0.003)), 1)
        elif symbol in ("NIFTY BANK", "BANKNIFTY"):
            pcr = round(random.uniform(0.7, 1.4), 2)
            option_chain = _mock_option_chain(ltp, 100.0, 15, pcr)
            futures_price = round(ltp * (1 + random.uniform(0.001, 0.003)), 1)

        snapshots.append(MarketDataSnapshot(
            symbol=symbol,
            exchange=exchange,
            current_price=round(ltp, 2),
            ohlcv_daily=ohlcv,
            ohlcv_15min=[],
            indicators=_compute_indicators(ohlcv),
            news_headlines=news_map.get(symbol, []),
            option_chain=option_chain,
            futures_price=futures_price,
            pcr=pcr,
        ))

    return snapshots
