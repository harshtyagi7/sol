"""
Option chain service — fetches live F&O data from Kite for index underlyings.

For each underlying (e.g. NIFTY, BANKNIFTY):
  - Loads NFO instruments list (cached daily)
  - Finds the nearest weekly/monthly expiry
  - Selects ATM ± 10 strikes (CE + PE each)
  - Fetches full quotes: LTP, OI, IV, Greeks
  - Also fetches the nearest futures contract price
  - Computes PCR (put-call ratio by OI)

Used by market_data_service to attach F&O context to index snapshots.
"""

import logging
from datetime import datetime, date
from typing import Optional

import pytz

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------------------------------------------------
# NFO instrument cache  (symbol, expiry, strike, type → token)
# ---------------------------------------------------------------------------

_nfo_cache: list[dict] = []
_nfo_cache_loaded_at: Optional[datetime] = None
_NFO_CACHE_TTL_SECONDS = 86_400  # refresh daily


_nfo_load_error: str = ""  # last error, shown in /api/options/status


def _ensure_nfo_cache(client) -> None:
    global _nfo_cache, _nfo_cache_loaded_at, _nfo_load_error
    now = datetime.now(IST)
    if (
        _nfo_cache_loaded_at is not None
        and (now - _nfo_cache_loaded_at).total_seconds() < _NFO_CACHE_TTL_SECONDS
    ):
        return
    try:
        instruments = client.get_instruments("NFO")
        if not instruments:
            _nfo_load_error = (
                "kite.instruments('NFO') returned an empty list. "
                "Check that the NFO segment is enabled on your Kite Connect API app: "
                "https://developers.kite.trade → your app → Segments → enable NFO."
            )
            logger.warning(_nfo_load_error)
            return
        _nfo_cache = instruments
        _nfo_cache_loaded_at = now
        _nfo_load_error = ""
        logger.info(
            f"NFO instrument cache loaded: {len(_nfo_cache)} instruments "
            f"(sample: {_nfo_cache[0].get('tradingsymbol', '?')})"
        )
    except Exception as e:
        _nfo_load_error = (
            f"Failed to load NFO instruments: {e}. "
            "Ensure the NFO segment is enabled in your Kite Connect API app settings "
            "at https://developers.kite.trade and that your access token is valid."
        )
        logger.error(_nfo_load_error)


