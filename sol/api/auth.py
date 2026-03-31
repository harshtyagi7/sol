"""Zerodha Kite OAuth endpoints and session verification dependency."""

from datetime import datetime, timedelta

import pytz
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])
IST = pytz.timezone("Asia/Kolkata")

MAX_FAILED_ATTEMPTS = 2


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PinSet(BaseModel):
    pin: str  # 4–8 digits

class PinVerify(BaseModel):
    device_id: str
    pin: str
    label: str = "Unknown Device"

class DeviceAction(BaseModel):
    device_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_pin(pin: str) -> str:
    import hashlib
    return hashlib.sha256(pin.encode()).hexdigest()


def _check_pin(pin: str, pin_hash: str) -> bool:
    return _hash_pin(pin) == pin_hash


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


# ── PIN management ────────────────────────────────────────────────────────────

@router.get("/logout")
async def logout():
    """Invalidate the current Kite session."""
    from sol.database import get_session
    from sol.models.session import KiteSession
    from sol.broker.kite_client import get_kite_client
    from sqlalchemy import update

    async with get_session() as db:
        await db.execute(update(KiteSession).values(is_valid=False))

    client = get_kite_client()
    client.set_access_token("")

    return RedirectResponse(url="/")


@router.get("/pin/status")
async def pin_status():
    """Returns whether a PIN has been set."""
    from sol.database import get_session
    from sol.models.device_auth import AppPin
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(AppPin).limit(1))
        pin = result.scalar_one_or_none()
    return {"pin_set": pin is not None}


@router.post("/pin/set")
async def set_pin(body: PinSet):
    """Set or change the app PIN. Calling device is auto-approved."""
    if not body.pin.isdigit() or not (4 <= len(body.pin) <= 8):
        raise HTTPException(status_code=400, detail="PIN must be 4–8 digits")

    from sol.database import get_session
    from sol.models.device_auth import AppPin
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(AppPin).limit(1))
        existing = result.scalar_one_or_none()
        if existing:
            existing.pin_hash = _hash_pin(body.pin)
        else:
            db.add(AppPin(pin_hash=_hash_pin(body.pin)))

    return {"success": True}


@router.post("/device/verify")
async def verify_device_pin(body: PinVerify):
    """Verify PIN for a device. Blocks after MAX_FAILED_ATTEMPTS wrong attempts."""
    from sol.database import get_session
    from sol.models.device_auth import AppPin, DeviceAuth
    from sqlalchemy import select

    async with get_session() as db:
        # Check PIN is set
        pin_result = await db.execute(select(AppPin).limit(1))
        app_pin = pin_result.scalar_one_or_none()
        if not app_pin:
            raise HTTPException(status_code=400, detail="No PIN configured")

        # Get or create device record
        dev_result = await db.execute(select(DeviceAuth).where(DeviceAuth.device_id == body.device_id))
        device = dev_result.scalar_one_or_none()

        if device is None:
            device = DeviceAuth(device_id=body.device_id, label=body.label, status="pending", failed_attempts=0)
            db.add(device)
            await db.flush()

        if device.status == "blocked":
            raise HTTPException(status_code=403, detail="Device blocked. Contact the account owner to unblock.")

        device.last_seen = datetime.now(IST)
        device.label = body.label

        if _check_pin(body.pin, app_pin.pin_hash):
            device.status = "approved"
            device.failed_attempts = 0
            return {"approved": True}
        else:
            device.failed_attempts += 1
            if device.failed_attempts >= MAX_FAILED_ATTEMPTS:
                device.status = "blocked"
                raise HTTPException(status_code=403, detail="Too many wrong attempts. Device blocked.")
            remaining = MAX_FAILED_ATTEMPTS - device.failed_attempts
            raise HTTPException(status_code=401, detail=f"Wrong PIN. {remaining} attempt(s) remaining.")


@router.get("/device/status")
async def device_status(device_id: str):
    """Check the approval status of a device."""
    from sol.database import get_session
    from sol.models.device_auth import AppPin, DeviceAuth
    from sqlalchemy import select

    async with get_session() as db:
        pin_result = await db.execute(select(AppPin).limit(1))
        app_pin = pin_result.scalar_one_or_none()
        if not app_pin:
            # No PIN set — all devices pass
            return {"status": "approved", "pin_required": False}

        dev_result = await db.execute(select(DeviceAuth).where(DeviceAuth.device_id == device_id))
        device = dev_result.scalar_one_or_none()

        if device is None:
            return {"status": "pending", "pin_required": True}

        if device.status == "approved":
            # Refresh last_seen
            device.last_seen = datetime.now(IST)

        return {"status": device.status, "pin_required": True}


# ── Device management (owner only) ───────────────────────────────────────────

@router.get("/devices")
async def list_devices():
    """List all known devices."""
    from sol.database import get_session
    from sol.models.device_auth import DeviceAuth
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(DeviceAuth).order_by(DeviceAuth.created_at.desc()))
        devices = result.scalars().all()

    return [
        {
            "device_id": d.device_id,
            "label": d.label,
            "status": d.status,
            "failed_attempts": d.failed_attempts,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            "created_at": d.created_at.isoformat(),
        }
        for d in devices
    ]


@router.post("/devices/{device_id}/unblock")
async def unblock_device(device_id: str):
    """Unblock a blocked device."""
    from sol.database import get_session
    from sol.models.device_auth import DeviceAuth
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(DeviceAuth).where(DeviceAuth.device_id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        device.status = "approved"
        device.failed_attempts = 0

    return {"success": True}


@router.delete("/devices/{device_id}")
async def remove_device(device_id: str):
    """Remove a device (forces re-verification on next visit)."""
    from sol.database import get_session
    from sol.models.device_auth import DeviceAuth
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(DeviceAuth).where(DeviceAuth.device_id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        await db.delete(device)

    return {"success": True}
