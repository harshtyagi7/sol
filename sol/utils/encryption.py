"""Fernet symmetric encryption for sensitive stored values (e.g., Kite access tokens)."""

import base64
import hashlib

from cryptography.fernet import Fernet


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from the app's SECRET_KEY."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(value: str, secret: str) -> str:
    f = Fernet(_derive_key(secret))
    return f.encrypt(value.encode()).decode()


def decrypt(token: str, secret: str) -> str:
    f = Fernet(_derive_key(secret))
    return f.decrypt(token.encode()).decode()
