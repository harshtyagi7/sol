"""Options API — live option chain data for index underlyings."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/options", tags=["options"])


@router.get("/status")
async def get_options_status():
    """
    Diagnostic endpoint — shows exactly where F&O data loading breaks.

    Checks, in order:
      1. Kite authentication
      2. NFO instruments cache (kite.instruments("NFO"))
      3. Sample quote fetch for one NIFTY CE option (kite.quote())
    """
    from sol.broker.kite_client import get_kite_client
    import sol.services.option_chain_service as oc_svc

    client = get_kite_client()
    status: dict = {
        "kite_authenticated": client.is_authenticated(),
    }

    if not client.is_authenticated():
        status["next_step"] = "Log in via /api/auth/login first."
        return status

    # Step 1: instruments cache
    oc_svc._ensure_nfo_cache(client)
    status.update(oc_svc.get_nfo_status())

    if not oc_svc._nfo_cache:
        status["next_step"] = (
            "instruments('NFO') returned empty or failed — see 'error' above. "
            "Ensure your Kite API key & secret are correct and the access token is fresh."
        )
        return status

    # Step 2: try a live NIFTY spot quote
    try:
        spot_q = client.get_ltp(["NSE:NIFTY 50"])
        spot = float((spot_q.get("NSE:NIFTY 50") or {}).get("last_price", 0))
        status["nifty_spot_ltp"] = spot
    except Exception as e:
        status["spot_quote_error"] = str(e)
        status["next_step"] = "LTP fetch for NSE:NIFTY 50 failed — check API key / token."
        return status

    # Step 3: try fetching one NIFTY CE option quote to verify F&O quote access
    if spot:
        try:
            nfo_insts = [
                i for i in oc_svc._nfo_cache
                if i.get("name") == "NIFTY" and i.get("instrument_type") == "CE"
            ]
            expiry = oc_svc._nearest_expiry(nfo_insts)
            if expiry and nfo_insts:
                interval = oc_svc._strike_interval("NIFTY")
                atm = oc_svc._round_to_strike_interval(spot, interval)
                sample_inst = next(
                    (i for i in nfo_insts
                     if i.get("expiry") == expiry and i.get("strike") == atm),
                    nfo_insts[0],
                )
                sym_key = f"NFO:{sample_inst['tradingsymbol']}"
                q = client.get_full_quote([sym_key])
                q_data = q.get(sym_key, {})
                status["sample_option_quote"] = {
                    "symbol": sym_key,
                    "ltp": q_data.get("last_price"),
                    "oi": q_data.get("oi"),
                    "iv": q_data.get("implied_volatility"),
                    "greeks_available": bool(q_data.get("greeks")),
                }
                status["fo_quote_working"] = bool(q_data.get("last_price") is not None)
        except Exception as e:
            status["fo_quote_error"] = str(e)
            status["fo_quote_working"] = False
            status["next_step"] = (
                f"NFO instruments loaded but kite.quote() failed: {e}. "
                "This may be a Kite plan limitation or an expired token."
            )

    return status


@router.get("/{underlying}")
async def get_option_chain(underlying: str, strikes: int = 8):
    """
    Fetch live option chain for an underlying (e.g. NIFTY, BANKNIFTY, RELIANCE).

    Returns ATM ± strikes with CE/PE LTP, OI, IV, Greeks, PCR, and futures price.
    Requires an active Kite session.

    Query params:
      strikes: number of strikes each side of ATM (default 8, max 15)
    """
    from sol.broker.kite_client import get_kite_client
    from sol.services.market_data_service import DEFAULT_WATCHLIST
    from sol.services.option_chain_service import UNDERLYING_MAP, get_option_chain as fetch_chain

    client = get_kite_client()
    if not client.is_authenticated():
        raise HTTPException(status_code=401, detail="Kite session required for live F&O data")

    symbol = underlying.upper()
    if symbol not in UNDERLYING_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Underlying '{symbol}' not supported. Supported: {sorted(UNDERLYING_MAP.keys())}"
        )

    # Resolve the Kite LTP symbol (watchlist may use "NIFTY 50" while URL uses "NIFTY")
    _ltp_symbol_map = {
        "NIFTY": "NIFTY 50",
        "BANKNIFTY": "NIFTY BANK",
    }
    ltp_symbol = _ltp_symbol_map.get(symbol, symbol)
    watchlist_map = {s: ex for s, ex in DEFAULT_WATCHLIST}
    exchange = watchlist_map.get(ltp_symbol, "NSE")

    try:
        quotes = client.get_ltp([f"{exchange}:{ltp_symbol}"])
        spot_price = float(quotes.get(f"{exchange}:{ltp_symbol}", {}).get("last_price", 0))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch spot price: {e}")

    if not spot_price:
        raise HTTPException(status_code=502, detail="Could not fetch current spot price")

    chain = await fetch_chain(
        underlying_symbol=symbol,
        current_price=spot_price,
        client=client,
        strikes_each_side=min(strikes, 15),
    )

    if not chain:
        raise HTTPException(
            status_code=502,
            detail=(
                "No option chain data returned. "
                "Call GET /api/options/status for a full diagnostic."
            )
        )

    return chain
