"""Read-only Contenter connection. Linking/sync never activates AI usage.

The separate research-context workflow explicitly approves a pinned snapshot.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from typing import Any

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.admin import current_admin, is_owner, _require_assistant_access
from app.config import Settings, get_settings
from app.database import SessionLocal
from app.deployment_drain import protected_work
from app.models import AdminAuditLog, AdminUser, AssistantWorkspace, ContenterBusinessLink, ContenterBusinessSnapshot

LOGGER = logging.getLogger(__name__)
ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_BYTES = 6_000_000
SECTION_KEYS = ("OVERVIEW", "SERVICES", "TARGET_MARKET", "PERSONAS", "VALUE_PROPOSITION", "COMPETITORS",
                "BRAND_VOICE", "BRAND_BOOK", "KEY_MESSAGES", "CONTENT_PILLARS", "GUIDELINES", "CHANNELS", "GOALS", "FAQ", "CALENDAR")
BLOCKED_STATES = {"access_revoked", "unavailable", "archived"}


class ContenterError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def safe_origin(value: str | None, *, api: bool = False) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    # Config is deployment-managed, not a browser-supplied arbitrary URL.
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ContenterError("invalid_configuration")
    if not api and parsed.path not in {"", "/"}:
        raise ContenterError("invalid_configuration")
    return value.rstrip("/")


def connection_status(settings: Settings) -> dict[str, Any]:
    try:
        api = safe_origin(settings.contenter_api_url, api=True)
        web = safe_origin(settings.contenter_web_url)
        token = settings.contenter_token.get_secret_value() if settings.contenter_token else ""
        valid = bool(api and len(token) >= 32)
    except (ContenterError, ValueError):
        api, web, valid = None, None, False
    return {"configured": valid, "api_url": api, "web_url": web,
            "sync_seconds": settings.contenter_sync_seconds, "ai_usage_enabled": False,
            "research_context_available": True}


class ContenterClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        status = connection_status(settings)
        if not status["configured"]:
            raise ContenterError("not_configured")
        self.base = str(status["api_url"])
        self.token = settings.contenter_token.get_secret_value()  # type: ignore[union-attr]
        self.transport = transport

    async def get(self, path: str, *, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self._get(path, params=params), timeout=8)
        except TimeoutError:
            raise ContenterError("unreachable") from None

    async def _get(self, path: str, *, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False, transport=self.transport) as client:
                async with client.stream("GET", self.base + "/integrations/researcher" + path,
                        params=params, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"}) as response:
                    if response.status_code in {401, 403}:
                        raise ContenterError("access_revoked")
                    if response.status_code == 404:
                        raise ContenterError("unavailable")
                    if not 200 <= response.status_code < 300:
                        raise ContenterError("upstream_error")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ContenterError("response_too_large")
                    result = json.loads(data)
                    if not isinstance(result, dict):
                        raise ContenterError("invalid_response")
                    return result
        except (httpx.HTTPError, OSError):
            raise ContenterError("unreachable") from None
        except (ValueError, UnicodeError):
            raise ContenterError("invalid_response") from None

    async def export(self, business_id: str) -> dict[str, Any]:
        if not ID.fullmatch(business_id):
            raise ContenterError("invalid_business_id")
        return normalize_export(await self.get("/businesses/" + quote(business_id, safe="") + "/export"), business_id)


def _text(value: object, limit: int = 50000) -> str:
    return str(value)[:limit] if isinstance(value, (str, int, float)) else ""


def _records(raw: dict[str, Any], key: str, allowed: tuple[str, ...], *, limit: int = 200) -> list[dict[str, Any]]:
    rows = raw.get(key, [])
    if not isinstance(rows, list):
        raise ContenterError("invalid_response")
    result = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            raise ContenterError("invalid_response")
        cleaned: dict[str, Any] = {}
        for name in allowed:
            value = row.get(name)
            if isinstance(value, bool) or value is None:
                cleaned[name] = value
            elif isinstance(value, list):
                cleaned[name] = [_text(x, 2000) for x in value[:50] if isinstance(x, str)]
            else:
                cleaned[name] = _text(value)
        result.append(cleaned)
    return result


def normalize_export(raw: dict[str, Any], expected_id: str) -> dict[str, Any]:
    if raw.get("schemaVersion") != 1 or isinstance(raw.get("schemaVersion"), bool):
        raise ContenterError("incompatible_schema")
    business = raw.get("business")
    if not isinstance(business, dict) or business.get("id") != expected_id or not isinstance(business.get("name"), str) or not business["name"].strip():
        raise ContenterError("invalid_response")
    if business.get("status") not in {"ACTIVE", "ARCHIVED"} or not isinstance(raw.get("sections"), list):
        raise ContenterError("invalid_response")
    sections = raw["sections"]
    if any(not isinstance(row, dict) or not isinstance(row.get("key"), str) or not isinstance(row.get("content"), str) for row in sections):
        raise ContenterError("invalid_response")
    keys = [row["key"] for row in sections]
    if not set(SECTION_KEYS).issubset(keys) or len(keys) != len(set(keys)):
        raise ContenterError("invalid_response")
    if any(not isinstance(raw.get(key), list) for key in ("facts", "terms", "notes", "references", "assets")):
        raise ContenterError("invalid_response")
    # No unknown keys, user identities, file paths, raw HTML or credentials are retained.
    out: dict[str, Any] = {"schemaVersion": 1, "business": {k: _text(business.get(k), 2000) for k in
        ("id", "name", "tagline", "industry", "website", "location", "language", "status", "origin", "buildState", "updatedAt")}}
    out["business"]["name"] = _text(business["name"], 160)
    specs = {
        "sections": ("key", "content", "source", "reviewedAt", "updatedAt"),
        "facts": ("id", "label", "value", "category", "sourceUrl", "note", "source", "verified", "validUntil", "isActive", "updatedAt"),
        "terms": ("id", "term", "kind", "alternatives", "note", "isActive"),
        "notes": ("id", "text", "status", "summary", "changedKeys", "isActive", "createdAt"),
        "references": ("id", "kind", "url", "title", "status", "isActive", "fetchedAt", "excerpt"),
        "assets": ("id", "kind", "title", "description", "url", "analysisStatus", "excerpt", "isActive"),
    }
    for key, allowed in specs.items():
        out[key] = _records(raw, key, allowed)
    # Structured asset analyses are summarized through their documented fields, not arbitrary JSON.
    for clean, source in zip(out["assets"], raw.get("assets", [])):
        analysis = source.get("analysis") if isinstance(source, dict) else None
        if isinstance(analysis, dict):
            clean["analysis"] = {k: _text(analysis.get(k), 6000) for k in ("summary", "visualStyle", "tone", "structure", "copy", "bestFor")}
            for key in ("messages", "guidelines"):
                clean["analysis"][key] = [_text(x, 2000) for x in analysis.get(key, [])[:50] if isinstance(x, str)] if isinstance(analysis.get(key), list) else []
    audit = raw.get("audit")
    if isinstance(audit, dict):
        out["audit"] = {"summary": _text(audit.get("summary"), 6000),
                        "score": audit.get("score") if isinstance(audit.get("score"), (float, int)) else None,
                        "strengths": [_text(x, 2000) for x in audit.get("strengths", [])[:50] if isinstance(x, str)] if isinstance(audit.get("strengths"), list) else [],
                        "issues": _records(audit, "issues", ("severity", "status", "type", "target", "title", "description", "recommendation"), limit=30)}
    health = raw.get("health")
    out["health"] = {"score": health.get("score")} if isinstance(health, dict) and isinstance(health.get("score"), (float, int)) else {}
    out["business"]["gaps"] = [_text(x, 2000) for x in business.get("gaps", [])[:50] if isinstance(x, str)] if isinstance(business.get("gaps"), list) else []
    return out


def export_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def cache_visible(link: ContenterBusinessLink, settings: Settings, *, now: datetime | None = None) -> bool:
    if link.state in BLOCKED_STATES or not link.last_success_at:
        return False
    return (now or datetime.now(timezone.utc)) - link.last_success_at <= timedelta(seconds=settings.contenter_cache_max_age_seconds)


async def link_view(assistant_id: uuid.UUID, settings: Settings) -> dict[str, Any]:
    async with SessionLocal() as session:
        link = await session.get(ContenterBusinessLink, assistant_id)
        if link is None:
            return {"linked": False, "configured": connection_status(settings)["configured"], "ai_usage_enabled": False}
        visible = cache_visible(link, settings) and connection_status(settings)["configured"]
        snapshot = await session.scalar(select(ContenterBusinessSnapshot).where(
            ContenterBusinessSnapshot.assistant_id == assistant_id, ContenterBusinessSnapshot.version == link.version,
            ContenterBusinessSnapshot.external_business_id == link.external_business_id)) if visible else None
        status = connection_status(settings)
        return {"linked": True, "external_business_id": link.external_business_id, "business_name": link.business_name,
                "state": link.state if visible or link.state in BLOCKED_STATES else "expired",
                "version": link.version, "last_attempt_at": link.last_attempt_at.isoformat() if link.last_attempt_at else None,
                "last_success_at": link.last_success_at.isoformat() if link.last_success_at else None,
                "error_code": link.error_code, "profile": snapshot.payload if snapshot else None,
                "content_hash": snapshot.content_hash if snapshot else None, "ai_usage_enabled": False,
                "open_url": status["web_url"] + "/app/businesses/" + quote(link.external_business_id, safe="") if status["web_url"] and visible else None}


async def _store_export(session: Any, link: ContenterBusinessLink, payload: dict[str, Any], actor: uuid.UUID | None) -> None:
    content_hash = export_hash(payload)
    previous = await session.scalar(select(ContenterBusinessSnapshot).where(
        ContenterBusinessSnapshot.assistant_id == link.assistant_id, ContenterBusinessSnapshot.version == link.version))
    if previous is None or previous.content_hash != content_hash or previous.external_business_id != link.external_business_id:
        maximum = await session.scalar(select(func.max(ContenterBusinessSnapshot.version)).where(ContenterBusinessSnapshot.assistant_id == link.assistant_id))
        link.version = int(maximum or 0) + 1
        session.add(ContenterBusinessSnapshot(assistant_id=link.assistant_id, external_business_id=link.external_business_id,
                    version=link.version, content_hash=content_hash, payload=payload))
        session.add(AdminAuditLog(user_id=actor, assistant_id=link.assistant_id, action="contenter.snapshot.created",
                    details={"business_id": link.external_business_id, "version": link.version}))
    link.business_name = payload["business"]["name"]
    link.state = "archived" if payload["business"]["status"] == "ARCHIVED" else "healthy"
    link.last_attempt_at = link.last_success_at = link.updated_at = datetime.now(timezone.utc)
    link.error_code = None


@protected_work
async def sync_link(assistant_id: uuid.UUID, settings: Settings, *, actor: uuid.UUID | None = None) -> None:
    async with SessionLocal() as session:
        link = await session.get(ContenterBusinessLink, assistant_id)
        if link is None:
            raise HTTPException(404, "contenter_link_missing")
        business_id, generation = link.external_business_id, link.generation
    try:
        payload = await ContenterClient(settings).export(business_id)
        error = None
    except ContenterError as exc:
        payload, error = None, exc.code
    async with SessionLocal() as session:
        # Serialize with link/unlink; recheck generation after network I/O.
        workspace = await session.scalar(select(AssistantWorkspace).where(AssistantWorkspace.id == assistant_id).with_for_update())
        if workspace is None or workspace.deleted_at is not None:
            return
        link = await session.get(ContenterBusinessLink, assistant_id)
        if link is None or link.generation != generation:
            return
        if payload is not None:
            await _store_export(session, link, payload, actor)
        else:
            link.state = error if error in BLOCKED_STATES else "stale"
            link.last_attempt_at = link.updated_at = datetime.now(timezone.utc)
            link.error_code = error
        await session.commit()


async def sync_loop(settings: Settings, stop: asyncio.Event) -> None:
    # Runs independently of crawling, scoring and publishing. Does not spend AI credits.
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
            break
        except TimeoutError:
            pass
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.contenter_sync_seconds)
            async with SessionLocal() as session:
                ids = list((await session.scalars(select(ContenterBusinessLink.assistant_id)
                    .join(AssistantWorkspace, AssistantWorkspace.id == ContenterBusinessLink.assistant_id)
                    .where(AssistantWorkspace.deleted_at.is_(None),
                           (ContenterBusinessLink.last_attempt_at.is_(None)) | (ContenterBusinessLink.last_attempt_at < cutoff))
                    .order_by(ContenterBusinessLink.last_attempt_at.asc().nullsfirst()).limit(25))).all())
            for assistant_id in ids:
                if stop.is_set():
                    return
                try:
                    await sync_link(assistant_id, settings)
                except Exception as exc:
                    # One bad link cannot starve other projects in this batch.
                    LOGGER.warning("contenter_link_sync_failure assistant_id=%s type=%s", assistant_id, type(exc).__name__)
        except Exception as exc:
            # Do not log upstream response bodies, URLs with query strings or credentials.
            LOGGER.warning("contenter_sync_failure type=%s", type(exc).__name__)


router = APIRouter(prefix="/admin/api", tags=["contenter"])


async def _user(token: str | None, assistant_id: uuid.UUID | None = None, *, write: bool = False) -> AdminUser:
    user = await current_admin(token)
    if assistant_id is None:
        if not is_owner(user):
            raise HTTPException(403, "owner role required")
    else:
        workspace = await _require_assistant_access(assistant_id, user, write=write)
        if workspace.deleted_at is not None:
            raise HTTPException(404, "assistant not found")
    return user


@router.get("/contenter/status")
async def status(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    await _user(token)
    return connection_status(get_settings())


@router.post("/contenter/test")
async def test_connection(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    await _user(token)
    try:
        result = await ContenterClient(get_settings()).get("/ping")
        if result.get("service") != "contenter" or result.get("schemaVersion") != 1 or result.get("ok") is not True:
            raise ContenterError("invalid_response")
        return {"state": "healthy", "schema_version": 1, "ai_usage_enabled": False}
    except ContenterError as exc:
        return {"state": "unavailable", "error_code": exc.code, "ai_usage_enabled": False}


@router.get("/assistants/{assistant_id}/contenter/businesses")
async def businesses(assistant_id: uuid.UUID, q: str = Query(default="", max_length=200), page: int = Query(default=1, ge=1),
        token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    await _user(token, assistant_id, write=True)
    try:
        result = await ContenterClient(get_settings()).get("/businesses", params={"q": q, "page": page, "pageSize": 20})
        if not isinstance(result.get("items"), list) or not isinstance(result.get("totalPages"), int):
            raise ContenterError("invalid_response")
        items = [{k: _text(row.get(k), 2000) for k in ("id", "name", "industry", "tagline", "status")} for row in result["items"][:20]
                 if isinstance(row, dict) and ID.fullmatch(str(row.get("id", "")))]
        return {"items": items, "page": page, "total_pages": min(max(result["totalPages"], 1), 10000)}
    except ContenterError as exc:
        raise HTTPException(409 if exc.code == "not_configured" else 502, exc.code) from None


class LinkRequest(BaseModel):
    business_id: str = Field(min_length=1, max_length=128, pattern=ID.pattern)


@router.get("/assistants/{assistant_id}/contenter")
async def get_link(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    user = await _user(token, assistant_id)
    try:
        await _require_assistant_access(assistant_id, user, write=True)
        can_write = True
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        can_write = False
    return {**await link_view(assistant_id, get_settings()), "can_write": can_write}


@router.put("/assistants/{assistant_id}/contenter")
async def set_link(assistant_id: uuid.UUID, payload: LinkRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    user = await _user(token, assistant_id, write=True)
    settings = get_settings()
    try:
        profile = await ContenterClient(settings).export(payload.business_id)
    except ContenterError as exc:
        raise HTTPException(409 if exc.code == "not_configured" else 502, exc.code) from None
    if profile["business"]["status"] != "ACTIVE":
        raise HTTPException(409, "business_archived")
    # Remote I/O is bounded but may outlive a revocation of this user's access.
    user = await _user(token, assistant_id, write=True)
    async with SessionLocal() as session:
        workspace = await session.scalar(select(AssistantWorkspace).where(AssistantWorkspace.id == assistant_id).with_for_update())
        if workspace is None or workspace.deleted_at is not None:
            raise HTTPException(404, "assistant not found")
        link = await session.get(ContenterBusinessLink, assistant_id)
        if link is None:
            link = ContenterBusinessLink(assistant_id=assistant_id, external_business_id=payload.business_id, version=0)
            session.add(link)
        link.external_business_id, link.generation = payload.business_id, uuid.uuid4()
        link.business_name = profile["business"]["name"]
        link.state = "healthy"
        await _store_export(session, link, profile, user.id)
        session.add(AdminAuditLog(user_id=user.id, assistant_id=assistant_id, action="contenter.link.set", details={"business_id": payload.business_id}))
        await session.commit()
    return {**await link_view(assistant_id, settings), "can_write": True}


@router.delete("/assistants/{assistant_id}/contenter")
async def unlink(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    user = await _user(token, assistant_id, write=True)
    async with SessionLocal() as session:
        await session.scalar(select(AssistantWorkspace).where(AssistantWorkspace.id == assistant_id).with_for_update())
        await session.execute(delete(ContenterBusinessLink).where(ContenterBusinessLink.assistant_id == assistant_id))
        session.add(AdminAuditLog(user_id=user.id, assistant_id=assistant_id, action="contenter.link.removed", details={}))
        await session.commit()
    return {"linked": False, "ai_usage_enabled": False, "can_write": True}


@router.post("/assistants/{assistant_id}/contenter/sync")
async def sync(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    user = await _user(token, assistant_id, write=True)
    await sync_link(assistant_id, get_settings(), actor=user.id)
    return {**await link_view(assistant_id, get_settings()), "can_write": True}


@router.get("/assistants/{assistant_id}/contenter/versions")
async def versions(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, Any]:
    await _user(token, assistant_id)
    async with SessionLocal() as session:
        link = await session.get(ContenterBusinessLink, assistant_id)
        if link is None or not cache_visible(link, get_settings()) or not connection_status(get_settings())["configured"]:
            return {"items": []}
        snapshots = (await session.scalars(select(ContenterBusinessSnapshot).where(
            ContenterBusinessSnapshot.assistant_id == assistant_id, ContenterBusinessSnapshot.external_business_id == link.external_business_id)
            .order_by(ContenterBusinessSnapshot.version.desc()).limit(20))).all()
        return {"items": [{"version": item.version, "content_hash": item.content_hash, "created_at": item.created_at.isoformat()} for item in snapshots]}
