"""Zerodha Kite OAuth endpoints and session verification dependency."""

from datetime import datetime, timedelta

import pytz
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])
IST = pytz.timezone("Asia/Kolkata")


async def verify_session():
    """
    FastAPI dependency — raises 401 if there is no valid authenticated Kite session.
    Inject on any route that should require authentication.
    """
    from sol.database import get_session
    from sol.models.session import KiteSession
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(
            select(KiteSession)
            .where(KiteSession.is_valid == True)
            .order_by(KiteSession.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in via Zerodha.")

    now = datetime.now(IST)
    if session.token_expiry and now > session.token_expiry:
        raise HTTPException(status_code=401, detail="Session expired. Please re-login.")

    return session


@router.get("/login")
async def get_login_url():
    """Redirects to Kite login page."""
    from sol.broker.kite_client import get_kite_client
    client = get_kite_client()
    url = client.get_login_url()
    return RedirectResponse(url=url)


@router.get("/callback")
async def kite_callback(request_token: str):
    """
    Kite redirects here after successful login with request_token.
    Exchange for access_token and store encrypted in DB.
    Rejects the login if the Zerodha user_id doesn't match ALLOWED_KITE_USER_ID.
    """
    from sol.broker.kite_client import get_kite_client
    from sol.database import get_session
    from sol.models.session import KiteSession
    from sol.utils.encryption import encrypt
    from sol.config import get_settings
    from sqlalchemy import update

    client = get_kite_client()
    settings = get_settings()

    try:
        session_data = client.complete_oauth(request_token)
        incoming_user_id = str(session_data.get("user_id", ""))

        # Enforce single-user access
        if settings.ALLOWED_KITE_USER_ID and incoming_user_id != settings.ALLOWED_KITE_USER_ID:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. This Sol instance is locked to a specific Zerodha account.",
            )

        access_token = session_data["access_token"]
        encrypted_token = encrypt(access_token, settings.SECRET_KEY)

        # Kite tokens expire at 6 AM IST next day
        now = datetime.now(IST)
        expiry = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now.hour >= 6:
            expiry = expiry + timedelta(days=1)

        async with get_session() as db:
            # Invalidate all previous sessions
            await db.execute(update(KiteSession).values(is_valid=False))
            db.add(KiteSession(
                access_token_encrypted=encrypted_token,
                token_expiry=expiry,
                is_valid=True,
                user_id=incoming_user_id,
                user_name=str(session_data.get("user_name", "")),
            ))

        return RedirectResponse(url="/?auth=success")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {str(e)}")


@router.get("/status")
async def auth_status():
    """Check if Kite session is valid. Used by the frontend auth gate."""
    from sol.broker.kite_client import get_kite_client
    from sol.database import get_session
    from sol.models.session import KiteSession
    from sol.config import get_settings
    from sol.utils.encryption import decrypt
    from sqlalchemy import select

    client = get_kite_client()
    settings = get_settings()

    async with get_session() as db:
        result = await db.execute(
            select(KiteSession)
            .where(KiteSession.is_valid == True)
            .order_by(KiteSession.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

    if not session:
        return {"authenticated": False, "reason": "No valid session found"}

    now = datetime.now(IST)
    if session.token_expiry and now > session.token_expiry:
        return {"authenticated": False, "reason": "Token expired. Please re-login."}

    if not client.is_authenticated():
        try:
            token = decrypt(session.access_token_encrypted, settings.SECRET_KEY)
            client.set_access_token(token)
        except Exception as e:
            return {"authenticated": False, "reason": str(e)}

    return {
        "authenticated": True,
        "user_name": session.user_name,
        "expires_at": session.token_expiry.isoformat() if session.token_expiry else None,
    }
