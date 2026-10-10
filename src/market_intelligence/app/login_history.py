"""Owner-only login history in the existing append-only security journal.

Email snapshots stay in the database, never in application logs or alerts.
No account foreign key is required, so rejected and deleted accounts remain
visible. OAuth identities are supplied only after signature verification.
"""
import logging
import uuid

from sqlalchemy import String, case, cast, func, literal, select, union_all

from app.database import SessionLocal
from app.google_auth import normalize_email
from app.models import AdminAuditLog, AdminUser, SecurityEvent

LOGGER = logging.getLogger("bee.security")
ACTION = "auth.login"
PAGE_SIZE = 10


async def record_login_attempt(*, method: str, portal: str, successful: bool,
                               email: str | None = None, username: str | None = None,
                               actor_id: uuid.UUID | None = None, reason: str | None = None) -> None:
    try:
        async with SessionLocal() as session:
            if username:
                identifier = username.strip().lower()
                account = await session.scalar(select(AdminUser).where(
                    AdminUser.email == normalize_email(identifier) if "@" in identifier
                    else AdminUser.username == identifier))
                if account:
                    actor_id = account.id
                    email = account.email
                elif "@" in identifier:
                    email = identifier
            details = {
                "email": email.strip().lower()[:320] if email else None,
                "username": username.strip()[:320] if username else None,
                "method": method, "portal": portal,
                "outcome": "success" if successful else "failure",
                "reason": reason,
            }
            # Informational events are excluded from the shared incident feed.
            session.add(SecurityEvent(action=ACTION, severity="info", actor_id=actor_id, details=details))
            await session.commit()
    except Exception:
        # Auth keeps the existing best-effort journal policy during DB outages.
        LOGGER.error("login_history_persistence_failed method=%s portal=%s", method, portal)


async def list_login_history(user: AdminUser, *, page: int = 1) -> dict:
    from app.admin import _require_owner
    _require_owner(user)
    keys = ("email", "username", "method", "portal", "outcome", "reason")
    current = select((literal("login:") + cast(SecurityEvent.id, String)).label("id"),
        SecurityEvent.created_at, *[SecurityEvent.details[key].astext.label(key) for key in keys]
    ).where(SecurityEvent.action == ACTION)
    # Existing records remain visible. Their email is recoverable only while
    # the account still exists; older rejected identities were never retained.
    legacy = select((literal("audit:") + cast(AdminAuditLog.id, String)).label("id"),
        AdminAuditLog.created_at,
        func.coalesce(AdminAuditLog.details["email"].astext, AdminUser.email).label("email"),
        AdminUser.username.label("username"),
        func.coalesce(AdminAuditLog.details["method"].astext,
                      case((AdminAuditLog.action == "auth.google.failed", "google"), else_="password")).label("method"),
        AdminAuditLog.details["portal"].astext.label("portal"),
        case((AdminAuditLog.action == "admin.login", "success"), else_="failure").label("outcome"),
        AdminAuditLog.details["reason"].astext.label("reason")
    ).outerjoin(AdminUser, AdminUser.id == AdminAuditLog.user_id).where(
        AdminAuditLog.action.in_(("admin.login", "auth.google.failed")),
        func.coalesce(AdminAuditLog.details["login_history_recorded"].astext, "") != "true")
    history = union_all(current, legacy).subquery()
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(history)) or 0
        rows = (await session.execute(select(history)
            .order_by(history.c.created_at.desc(), history.c.id.desc())
            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE))).mappings().all()
    return {"page": page, "page_size": PAGE_SIZE, "total": total,
            "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "attempts": [{"id": row["id"], "created_at": row["created_at"].isoformat(),
                          **{key: row[key] for key in keys}}
                         for row in rows]}
