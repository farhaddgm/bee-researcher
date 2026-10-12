from __future__ import annotations

import asyncio
import json
import uuid
import hashlib
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, cast

from fastapi import APIRouter, Cookie, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
from sqlalchemy import Text, delete, func, literal, or_, select, text, tuple_

from app import admin
from app.config import get_settings
from app.database import SessionLocal
from app.models import Publication
from app.models import AdminSession, AdminUser
from app.security_controls import ADMIN_SESSION_COOKIE
from app.news_chat import providers, service as svc
from app.news_chat.context import context_for
from app.news_chat.models import ChatConversation, ChatGeneration, ChatPolicy
from app.news_chat.schemas import Feedback, Grant, Policy, ResearchStart

router = APIRouter()
COOKIE = admin.USER_SESSION_COOKIE
ROOT = Path(__file__).parent


@router.get("/assets/news-chat/{asset}", include_in_schema=False)
async def asset(asset: str):
    types = {"chat.js": "application/javascript", "chat.css": "text/css", "i18n.js": "application/javascript", "admin.js": "application/javascript", "voice.js": "application/javascript", "memory.js": "application/javascript"}
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
        return {"conversations": [{"id": str(c.id), "provider": c.provider, "created_at": c.created_at.isoformat(), "context_version": c.context["version"], "saved_at": c.saved_at.isoformat() if c.saved_at else None} for c in rows]}


@router.post("/user/api/publications/{pid}/conversations", status_code=201)
async def start(pid: uuid.UUID, payload: ResearchStart, token: str | None = Cookie(None, alias=COOKIE)):
    # Preserve existing internal callers of the original Start schema.
    payload = ResearchStart.model_validate(payload.model_dump())
    user = await admin.current_reader(token)
    svc.require(user)
    async with SessionLocal() as s:
        await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": svc.LOCK})
        if payload.conversation_id:
            existing = await s.get(ChatConversation, payload.conversation_id)
            if existing:
                if existing.user_id != user.id or existing.publication_id != pid:
                    raise HTTPException(404, "news_unavailable")
                if existing.deleted_at or svc.window_expired(existing.context):
                    raise HTTPException(410, "conversation_closed")
                if payload.source_ids or payload.memory_ids or payload.include_business:
                    from app.reader_research.service import selected_context
                    pub = await svc.publication(s, pid, user)
                    requested = await selected_context(s, pub, user, payload.source_ids, payload.memory_ids, payload.include_business)
                    if requested['version'] != existing.context['version']:
                        raise HTTPException(409, 'idempotency_conflict')
                return {"id": str(existing.id), "provider": existing.provider, "context": svc.public_context(existing.context)}
        pub = await svc.publication(s, pid, user)
        m = svc.model_for(await svc.policy(s), pub.assistant_id, payload.model_key)
        # Count and insert share the cross-process admission lock. Two tabs
        # cannot both claim the last available conversation slot.
        count = await s.scalar(select(func.count()).select_from(ChatConversation).where(ChatConversation.user_id == user.id, ChatConversation.deleted_at.is_(None))) or 0
        if count >= 500:
            raise HTTPException(429, "quota_exceeded")
        ctx = context_for(pub.message_text, pub.published_at.isoformat() if pub.published_at else None)
        if payload.source_ids or payload.memory_ids or payload.include_business:
            from app.reader_research.service import selected_context
            ctx = await selected_context(s, pub, user, payload.source_ids, payload.memory_ids, payload.include_business)
        ctx.update(_ephemeral=True, _session_hash=hashlib.sha256((token or "").encode()).hexdigest(),
                   _expires_at=(svc.now() + timedelta(seconds=svc.WINDOW_LEASE_SECONDS)).isoformat())
        c = ChatConversation(id=payload.conversation_id or uuid.uuid4(), user_id=user.id, assistant_id=pub.assistant_id, publication_id=pid,
                             context=ctx, provider=m.provider, created_at=svc.now())
        s.add(c)
        await s.commit()
        return {"id": str(c.id), "provider": c.provider, "context": svc.public_context(c.context)}


@router.post("/user/api/publications/{pid}/conversations/{cid}/close")
async def close_window(pid: uuid.UUID, cid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token, touch=False)
    async with SessionLocal() as s:
        await svc.close_window(s, cid, pid, user)
    return {"status": "deleted"}


@router.post("/user/api/conversations/{cid}/heartbeat")
async def heartbeat(cid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token, touch=False)
    async with SessionLocal() as s:
        await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": svc.LOCK})
        c = await svc.conversation(s, cid, user)
        if c.saved_at:
            return {"status": "saved"}
        if not c.context.get("_ephemeral") or c.context.get("_session_hash") != hashlib.sha256((token or "").encode()).hexdigest():
            raise HTTPException(403, "chat_access_denied")
        c.context = {**c.context, "_expires_at": (svc.now() + timedelta(seconds=svc.WINDOW_LEASE_SECONDS)).isoformat()}
        await s.commit()
    return {"status": "active"}


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
        return {"messages": [svc.view(g) for g in reversed(page)], "context": svc.public_context(c.context), "saved_at": c.saved_at.isoformat() if c.saved_at else None, "older_before": str(page[-1].id) if len(rows) > 30 else None}


