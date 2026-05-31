"""Inbound auth: bearer token + HMAC over the raw body.

Implemented as a helper (not a Depends) because we need the *raw* request body to
verify the HMAC before pydantic consumes/parses it.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from .config import get_settings
from .security import verify


async def authenticate(request: Request) -> bytes:
    """Validate bearer token + X-Signature; return the raw body on success."""
    settings = get_settings()

    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer ") or not _ct_eq(authz[len("Bearer "):], settings.engine_api_token):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    body = await request.body()
    signature = request.headers.get("x-signature")
    if not verify(body, settings.engine_hmac_secret, signature):
        raise HTTPException(status_code=401, detail="invalid or missing HMAC signature")
    return body


def _ct_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)
