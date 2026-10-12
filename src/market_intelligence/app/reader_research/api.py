from __future__ import annotations

import uuid
from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, literal, or_, select, text, tuple_
from app import admin
from app.config import get_settings
from app.database import SessionLocal
from app.models import ArticleAnalysis, NormalizedArticle, Publication, Source, SourceItem
from app.news_chat import service as chat
from app.news_chat.context import reader_report_text
from app.news_chat.schemas import Feedback
from app.pipeline_service import _article_decisions
from app.news_chat.models import ChatConversation, ChatGeneration
from app.reader_research import service
from app.reader_research.models import ResearchProfile, ResearchRecord
from app.reader_research.schemas import Kind, Profile, Record

router = APIRouter()
COOKIE = admin.USER_SESSION_COOKIE
ROOT = Path(__file__).parent


@router.get('/assets/reader-research/{asset}', include_in_schema=False)
async def asset(asset: str):
    types = {'research.js': 'application/javascript', 'research.css': 'text/css', 'i18n.js': 'application/javascript'}
    if asset not in types:
        raise HTTPException(404)
    return FileResponse(ROOT / asset, media_type=types[asset], headers={'Cache-Control': 'no-cache'})


async def reader(token, aid, *, touch=True):
    user = await admin.current_reader(token, touch=touch)
    await service.project(user, aid)
    return user


def profile_view(row):
    return {**Profile.model_validate(row.settings if row else {}).model_dump(mode='json'), 'version': row.version if row else 0}