@router.put("/user/api/conversations/{cid}/memory")
async def save_memory(cid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    async with SessionLocal() as s:
        await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": svc.LOCK})
        c = await svc.conversation(s, cid, user)
        # Synchronize saving with retention and explicit deletion. Saving is
        # idempotent and refers to the whole persisted thread, not the UI page.
        c = await s.scalar(select(ChatConversation).where(ChatConversation.id == c.id, ChatConversation.deleted_at.is_(None)).with_for_update())
        if c is None:
            raise HTTPException(404, "news_unavailable")
        completed = await s.scalar(select(ChatGeneration.id).where(ChatGeneration.conversation_id == cid, ChatGeneration.status == "completed", ChatGeneration.answer != "").limit(1))
        if completed is None:
            raise HTTPException(409, "completed_answer_required")
        c.saved_at = c.saved_at or svc.now()
        c.context = {k: v for k, v in c.context.items() if not k.startswith("_") or k=="_voice_continuous_started_at"}
        await s.commit()
        return {"id": str(c.id), "assistant_id": str(c.assistant_id), "saved_at": c.saved_at.isoformat()}


@router.delete("/user/api/conversations/{cid}/memory")
async def unsave_memory(cid: uuid.UUID, remove_audio: bool = False, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    async with SessionLocal() as s:
        await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": svc.LOCK})
        c = await svc.conversation(s, cid, user)
        from app.news_voice.models import VoiceAudio
        audio=await s.scalar(select(VoiceAudio.id).where(VoiceAudio.conversation_id==cid,VoiceAudio.deleted_at.is_(None),VoiceAudio.saved_at.is_not(None)).limit(1))
        if audio and not remove_audio:raise HTTPException(409,'audio_removal_confirmation_required')
        if remove_audio:
            from app.news_voice.service import erase_conversation as erase_voice
            await erase_voice(s,cid)
        c.saved_at = None
        await s.commit()
    return {"status": "removed"}


@router.get('/user/api/conversations/{cid}/memory-reference')
async def memory_reference(cid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    async with SessionLocal() as s:
        c = await svc.conversation(s, cid, user)
        if not c.saved_at:
            raise HTTPException(404, 'news_unavailable')
        return {'id': str(c.id), 'assistant_id': str(c.assistant_id), 'publication_id': str(c.publication_id),
                'title': next((seg['text'][:180] for seg in c.context.get('segments', [])), ''),
                'provider': c.provider, 'saved_at': c.saved_at.isoformat()}


@router.get("/user/api/assistants/{aid}/memory")
async def project_memory(aid: uuid.UUID, before: uuid.UUID | None = None, q: Annotated[str, Query(max_length=120)] = '',
                         model: Annotated[str, Query(max_length=120)] = '', after_date: date | None = None, until_date: date | None = None,
                         token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    svc.require(user)
    available = await admin.reader_assistants(user)
    if str(aid) not in {str(a["id"]) for a in cast(list[dict[str, Any]], available["assistants"])}:
        raise HTTPException(404, "news_unavailable")
    async with SessionLocal() as s:
        query = select(ChatConversation).join(Publication, Publication.id == ChatConversation.publication_id).where(
            ChatConversation.user_id == user.id, ChatConversation.assistant_id == aid,
            ChatConversation.saved_at.is_not(None), ChatConversation.deleted_at.is_(None), Publication.status == "published")
        if after_date and until_date and after_date > until_date:
            raise HTTPException(422, 'invalid_date_range')
        if after_date:
            query = query.where(ChatConversation.saved_at >= datetime.combine(after_date, time.min, timezone.utc))
        if until_date:
            query = query.where(ChatConversation.saved_at <= datetime.combine(until_date, time.max, timezone.utc))
        matching = select(ChatGeneration.id).where(ChatGeneration.conversation_id == ChatConversation.id)
        if q.strip():
            pattern = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            matching = matching.where(or_(ChatGeneration.question.ilike(pattern, escape='\\'), ChatGeneration.answer.ilike(pattern, escape='\\')))
        if model:
            matching = matching.where(func.concat(ChatGeneration.model['provider'].as_string(), ':', ChatGeneration.model['model_id'].as_string()) == model)
        if q.strip() and not model:
            query = query.where(or_(matching.exists(), ChatConversation.context['segments'].cast(Text).ilike(pattern, escape='\\')))
        elif q.strip() and model:
            model_match = select(ChatGeneration.id).where(ChatGeneration.conversation_id == ChatConversation.id,
                func.concat(ChatGeneration.model['provider'].as_string(), ':', ChatGeneration.model['model_id'].as_string()) == model)
            query = query.where(or_(matching.exists(), ChatConversation.context['segments'].cast(Text).ilike(pattern, escape='\\') & model_match.exists()))
        elif model:
            query = query.where(matching.exists())
        if before:
            prior = await s.scalar(query.where(ChatConversation.id == before))
            if prior is None:
                raise HTTPException(404, "news_unavailable")
            query = query.where(tuple_(ChatConversation.saved_at, ChatConversation.id) < tuple_(literal(prior.saved_at), literal(prior.id)))
        rows = (await s.scalars(query.order_by(ChatConversation.saved_at.desc(), ChatConversation.id.desc()).limit(31))).all()
        page = rows[:30]
        return {"memories": [{"id": str(c.id), "publication_id": str(c.publication_id), "provider": c.provider,
                              "title": next((s["text"][:180] for s in c.context.get("segments", [])), ""),
                              "saved_at": c.saved_at.isoformat() if c.saved_at else None} for c in page],
                "older_before": str(page[-1].id) if len(rows) > 30 else None}


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
        c = await s.get(ChatConversation, cid)
        if c is None or c.user_id != user.id:
            raise HTTPException(404, "news_unavailable")
        await svc.close_window(s, cid, c.publication_id, user, preserve_saved=False)
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
