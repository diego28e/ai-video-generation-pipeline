"""Outbound, HMAC-signed webhooks to the LMS, with simple bounded retry."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx

from .config import get_settings
from .security import sign

log = logging.getLogger("engine.webhooks")

_MAX_ATTEMPTS = 3


async def post_signed(url: str, event_type: str, payload: dict) -> bool:
    """POST one signed event. Returns True on a non-5xx response."""
    if not url:
        log.warning("skipping '%s' webhook: no callback URL configured", event_type)
        return False

    settings = get_settings()
    body = json.dumps({"type": event_type, **payload}).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Signature": sign(body, settings.engine_hmac_secret)}

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=body, headers=headers)
            if resp.status_code < 500:
                log.info("webhook '%s' -> %s [%s]", event_type, url, resp.status_code)
                return True
            log.warning("webhook '%s' got %s (attempt %d/%d)", event_type, resp.status_code, attempt, _MAX_ATTEMPTS)
        except Exception as exc:  # noqa: BLE001
            log.warning("webhook '%s' failed (attempt %d/%d): %r", event_type, attempt, _MAX_ATTEMPTS, exc)
        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(1.5 * attempt)
    return False


async def emit(job, event_type: str, payload: dict) -> None:
    """Emit a per-job event if the job subscribed to it."""
    if event_type not in job.callback.events:
        return
    await post_signed(job.callback.url, event_type, payload)


async def emit_idle(payload: dict, fallback_url: Optional[str]) -> None:
    """Emit the global idle event to the configured orchestrator URL (or a fallback)."""
    settings = get_settings()
    url = settings.orchestrator_webhook_url or (fallback_url or "")
    await post_signed(url, "idle", payload)
