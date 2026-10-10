from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, cast

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
from sqlalchemy import delete, func, literal, select, text, tuple_

from app import admin
from app.config import get_settings
from app.database import SessionLocal
from app.models import AdminSession, AdminUser
from app.security_controls import ADMIN_SESSION_COOKIE
from app.news_chat import providers, service as svc
from app.news_chat.context import context_for
from app.news_chat.models import ChatConversation, ChatGeneration, ChatPolicy
from app.news_chat.schemas import Feedback, Grant, Policy, Start

router = APIRouter()
COOKIE = admin.USER_SESSION_COOKIE
ROOT = Path(__file__).parent


@router.get("/assets/news-chat/{asset}", include_in_schema=False)
async def asset(asset: str):
    types = {"chat.js": "application/javascript", "chat.css": "text/css", "i18n.js": "application/javascript", "admin.js": "application/javascript"}
    if asset not in types:
        raise HTTPException(404)
    return FileResponse(ROOT / asset, media_type=types[asset], headers={"Cache-Control": "no-cache"})


@router.get("/user/api/chat/models")
async def models(assistant_id: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    svc.require(user)
    available = await admin.reader_assistants(user)
    if str(assistant_id) not in {str(a["id"]) for a in cast(list[dict[str, Any]], available["assistants"])}:
        raise HTTPException(404, "news_unavailable")
    async with SessionLocal() as s:
        p = await svc.policy(s)
        rows = []
        for m in p.models:
            try:
                svc.model_for(p, assistant_id, m.key)
            except HTTPException:
                continue
            rows.append({"key": m.key, "provider": m.provider, "label": m.label})
    return {"models": rows, "daily_requests": p.user_daily_requests, "enabled": bool(rows),
            "scope": "user_portal", "reason": None if rows else (
                "chat_disabled" if not get_settings().news_chat_enabled or not p.enabled else "model_unavailable")}


@router.get("/user/api/publications/{pid}/chat-context")
async def context(pid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    svc.require(user)
    async with SessionLocal() as s:
        pub = await svc.publication(s, pid, user)
        return {**context_for(pub.message_text, pub.published_at.isoformat() if pub.published_at else None), "assistant_id": str(pub.assistant_id)}


@router.get("/user/api/publications/{pid}/conversations")
async def conversations(pid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    svc.require(user)
    async with SessionLocal() as s:
        await svc.publication(s, pid, user)
        # The enforced account cap is 500. Do not make its older conversations
        # unreachable behind a silently shorter fifty-option selector.
        rows = (await s.scalars(select(ChatConversation).where(ChatConversation.user_id == user.id, ChatConversation.publication_id == pid, ChatConversation.deleted_at.is_(None)).order_by(ChatConversation.created_at.desc(), ChatConversation.id.desc()).limit(500))).all()
        return {"conversations": [{"id": str(c.id), "provider": c.provider, "created_at": c.created_at.isoformat(), "context_version": c.context["version"]} for c in rows]}


@router.post("/user/api/publications/{pid}/conversations", status_code=201)
async def start(pid: uuid.UUID, payload: Start, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    svc.require(user)
    async with SessionLocal() as s:
        pub = await svc.publication(s, pid, user)
        m = svc.model_for(await svc.policy(s), pub.assistant_id, payload.model_key)
        # Count and insert share the cross-process admission lock. Two tabs
        # cannot both claim the last available conversation slot.
        await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": svc.LOCK})
        count = await s.scalar(select(func.count()).select_from(ChatConversation).where(ChatConversation.user_id == user.id, ChatConversation.deleted_at.is_(None))) or 0
        if count >= 500:
            raise HTTPException(429, "quota_exceeded")
        c = ChatConversation(id=uuid.uuid4(), user_id=user.id, assistant_id=pub.assistant_id, publication_id=pid,
                             context=context_for(pub.message_text, pub.published_at.isoformat() if pub.published_at else None), provider=m.provider, created_at=svc.now())
        s.add(c)
        await s.commit()
        return {"id": str(c.id), "provider": c.provider, "context": c.context}


@router.get("/user/api/conversations/{cid}/messages")
async def messages(cid: uuid.UUID, before: uuid.UUID | None = None, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    async with SessionLocal() as s:
        c = await svc.conversation(s, cid, user)
        query = select(ChatGeneration).where(ChatGeneration.conversation_id == cid)
        if before:
            prior = await s.scalar(select(ChatGeneration).where(ChatGeneration.id == before, ChatGeneration.conversation_id == cid))
            if prior is None:
                raise HTTPException(404)
            query = query.where(tuple_(ChatGeneration.created_at, ChatGeneration.id) < tuple_(literal(prior.created_at), literal(prior.id)))
        # UUID breaks timestamp ties, including batches written in the same
        # transaction. Fetch a look-ahead row, not an empty extra page.
        rows = (await s.scalars(query.order_by(ChatGeneration.created_at.desc(), ChatGeneration.id.desc()).limit(31))).all()
        page = rows[:30]
        return {"messages": [svc.view(g) for g in reversed(page)], "context": c.context, "older_before": str(page[-1].id) if len(rows) > 30 else None}


@router.post("/user/api/conversations/{cid}/messages", status_code=202)
async def send(cid: uuid.UUID, payload: svc.Question, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    return await svc.send(cid, payload, user, token or "")


@router.get("/user/api/chat-generations/{gid}/events")
async def events(gid: uuid.UUID, request: Request, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token, touch=False)
    async with SessionLocal() as s:
        await svc.authorized_generation(s, gid, user)
    async def output():
        previous = None
        while not await request.is_disconnected():
            try:
                u = await admin.current_reader(token, touch=False)
                async with SessionLocal() as s:
                    g = await svc.authorized_generation(s, gid, u)
                    data = svc.view(g)
                encoded = json.dumps(data, ensure_ascii=False)
                if encoded != previous:
                    yield "event: snapshot\ndata: " + encoded + "\n\n"
                    previous = encoded
                else:
                    yield ": heartbeat\n\n"
                if data["status"] not in svc.ACTIVE:
                    return
            except HTTPException:
                yield 'event: access_denied\ndata: {"error":"session_expired"}\n\n'
                return
            await asyncio.sleep(0.5)
    return StreamingResponse(output(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/user/api/chat-generations/{gid}/cancel")
async def cancel(gid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    async with SessionLocal() as s:
        g = await svc.authorized_generation(s, gid, user)
        g.cancel_requested = True
        await s.commit()
    return {"status": "stopping"}


@router.delete("/user/api/conversations/{cid}")
async def remove(cid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    async with SessionLocal() as s:
        c = await svc.conversation(s, cid, user)
        c.deleted_at, c.context = svc.now(), {}
        for g in (await s.scalars(select(ChatGeneration).where(ChatGeneration.conversation_id == cid).with_for_update())).all():
            g.cancel_requested, g.question, g.answer, g.citations = True, "", "", []
        await s.commit()
    return {"status": "deleted"}


@router.post("/user/api/chat-messages/{gid}/feedback")
async def feedback(gid: uuid.UUID, payload: Feedback, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    async with SessionLocal() as s:
        g = await svc.authorized_generation(s, gid, user)
        if g.status not in {"completed", "failed", "stopped", "unknown"}:
            raise HTTPException(409, "chat_busy")
        g.feedback = payload.value
        await s.commit()
    return {"status": "saved"}


async def owner(token):
    actor = await admin.current_admin(token)
    if not admin.is_owner(actor):
        raise HTTPException(403, "owner_required")
    return actor


@router.get("/admin/api/news-chat/policy")
async def get_policy(token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as s:
        p = await svc.policy(s)
        return {"policy": p.model_dump(mode="json"), "scope": "user_portal", "server_enabled": get_settings().news_chat_enabled,
                "configured": {provider: providers.configured(get_settings(), provider) for provider in ("openai", "anthropic", "google")}}


@router.put("/admin/api/news-chat/policy")
async def put_policy(payload: Policy, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    # Retire legacy project overrides on save. Membership remains separate.
    payload = payload.model_copy(update={"projects": {}})
    async with SessionLocal() as s:
        for m in payload.models:
            if m.enabled and (not m.verified or not providers.configured(get_settings(), m.provider)):
                raise HTTPException(422, "provider_unconfigured")
        row = await s.get(ChatPolicy, 1, with_for_update=True)
        if row is None:
            row = ChatPolicy(id=1, config={})
            s.add(row)
        row.config = payload.model_dump(mode="json")
        await s.commit()
    await admin._audit(actor.id, "news_chat.policy", details={"enabled": payload.enabled, "model_count": len(payload.models)})
    return {"status": "saved"}


@router.put("/admin/api/news-chat/users/{uid}/grant")
async def grant(uid: uuid.UUID, payload: Grant, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as s:
        user = await s.get(AdminUser, uid, with_for_update=True)
        if user is None:
            raise HTTPException(404)
        if payload.enabled and not admin.user_portal_access_allowed(user):
            raise HTTPException(422, "user_portal_required")
        user.preferences = {**(user.preferences or {}), "news_chat_enabled": payload.enabled}
        await s.execute(delete(AdminSession).where(AdminSession.user_id == uid, AdminSession.portal == "user"))
        await s.commit()
    await admin._audit(actor.id, "news_chat.grant", details={"user_id": str(uid), "enabled": payload.enabled})
    return {"status": "saved"}


@router.get("/admin/api/news-chat/usage")
async def usage(token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as s:
        rows = (await s.scalars(select(ChatGeneration).order_by(ChatGeneration.created_at.desc()).limit(100))).all()
        return {"requests": [{"id": str(g.id), "status": g.status, "provider": g.model["provider"], "model_id": g.model["model_id"],
                           "reserved_usd": str(g.reserved_usd), "actual_usd": str(g.actual_usd) if g.actual_usd is not None else None,
                           "error_code": g.error_code, "created_at": g.created_at.isoformat()} for g in rows]}
