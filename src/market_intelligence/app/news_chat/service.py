from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from contextlib import aclosing
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text, update

from app import admin
from app.config import get_settings
from app.database import SessionLocal
from app.deployment_drain import work_lease
from app.models import AdminSession, AdminUser, Publication
from app.news_chat import providers
from app.news_chat.context import context_for, prompt, validate_citations
from app.news_chat.models import ChatConversation, ChatGeneration, ChatPolicy
from app.news_chat.schemas import ModelSpec, Policy, Question

ACTIVE = ("queued", "running")
LOCK = 71394001


def now():
    return datetime.now(timezone.utc)


def allowed(user: AdminUser) -> bool:
    return bool(user is not None and user.active and admin.user_portal_access_allowed(user) and
                (admin.is_owner(user) or (user.preferences or {}).get("news_chat_enabled") is True))


def require(user):
    if not allowed(user):
        raise HTTPException(403, "chat_access_denied")


async def policy(s) -> Policy:
    row = await s.get(ChatPolicy, 1)
    return Policy.model_validate(row.config if row else {})


async def publication(s, pid, user):
    available = await admin.reader_assistants(user)
    ids = {uuid.UUID(a["id"]) for a in available["assistants"]}
    row = await s.scalar(select(Publication).where(Publication.id == pid, Publication.assistant_id.in_(ids), Publication.status == "published"))
    if row is None:
        raise HTTPException(404, "news_unavailable")
    return row


def model_for(p: Policy, aid: uuid.UUID, key: str) -> ModelSpec:
    settings = get_settings()
    # User-portal feature. Project ACL remains in publication()/models API;
    # a policy allowlist must never exclude newly created workspaces.
    if not settings.news_chat_enabled or not p.enabled:
        raise HTTPException(403, "chat_disabled")
    for model in p.models:
        if model.key == key and model.enabled and model.verified:
            if not providers.configured(settings, model.provider):
                raise HTTPException(503, "provider_unconfigured")
            return model
    raise HTTPException(403, "model_unavailable")


