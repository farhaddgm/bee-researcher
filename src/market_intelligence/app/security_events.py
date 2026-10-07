"""Minimal immutable security events; never store raw identities or requests."""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from app.database import SessionLocal
from app.models import SecurityEvent

LOGGER = logging.getLogger("bee.security")
_DETAILS = {"user_id", "method", "portal", "state", "publication_id", "target_id", "reason", "client_hash", "role", "active", "target_user_id", "fields", "count", "counts", "memberships_updated", "password_changed"}


def security_event_severity(action: str) -> str:
    if action.startswith(("admin_user.", "google_access.", "assistant.member.",
        "admin.password.", "admin.session.revoke", "assistant.telegram.", "privacy.data.", "admin.mfa.")):
        return "warning"
    return "info"


def client_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


async def record_security_event(action: str, *, actor_id=None, assistant_id=None, severity="info", details=None):
    safe = {k: str(v)[:160] for k, v in (details or {}).items() if k in _DETAILS}
    event = {"action": action[:80], "severity": severity, "actor_id": str(actor_id) if actor_id else None,
             "assistant_id": str(assistant_id) if assistant_id else None, "details": safe}
    LOGGER.log(logging.WARNING if severity in {"warning", "critical"} else logging.INFO,
               "security_event %s", json.dumps(event, ensure_ascii=True))
    try:
        async with SessionLocal() as session:
            session.add(SecurityEvent(action=event["action"], severity=severity, actor_id=actor_id,
                                      assistant_id=assistant_id, details=safe))
            await session.commit()
    except Exception:
        # Keep a separate actionable signal even if the database is unavailable.
        LOGGER.error("security_event_persistence_failed action=%s", event["action"])


async def security_incidents():
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    async with SessionLocal() as session:
        rows = (await session.scalars(select(SecurityEvent).where(SecurityEvent.created_at >= since,
            SecurityEvent.severity.in_(["warning", "critical"])).order_by(SecurityEvent.created_at.desc()).limit(100))).all()
    return [{"id": f"security:{r.id}", "assistant_id": str(r.assistant_id) if r.assistant_id else None,
             "message": f"Security: {r.action}", "severity": r.severity, "status": "open", "read": False,
             "created_at": r.created_at.isoformat(), "suggested_action": "review_security_events",
             "details": r.details} for r in rows]
