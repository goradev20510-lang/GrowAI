"""
Clerk sign-in for the API: verifies the session token the React app sends.
Only the publishable key is needed; tokens are checked against Clerk's public keys.
"""
from __future__ import annotations
import base64
import binascii
import os
from functools import lru_cache

import jwt

from security.auth import ROLES


def publishable_key() -> str:
    return (os.getenv("CLERK_PUBLISHABLE_KEY") or "").strip()


def enabled() -> bool:
    return bool(publishable_key())


def issuer() -> str:
    """The Clerk frontend API URL, which is encoded inside the publishable key."""
    try:
        encoded = publishable_key().split("_", 2)[2]
        host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
    except (IndexError, binascii.Error, UnicodeDecodeError) as e:
        raise ValueError("CLERK_PUBLISHABLE_KEY is not a valid Clerk publishable key") from e
    return f"https://{host}"


@lru_cache(maxsize=4)
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, timeout=10)


def _signing_key(token: str):
    return _jwks(f"{issuer()}/.well-known/jwks.json").get_signing_key_from_jwt(token).key


def _role(user_id: str) -> str:
    admins = {i.strip() for i in os.getenv("CLERK_ADMIN_IDS", "").split(",") if i.strip()}
    if user_id in admins:
        return "admin"
    role = os.getenv("CLERK_DEFAULT_ROLE", "viewer").strip().lower()
    return role if role in ROLES else "viewer"


def authenticate(token: str, allowed_origins: list[str]) -> dict | None:
    """{"username", "role"} for a valid session token; None otherwise."""
    try:
        claims = jwt.decode(token, _signing_key(token), algorithms=["RS256"], issuer=issuer(),
                            leeway=10, options={"require": ["exp", "iss", "sub"]})
    except (jwt.PyJWTError, ValueError):
        return None
    azp = claims.get("azp")                  # the site the token was issued to
    if azp and azp not in allowed_origins:
        return None
    return {"username": claims["sub"], "role": _role(claims["sub"])}