async def conversation(s, cid, user):
    require(user)
    row = await s.scalar(select(ChatConversation).where(ChatConversation.id == cid, ChatConversation.user_id == user.id, ChatConversation.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(404, "news_unavailable")
    await publication(s, row.publication_id, user)
    return row


def view(g):
    return {"id": str(g.id), "conversation_id": str(g.conversation_id), "question": g.question,
            "answer": g.answer, "status": g.status, "error_code": g.error_code,
            "provider": g.model["provider"], "model": g.model["label"], "model_key": g.model["provider"] + ":" + g.model["model_id"],
            "citations": g.citations, "feedback": g.feedback, "created_at": g.created_at.isoformat()}


async def send(cid: uuid.UUID, q: Question, user: AdminUser, token: str) -> dict:
    require(user)
    if not q.question.strip():
        raise HTTPException(422, "question_required")
    async with SessionLocal() as s:
        c = await conversation(s, cid, user)
        pub = await publication(s, c.publication_id, user)
        if c.context["version"] != q.context_version or context_for(pub.message_text, None)["version"] != q.context_version:
            raise HTTPException(409, "context_changed")
        p = await policy(s)
        m = model_for(p, c.assistant_id, q.model_key)
        if c.provider != m.provider:
            raise HTTPException(409, "new_provider_requires_new_conversation")
        if q.selected_segment and q.selected_segment not in {seg["id"] for seg in c.context["segments"]}:
            raise HTTPException(422, "invalid_selection")
        # Across all processes: reservation, idempotency and capacity are atomic.
        await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
        prior = await s.scalar(select(ChatGeneration).where(ChatGeneration.user_id == user.id, ChatGeneration.idempotency_key == q.idempotency_key))
        if prior:
            if (prior.conversation_id != cid or prior.question != q.question or prior.model["model_id"] != m.model_id
                or prior.language != q.language or prior.usage.get("selected_segment") != q.selected_segment):
                raise HTTPException(409, "idempotency_conflict")
            return view(prior)
        active = await s.scalar(select(func.count()).select_from(ChatGeneration).where(ChatGeneration.status.in_(ACTIVE))) or 0
        own_active = await s.scalar(select(func.count()).select_from(ChatGeneration).where(ChatGeneration.status.in_(ACTIVE), ChatGeneration.user_id == user.id))
        if active >= 4 or own_active:
            raise HTTPException(429, "chat_busy")
        history = list((await s.scalars(select(ChatGeneration).where(ChatGeneration.conversation_id == cid, ChatGeneration.status == "completed").order_by(ChatGeneration.created_at.desc(), ChatGeneration.id.desc()).limit(20))).all())
        try:
            messages = prompt(c.context, q.question, q.language, [view(g) for g in reversed(history)], q.selected_segment, m.max_input_chars)
        except ValueError:
            raise HTTPException(422, "context_too_large") from None
        # Conservative upper bound: <= one Unicode scalar per token is not
        # guaranteed; use UTF-8 bytes for input reservation rather than chars/4.
        input_bound = sum(len(x["content"].encode()) + 100 for x in messages)
        reserve = ((Decimal(input_bound) * m.input_usd + Decimal(m.max_output_tokens) * m.output_usd) / Decimal(1_000_000)).quantize(Decimal("0.00000001"), rounding=ROUND_CEILING)
        day = now().astimezone(ZoneInfo(get_settings().timezone)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        charge = func.coalesce(ChatGeneration.actual_usd, ChatGeneration.reserved_usd)
        own = ChatGeneration.user_id == user.id
        # Aggregate in SQL: accepting a question must not load every user's
        # private transcript or scan it in Python just to calculate a budget.
        total, user_total, count, recent = (await s.execute(select(
            func.coalesce(func.sum(charge), 0),
            func.coalesce(func.sum(charge).filter(own), 0),
            func.count().filter(own),
            func.count().filter(own, ChatGeneration.created_at >= now() - timedelta(minutes=1)),
        ).where(ChatGeneration.created_at >= day))).one()
        if count >= p.user_daily_requests or recent >= 5:
            raise HTTPException(429, "quota_exceeded")
        if total + reserve > p.daily_budget_usd or user_total + reserve > p.user_daily_budget_usd:
            raise HTTPException(429, "budget_exhausted")
        session = await s.scalar(select(AdminSession).where(AdminSession.token_hash == hashlib.sha256(token.encode()).hexdigest(), AdminSession.user_id == user.id, AdminSession.portal == "user"))
        if session is None:
            raise HTTPException(401, "session_expired")
        deadline = min(session.expires_at, admin._reader_nightly_expiry(session.created_at), session.created_at + timedelta(hours=get_settings().session_absolute_hours), now() + timedelta(seconds=get_settings().news_chat_timeout_seconds))
        g = ChatGeneration(id=uuid.uuid4(), conversation_id=cid, user_id=user.id, assistant_id=c.assistant_id, idempotency_key=q.idempotency_key,
                           session_hash=session.token_hash, question=q.question, answer="", language=q.language, model=m.model_dump(mode="json"),
                           citations=[], status="queued", cancel_requested=False, reserved_usd=reserve, usage={"input_bound": input_bound, "selected_segment": q.selected_segment}, deadline=deadline, created_at=now())
        s.add(g)
        await s.commit()
        return view(g)


async def authorized_generation(s, gid, user):
    g = await s.scalar(select(ChatGeneration).where(ChatGeneration.id == gid, ChatGeneration.user_id == user.id))
    if g is None or not g.conversation_id:
        raise HTTPException(404, "news_unavailable")
    await conversation(s, g.conversation_id, user)
    p = await policy(s)
    model_for(p, g.assistant_id, g.model["provider"] + ":" + g.model["model_id"])
    return g


async def live(gid):
    async with SessionLocal() as s:
        g = await s.get(ChatGeneration, gid)
        if g and g.cancel_requested:
            raise HTTPException(403, "chat_cancelled")
        if not g or g.deadline <= now():
            raise HTTPException(401, "session_expired")
        sess = await s.scalar(select(AdminSession).where(AdminSession.token_hash == g.session_hash, AdminSession.portal == "user", AdminSession.expires_at > now()))
        if not sess:
            raise HTTPException(401, "session_expired")
        user = await s.get(AdminUser, sess.user_id)
        await authorized_generation(s, gid, user)


async def monitored_events(gid, stream):
    """Cancellation/session checks continue even while upstream sends no token."""
    pending = None
    last_check = time.monotonic()
    async with aclosing(stream) as iterator:
        try:
            while True:
                pending = asyncio.create_task(iterator.__anext__())
                while True:
                    done, _ = await asyncio.wait({pending}, timeout=0.5)
                    if time.monotonic() - last_check >= 0.5:
                        await live(gid)
                        last_check = time.monotonic()
                    if done:
                        break
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    return
                yield event
        finally:
            if pending:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def generate(gid):
    answer, usage, status, error = "", {}, "unknown", None
    try:
        await live(gid)
        async with SessionLocal() as s:
            g = await s.get(ChatGeneration, gid)
            c = await s.get(ChatConversation, g.conversation_id)
            context = c.context
            model = ModelSpec.model_validate(g.model)
            history = list((await s.scalars(select(ChatGeneration).where(ChatGeneration.conversation_id == c.id, ChatGeneration.status == "completed").order_by(ChatGeneration.created_at.desc(), ChatGeneration.id.desc()).limit(20))).all())
            messages = prompt(context, g.question, g.language, [view(x) for x in reversed(history)], g.usage.get("selected_segment"), model.max_input_chars)
            deadline = g.deadline
        last_write = time.monotonic()
        async with asyncio.timeout(max(0.1, (deadline - now()).total_seconds())), aclosing(monitored_events(gid, providers.stream(get_settings(), model, messages))) as events:
            async for event in events:
                if event.get("text"):
                    answer += event["text"]
                    if len(answer) > 40000:
                        raise providers.ProviderError("provider_incomplete")
                if event.get("usage"):
                    usage = event["usage"]
                if time.monotonic() - last_write > 0.25:
                    async with SessionLocal() as s:
                        row = await s.get(ChatGeneration, gid, with_for_update=True)
                        if row.cancel_requested:
                            raise HTTPException(403, "chat_cancelled")
                        row.answer = answer
                        await s.commit()
                    last_write = time.monotonic()
        await live(gid)
        status = "completed" if answer.strip() else "failed"
        error = None if answer.strip() else "provider_empty"
    except HTTPException as exc:
        status, error = "stopped", "chat_stopped" if exc.status_code != 401 else "session_expired"
    except providers.ProviderError as exc:
        status, error = ("unknown" if exc.code == "generation_unknown" else "failed"), exc.code
    except (TimeoutError, asyncio.CancelledError):
        status, error = "unknown", "generation_unknown"
    except Exception:
        # Never log prompt, upstream exception text, answer or credentials.
        status, error = "unknown", "provider_failed"
    async with SessionLocal() as s:
        row = await s.get(ChatGeneration, gid, with_for_update=True)
        if not row:
            return
        c = await s.get(ChatConversation, row.conversation_id) if row.conversation_id else None
        citations = []
        if c and c.deleted_at is None:
            answer, citations, invalid = validate_citations(answer, c.context)
            if invalid or (status == "completed" and not citations):
                error = "citation_unverified"
            row.answer = answer
        else:
            row.answer, row.question = "", ""
        row.citations, row.status, row.error_code = citations, status, error
        row.actual_usd = providers.cost(ModelSpec.model_validate(row.model), usage)
        row.usage = {**row.usage, **usage}
        row.finished_at, row.session_hash = now(), ""
        await s.commit()


async def worker(stop: asyncio.Event):
    while not stop.is_set():
        try:
            async with work_lease():
                async with SessionLocal() as s:
                    g = await s.scalar(select(ChatGeneration).where(ChatGeneration.status == "queued").order_by(ChatGeneration.created_at).with_for_update(skip_locked=True).limit(1))
                    gid = g.id if g else None
                    if g:
                        g.status = "running"
                        await s.commit()
                if gid:
                    await generate(gid)
            if not gid:
                try:
                    await asyncio.wait_for(stop.wait(), 0.5)
                except TimeoutError:
                    pass
        except Exception:
            # Fail closed and back off when the isolated chat store is unavailable.
            try:
                await asyncio.wait_for(stop.wait(), 2)
            except TimeoutError:
                pass


async def maintenance_once():
    async with work_lease(), SessionLocal() as s:
        await s.execute(update(ChatGeneration).where(ChatGeneration.status.in_(ACTIVE), ChatGeneration.deadline < now() - timedelta(seconds=10)).values(status="unknown", error_code="generation_unknown", finished_at=now(), session_hash=""))
        cutoff = now() - timedelta(days=get_settings().news_chat_retention_days)
        # Covers orphaned billing rows too. Skip already-cleared rows rather
        # than repeatedly rewriting the lifetime financial ledger every tick.
        await s.execute(update(ChatGeneration).where(ChatGeneration.created_at < cutoff, or_(ChatGeneration.question != "", ChatGeneration.answer != "", ChatGeneration.session_hash != "")).values(question="", answer="", citations=[], session_hash="", cancel_requested=True))
        # The frozen database trigger clears text even for cascade deletion;
        # the nullable FK preserves the corresponding consumption records.
        await s.execute(delete(ChatConversation).where(ChatConversation.created_at < cutoff))
        await s.commit()


async def maintenance(stop):
    while not stop.is_set():
        try:
            await maintenance_once()
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), 30)
        except TimeoutError:
            pass
