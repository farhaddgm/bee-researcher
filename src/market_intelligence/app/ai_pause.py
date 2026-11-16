"""Owner kill switch: when AI is paused for a project (or globally) no provider call is made."""
from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from sqlalchemy import select

LOGGER = logging.getLogger(__name__)
current_assistant: ContextVar[uuid.UUID | None] = ContextVar("ai_pause_assistant", default=None)
_CACHE: dict[str, tuple[float, bool]] = {}
TTL = 5.0


def invalidate() -> None:
    _CACHE.clear()


async def is_paused(assistant_id: uuid.UUID | None = None) -> bool:
    ident = str(assistant_id) if assistant_id else "default"
    hit = _CACHE.get(ident)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    from app.database import SessionLocal
    from app.token_quotas import service
    try:
        async with SessionLocal() as s:
            value = await service.paused(s, assistant_id)
    except Exception:  # the database being unreachable must not take the pipeline's own error handling away
        LOGGER.warning("ai_pause_lookup_failed")
        return False
    _CACHE[ident] = (time.monotonic(), value)
    return value


async def ensure_active(assistant_id: uuid.UUID | None = None) -> None:
    from app.openai_client import AIProviderError
    if await is_paused(assistant_id or current_assistant.get()):
        raise AIProviderError("ai_paused")