@router.get('/user/api/assistants/{aid}/research/profile')
async def profile(aid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        return profile_view(await s.get(ResearchProfile, (user.id, aid)))


@router.put('/user/api/assistants/{aid}/research/profile')
async def save_profile(aid: uuid.UUID, payload: Profile, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        await s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': service.LOCK})
        row = await s.get(ResearchProfile, (user.id, aid), with_for_update=True)
        if payload.version != (row.version if row else 0):
            raise HTTPException(409, 'revision_conflict')
        if row is None:
            row = ResearchProfile(user_id=user.id, assistant_id=aid, version=0)
            s.add(row)
        row.settings = payload.model_dump(mode='json', exclude={'version'})
        row.version += 1
        row.updated_at = chat.now()
        await s.commit()
        return profile_view(row)


@router.get('/user/api/assistants/{aid}/research/feed')
async def feed(aid: uuid.UUID, before: uuid.UUID | None = None, days: int = Query(90, ge=1, le=365),
               limit: int = Query(200, ge=1, le=200), touch: bool = True, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid, touch=touch)
    async with SessionLocal() as s:
        published = func.coalesce(Publication.published_at, Publication.created_at)
        query = select(Publication, Source.name, NormalizedArticle).join(ArticleAnalysis,
            (ArticleAnalysis.id == Publication.analysis_id) & (ArticleAnalysis.assistant_id == aid)).join(NormalizedArticle,
            (NormalizedArticle.id == ArticleAnalysis.article_id) & (NormalizedArticle.assistant_id == aid)).join(SourceItem,
            (SourceItem.id == NormalizedArticle.source_item_id) & (SourceItem.assistant_id == aid)).join(Source,
            (Source.id == SourceItem.source_id) & (Source.assistant_id == aid)).where(
            Publication.assistant_id == aid, Publication.status == 'published', published >= chat.now() - timedelta(days=days))
        if before:
            prior = await s.scalar(select(Publication).where(Publication.id == before, Publication.assistant_id == aid, Publication.status == 'published'))
            if prior is None:
                raise HTTPException(404, 'news_unavailable')
            query = query.where(tuple_(published, Publication.id) < tuple_(literal(prior.published_at or prior.created_at), literal(prior.id)))
        rows = (await s.execute(query.order_by(published.desc(), Publication.id.desc()).limit(limit + 1))).all()
        decisions = await _article_decisions(s, [r[2] for r in rows[:limit]], get_settings())
        data = []
        for pub, source, article in rows[:limit]:
            clean = reader_report_text(pub.message_text)
            data.append({'id': str(pub.id), 'title': clean.splitlines()[0][:180] if clean else '', 'text': clean,
                         'source': source, 'published_at': (pub.published_at or pub.created_at).isoformat(),
                         'article_published_at': article.published_at.isoformat() if article.published_at else None,
                         'relevance': decisions[article.id].get('relevance_score')})
        p = Profile.model_validate(profile_view(await s.get(ResearchProfile, (user.id, aid))))
        return {'news': service.feed_signals(data, p, chat.now()), 'trends': service.trends(data),
                'older_before': str(rows[limit-1][0].id) if len(rows) > limit else None,
                'scope': 'published_project_reports', 'lookback_days': days, 'window_count': len(data)}


def record_view(row, user):
    return {'id': str(row.id), 'kind': row.kind, 'title': row.title, 'body': row.body,
            'attributes': row.attributes, 'publication_ids': row.publication_ids,
            # Sharing a result never exposes its private conversation identifier.
            'conversation_id': str(row.conversation_id) if row.conversation_id and row.user_id == user.id else None,
            'version': row.version, 'owned': row.user_id == user.id,
            'created_at': row.created_at.isoformat(), 'updated_at': row.updated_at.isoformat()}


async def sources_visible(s, aid, ids):
    if not ids:
        return True
    count = await s.scalar(select(func.count()).select_from(Publication).where(Publication.id.in_([uuid.UUID(v) for v in ids]),
        Publication.assistant_id == aid, Publication.status == 'published'))
    return count == len(ids)


@router.get('/user/api/assistants/{aid}/research/records')
async def records(aid: uuid.UUID, kind: Kind, before: uuid.UUID | None = None, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        query = select(ResearchRecord).where(ResearchRecord.assistant_id == aid, ResearchRecord.kind == kind)
        if kind != 'shared':
            query = query.where(ResearchRecord.user_id == user.id)
        if before:
            prior = await s.scalar(query.where(ResearchRecord.id == before))
            if prior is None:
                raise HTTPException(404, 'news_unavailable')
            query = query.where(tuple_(ResearchRecord.created_at, ResearchRecord.id) < tuple_(literal(prior.created_at), literal(prior.id)))
        # Filter source withdrawal before exposing records. A scanned cursor
        # ensures revoked rows cannot trap navigation on the same page.
        rows = list((await s.scalars(query.order_by(ResearchRecord.created_at.desc(), ResearchRecord.id.desc()).limit(51))).all())
        page = rows[:50]
        from app.reader_tools.corrections import stale_sources
        visible = []
        for r in page:
            if await sources_visible(s, aid, r.publication_ids):
                view = record_view(r, user)
                view['changed_sources'] = await stale_sources(s, aid, r.publication_ids, r.source_versions, r.created_at)
                visible.append(view)
        return {'records': visible, 'older_before': str(page[-1].id) if len(rows) > 50 else None}


@router.post('/user/api/assistants/{aid}/research/records', status_code=201)
async def create_record(aid: uuid.UUID, payload: Record, token: str | None = Cookie(None, alias=COOKIE)):
    return await write_record(aid, payload, token, None)


@router.put('/user/api/assistants/{aid}/research/records/{rid}')
async def update_record(aid: uuid.UUID, rid: uuid.UUID, payload: Record, token: str | None = Cookie(None, alias=COOKIE)):
    return await write_record(aid, payload, token, rid)


async def write_record(aid, payload, token, rid):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        await s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': service.LOCK})
        ids = [str(v) for v in payload.publication_ids]
        if not await sources_visible(s, aid, ids):
            raise HTTPException(404, 'news_unavailable')
        if payload.conversation_id:
            c = await chat.conversation(s, payload.conversation_id, user)
            if c.assistant_id != aid or not c.saved_at:
                raise HTTPException(404, 'news_unavailable')
        evidence = None
        generated_context = None
        if payload.generation_id:
            g = await s.scalar(select(ChatGeneration).where(ChatGeneration.id == payload.generation_id,
                ChatGeneration.user_id == user.id, ChatGeneration.assistant_id == aid, ChatGeneration.status == 'completed'))
            if g is None or not g.conversation_id:
                raise HTTPException(404, 'news_unavailable')
            generated = await s.get(ChatConversation, g.conversation_id)
            if generated is None:
                raise HTTPException(404, 'news_unavailable')
            generated_ids = generated.context.get('source_ids') or [str(generated.publication_id)]
            if generated.deleted_at or set(generated_ids) != set(ids):
                raise HTTPException(404, 'news_unavailable')
            from app.reader_tools.corrections import context_evidence_versions
            evidence = await context_evidence_versions(s, generated.context, ids)
            generated_context = generated.context
        row = await s.get(ResearchRecord, rid or payload.id or uuid.uuid4(), with_for_update=True)
        if row:
            if row.user_id != user.id or row.assistant_id != aid:
                raise HTTPException(404, 'news_unavailable')
            if rid is None:
                equal = (row.kind == payload.kind and row.title == payload.title and row.body == payload.body
                         and row.attributes == payload.attributes.model_dump(mode='json') and row.publication_ids == ids
                         and row.conversation_id == payload.conversation_id and row.source_generation_id == payload.generation_id)
                if not equal:
                    raise HTTPException(409, 'idempotency_conflict')
                return record_view(row, user)
            if row.version != payload.version or row.kind != payload.kind:
                raise HTTPException(409, 'revision_conflict')
        else:
            if rid is not None or payload.version != 0:
                raise HTTPException(404, 'news_unavailable')
            count = await s.scalar(select(func.count()).select_from(ResearchRecord).where(ResearchRecord.user_id == user.id, ResearchRecord.assistant_id == aid))
            if count >= 400:
                raise HTTPException(429, 'quota_exceeded')
            row = ResearchRecord(id=payload.id or uuid.uuid4(), user_id=user.id, assistant_id=aid, kind=payload.kind, version=0)
        from app.reader_tools.corrections import dependency_versions
        await dependency_versions(s, user, aid, ids)
        if generated_context:
            from app.reader_tools.corrections import retain_report_history
            await retain_report_history(s, generated_context, ids)
        prior_ids = row.publication_ids or []
        prior_versions = row.source_versions or {}
        row.source_versions = evidence if evidence is not None else {pid: prior_versions.get(pid, 0) if pid in prior_ids else 0 for pid in ids}
        if payload.generation_id:
            row.source_generation_id = payload.generation_id
        row.title, row.body = payload.title, payload.body
        row.attributes, row.publication_ids, row.conversation_id = payload.attributes.model_dump(mode='json'), ids, payload.conversation_id
        row.version += 1
        row.updated_at = chat.now()
        s.add(row)
        await s.commit()
        return record_view(row, user)


@router.delete('/user/api/assistants/{aid}/research/records/{rid}')
async def delete_record(aid: uuid.UUID, rid: uuid.UUID, version: int = Query(ge=1), token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        row = await s.get(ResearchRecord, rid, with_for_update=True)
        if row is None or row.user_id != user.id or row.assistant_id != aid:
            raise HTTPException(404, 'news_unavailable')
        if row.version != version:
            raise HTTPException(409, 'revision_conflict')
        await s.delete(row)
        await s.commit()
    return {'status': 'deleted'}


@router.get('/user/api/assistants/{aid}/research/usage')
async def usage(aid: uuid.UUID, before: uuid.UUID | None = None, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    chat.require(user)
    day = chat.now().astimezone(ZoneInfo(get_settings().timezone)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    async with SessionLocal() as s:
        p = await chat.policy(s)
        charge = func.coalesce(ChatGeneration.actual_usd, ChatGeneration.reserved_usd)
        own = ChatGeneration.user_id == user.id
        total, personal, count = (await s.execute(select(func.coalesce(func.sum(charge), 0),
            func.coalesce(func.sum(charge).filter(own), 0), func.count().filter(own)).where(ChatGeneration.created_at >= day))).one()
        from app.news_chat.budget import totals
        total,personal=await totals(s,user.id)
        q = select(ChatGeneration).where(own, ChatGeneration.assistant_id == aid)
        if before:
            prior = await s.scalar(q.where(ChatGeneration.id == before))
            if not prior:
                raise HTTPException(404, 'news_unavailable')
            q = q.where(tuple_(ChatGeneration.created_at, ChatGeneration.id) < tuple_(literal(prior.created_at), literal(prior.id)))
        rows = list((await s.scalars(q.order_by(ChatGeneration.created_at.desc(), ChatGeneration.id.desc()).limit(51))).all())
        models = []
        for m in p.models:
            try:
                chat.model_for(p, aid, m.key)
            except HTTPException:
                continue
            models.append({'key': m.key, 'label': m.label, 'provider': m.provider, 'input_usd_per_million': str(m.input_usd),
                           'output_usd_per_million': str(m.output_usd), 'max_input_chars': m.max_input_chars, 'price_reference': m.price_reference})
        return {'day_start': day.isoformat(), 'requests_today': count, 'request_limit': p.user_daily_requests,
                'remaining_requests': max(0, p.user_daily_requests-count), 'personal_charge_usd': str(personal),
                'remaining_budget_usd': str(max(Decimal(0), min(p.user_daily_budget_usd-personal, p.daily_budget_usd-total))),
                'scope': 'personal_all_projects_daily_budget', 'models': models,
                'requests': [{'id': str(g.id), 'status': g.status, 'provider': g.model['provider'], 'model': g.model['label'],
                    'created_at': g.created_at.isoformat(), 'actual_usd': str(g.actual_usd) if g.actual_usd is not None else None,
                    'reserved_usd': str(g.reserved_usd), 'feedback': g.feedback, 'error_code': g.error_code} for g in rows[:50]],
                'older_before': str(rows[49].id) if len(rows) > 50 else None}


@router.post('/user/api/assistants/{aid}/research/usage/{gid}/feedback')
async def usage_feedback(aid: uuid.UUID, gid: uuid.UUID, payload: Feedback, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    chat.require(user)
    async with SessionLocal() as s:
        g = await s.scalar(select(ChatGeneration).where(ChatGeneration.id == gid,
            ChatGeneration.assistant_id == aid, ChatGeneration.user_id == user.id).with_for_update())
        if g is None:
            raise HTTPException(404, 'news_unavailable')
        if g.status != 'completed':
            raise HTTPException(409, 'completed_answer_required')
        g.feedback = payload.value
        await s.commit()
    return {'status': 'saved'}
