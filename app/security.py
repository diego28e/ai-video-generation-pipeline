"""HMAC signing/verification for the engine <-> LMS handshake."""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional


def sign(body: bytes, secret: str) -> str:
    """Return the `X-Signature` header value for a raw request/webhook body."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(body: bytes, secret: str, signature: Optional[str]) -> bool:
    """Constant-time check of an `X-Signature` header against the body."""
    if not signature:
        return False
    return hmac.compare_digest(sign(body, secret), signature)
