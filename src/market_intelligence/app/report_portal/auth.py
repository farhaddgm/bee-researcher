import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.admin import (
    authenticate,
    _cookie_secure,
    _account_session_lifetime,
    _reader_nightly_expiry,
    request_activity,
)
from app.config import get_settings
from app.database import SessionLocal
from app.models import AdminSession, AdminUser
from app.portals import portal_spec
from app.security_controls import new_csrf_token
from .policy import enabled, has_report_access

SPEC = portal_spec("report")


def cookies(response, raw):
    now = datetime.now(timezone.utc)
    deadline = min(now + _account_session_lifetime(), _reader_nightly_expiry(now))
    for name, value, http_only in (
        (SPEC.session, raw, True),
        (SPEC.csrf, new_csrf_token(raw, get_settings()), False),
    ):
        response.set_cookie(
            name,
            value,
            expires=deadline,
            httponly=http_only,
            secure=_cookie_secure(),
            samesite="strict",
            path=SPEC.path,
        )


async def login(payload, response):
    enabled()
    raw, user = await authenticate(payload, require_mfa=False, portal="report")
    async with SessionLocal() as session:
        if not await has_report_access(session, user):
            await session.execute(
                delete(AdminSession).where(
                    AdminSession.token_hash == hashlib.sha256(raw.encode()).hexdigest()
                )
            )
            await session.commit()
            raise HTTPException(403, "report_access_denied")
    cookies(response, raw)
    return {"status": "logged_in"}


async def current(token):
    enabled()
    if not token:
        raise HTTPException(401, "authentication_required")
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(AdminSession, AdminUser)
                .join(AdminUser, AdminUser.id == AdminSession.user_id)
                .where(
                    AdminSession.token_hash
                    == hashlib.sha256(token.encode()).hexdigest(),
                    AdminSession.portal == "report",
                )
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(401, "session_expired")
        auth, user = row
        cutoff = min(
            _reader_nightly_expiry(auth.created_at),
            auth.created_at + timedelta(hours=get_settings().session_absolute_hours),
        )
        if (
            auth.expires_at <= now
            or cutoff <= now
            or not await has_report_access(session, user)
        ):
            await session.delete(auth)
            await session.commit()
            raise HTTPException(401, "session_expired")
        if request_activity.get():
            auth.expires_at = min(now + _account_session_lifetime(), cutoff)
            await session.commit()
    return user


async def logout(response, token):
    if token:
        async with SessionLocal() as session:
            await session.execute(
                delete(AdminSession).where(
                    AdminSession.portal == "report",
                    AdminSession.token_hash
                    == hashlib.sha256(token.encode()).hexdigest(),
                )
            )
            await session.commit()
    for name in (SPEC.session, SPEC.csrf):
        response.delete_cookie(name, path=SPEC.path)
    return {"status": "logged_out"}
