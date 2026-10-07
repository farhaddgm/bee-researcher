"""Telegram privileges use immutable IDs mapped to local active accounts."""
import uuid
from fastapi import HTTPException
from app.config import get_settings
from app.database import SessionLocal
from app.models import AdminUser
from app.security_events import record_security_event


async def telegram_actor(sender, assistant_id, *, feedback=False):
    from app import admin
    raw_id = sender.get("id") if isinstance(sender, dict) else None
    if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0 or sender.get("is_bot"):
        raise ValueError("telegram actor is not authorized")
    binding = get_settings().telegram_identity_bindings.get(str(raw_id))
    try:
        uid = uuid.UUID(binding) if binding else None
    except (ValueError, TypeError):
        uid = None
    async with SessionLocal() as session:
        user = await session.get(AdminUser, uid) if uid else None
    if not user or not user.active:
        await record_security_event("telegram.identity_denied", severity="warning")
        raise ValueError("telegram actor is not authorized")
    try:
        await admin._require_assistant_access(assistant_id, user)
    except HTTPException:
        await record_security_event("telegram.scope_denied", actor_id=user.id, severity="warning")
        raise ValueError("telegram actor is not authorized") from None
    if feedback and not admin.is_owner(user) and not admin.user_feedback_access_allowed(user):
        raise ValueError("telegram feedback is not authorized")
    return user