def get_nfo_status() -> dict:
    """Return diagnostic info about the NFO instrument cache."""
    return {
        "loaded": bool(_nfo_cache),
        "instrument_count": len(_nfo_cache),
        "loaded_at": _nfo_cache_loaded_at.isoformat() if _nfo_cache_loaded_at else None,
        "error": _nfo_load_error or None,
        "sample_instruments": [
            {"tradingsymbol": i.get("tradingsymbol"), "expiry": str(i.get("expiry")),
             "instrument_type": i.get("instrument_type"), "strike": i.get("strike")}
            for i in _nfo_cache[:5]
        ] if _nfo_cache else [],
        "setup_instructions": (
            "To enable F&O data: log in to https://developers.kite.trade, "
            "open your API app, go to Segments, and enable NFO. "
            "Then re-authenticate (tokens are per-session)."
        ) if not _nfo_cache else None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Kite uses these name prefixes for option underlyings in NFO
UNDERLYING_MAP = {
    "NIFTY 50":   "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY":      "NIFTY",
    "BANKNIFTY":  "BANKNIFTY",
    "RELIANCE":   "RELIANCE",
    "INFY":       "INFY",
    "TCS":        "TCS",
    "HDFCBANK":   "HDFCBANK",
    "ICICIBANK":  "ICICIBANK",
    "SBIN":       "SBIN",
}

# Lot sizes (approximate — Kite instruments list has exact `lot_size`)
DEFAULT_LOT_SIZES = {
    "NIFTY":      50,
    "BANKNIFTY":  15,
    "RELIANCE":   250,
    "INFY":       300,
    "TCS":        150,
    "HDFCBANK":   550,
    "ICICIBANK":  700,
    "SBIN":       1500,
}


def _nearest_expiry(instruments: list[dict]) -> Optional[date]:
    """Return the nearest future expiry date from a filtered instrument list."""
    today = date.today()
    expiries = set()
    for inst in instruments:
        exp = inst.get("expiry")
        if exp and exp >= today:
            expiries.add(exp)
    return min(expiries) if expiries else None


def _round_to_strike_interval(price: float, interval: float) -> float:
    return round(round(price / interval) * interval, 2)


def _strike_interval(underlying: str) -> float:
    intervals = {
        "NIFTY":      50.0,
        "BANKNIFTY":  100.0,
    }
    return intervals.get(underlying, 50.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_option_chain(
    underlying_symbol: str,
    current_price: float,
    client,
    strikes_each_side: int = 8,
) -> dict:
    """
    Fetch option chain for an underlying.

    Returns:
        {
          "underlying":  "NIFTY",
          "expiry":      "2024-04-25",
          "spot_price":  22500.0,
          "futures_price": 22530.0,
          "pcr":         0.87,
          "atm_iv":      14.5,
          "strikes": [
            {
              "strike": 22500,
              "ce": {"ltp": 120, "oi": 5000000, "iv": 14.2, "delta": 0.5, ...},
              "pe": {"ltp": 115, "oi": 4000000, "iv": 14.8, "delta": -0.5, ...},
            }, ...
          ]
        }
    Returns {} if Kite is not authenticated or NFO data unavailable.
    """
    _ensure_nfo_cache(client)
    if not _nfo_cache:
        return {}

    nfo_name = UNDERLYING_MAP.get(underlying_symbol)
    if not nfo_name:
        return {}

    interval = _strike_interval(nfo_name)
    atm_strike = _round_to_strike_interval(current_price, interval)

    # Filter to this underlying
    underlying_insts = [
        i for i in _nfo_cache
        if i.get("name") == nfo_name
    ]
    if not underlying_insts:
        logger.warning(f"No NFO instruments found for {nfo_name}")
        return {}

    expiry = _nearest_expiry([i for i in underlying_insts if i.get("instrument_type") in ("CE", "PE")])
    if not expiry:
        return {}

    # Build target strike list
    strikes_wanted = [
        atm_strike + (i * interval)
        for i in range(-strikes_each_side, strikes_each_side + 1)
    ]

    # Find CE/PE tokens for those strikes at the nearest expiry
    option_tokens: dict[str, dict] = {}  # "NFO:NIFTY24APR22500CE" → inst dict
    futures_token: Optional[int] = None
    futures_key: Optional[str] = None

    for inst in underlying_insts:
        itype = inst.get("instrument_type")
        if itype in ("CE", "PE") and inst.get("expiry") == expiry:
            if inst.get("strike") in strikes_wanted:
                key = f"NFO:{inst['tradingsymbol']}"
                option_tokens[key] = inst
        elif itype == "FUT":
            # Pick the nearest-expiry futures contract
            inst_expiry = inst.get("expiry")
            if inst_expiry and inst_expiry >= date.today():
                if futures_token is None or inst_expiry < underlying_insts[0].get("expiry", date.max):
                    futures_token = inst.get("instrument_token")
                    futures_key = f"NFO:{inst['tradingsymbol']}"

    if not option_tokens:
        logger.warning(f"No option instruments matched for {nfo_name} expiry={expiry}")
        return {}

    # Batch quote
    all_keys = list(option_tokens.keys())
    if futures_key:
        all_keys.append(futures_key)

    try:
        quotes = client.get_full_quote(all_keys)
    except Exception as e:
        logger.error(f"Option chain quote failed for {nfo_name}: {e}")
        return {}

    # Parse futures price
    futures_price: Optional[float] = None
    if futures_key and futures_key in quotes:
        futures_price = float(quotes[futures_key].get("last_price", 0)) or None

    # Build strike table
    strike_map: dict[float, dict] = {}
    for key, inst in option_tokens.items():
        q = quotes.get(key, {})
        strike = float(inst["strike"])
        itype = inst["instrument_type"]  # CE or PE

        entry = {
            "ltp": round(float(q.get("last_price", 0)), 2),
            "oi": int(q.get("oi", 0)),
            "oi_change": int(q.get("oi_day_high", 0)) - int(q.get("oi_day_low", 0)),
            "volume": int(q.get("volume", 0)),
            "iv": round(float(q.get("implied_volatility") or 0), 2),
            "tradingsymbol": inst["tradingsymbol"],
            "token": inst["instrument_token"],
        }
        # Greeks (available in Kite full quote under "greeks" key)
        greeks = q.get("greeks") or {}
        if greeks:
            entry["delta"] = round(float(greeks.get("delta", 0)), 4)
            entry["theta"] = round(float(greeks.get("theta", 0)), 4)
            entry["gamma"] = round(float(greeks.get("gamma", 0)), 6)
            entry["vega"]  = round(float(greeks.get("vega", 0)), 4)

        if strike not in strike_map:
            strike_map[strike] = {"strike": strike, "ce": {}, "pe": {}}
        strike_map[strike][itype.lower()] = entry

    strikes_sorted = sorted(strike_map.values(), key=lambda x: x["strike"])

    # PCR = total PE OI / total CE OI
    total_ce_oi = sum(s["ce"].get("oi", 0) for s in strikes_sorted if s.get("ce"))
    total_pe_oi = sum(s["pe"].get("oi", 0) for s in strikes_sorted if s.get("pe"))
    pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else None

    # ATM IV = average of CE and PE IV at ATM strike
    atm_data = strike_map.get(atm_strike, {})
    ce_iv = atm_data.get("ce", {}).get("iv", 0)
    pe_iv = atm_data.get("pe", {}).get("iv", 0)
    atm_iv = round((ce_iv + pe_iv) / 2, 2) if (ce_iv or pe_iv) else None

    return {
        "underlying": nfo_name,
        "expiry": str(expiry),
        "spot_price": current_price,
        "futures_price": futures_price,
        "atm_strike": atm_strike,
        "pcr": pcr,
        "atm_iv": atm_iv,
        "lot_size": DEFAULT_LOT_SIZES.get(nfo_name, 50),
        "strikes": strikes_sorted,
    }


# Underlyings for which we fetch option chains automatically
FO_UNDERLYINGS = {"NIFTY 50", "NIFTY BANK"}
