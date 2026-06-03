import hashlib
import hmac
import os

from fastapi import Header, HTTPException, Query

PLUCK_PASSWORD = os.environ.get("PLUCK_PASSWORD", "pluck")

# Deterministic token derived from the password — survives server restarts.
# Same password always produces the same 64-char hex token.
_SESSION_TOKEN = hmac.new(
    PLUCK_PASSWORD.encode(),
    b"pluck-session-v1",
    hashlib.sha256,
).hexdigest()


def generate_token() -> str:
    return _SESSION_TOKEN


def verify_token(token: str) -> bool:
    return hmac.compare_digest(token, _SESSION_TOKEN)


def check_auth(authorization: str | None, token: str | None) -> str:
    """Plain function — call directly when you own both parameters."""
    raw = None
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw = parts[1]
    if raw is None and token:
        raw = token
    if raw is None or not verify_token(raw):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return raw


async def require_auth(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> str:
    """FastAPI dependency — for routes where Depends() injection is reliable."""
    return check_auth(authorization, token)
