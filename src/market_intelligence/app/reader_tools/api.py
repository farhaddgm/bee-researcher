from __future__ import annotations
import difflib
import uuid
from pathlib import Path
from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import case, func, literal, or_, select, text, tuple_
from app import admin
from app.database import SessionLocal
from app.models import AdminUser, AssistantMember, Publication
from app.news_chat import service as chat
from app.news_chat.models import ChatConversation
from app.reader_research.api import reader, sources_visible
from app.reader_research.models import ResearchRecord
from app.reader_research.service import project
from app.reader_tools import corrections as changes
from app.reader_tools.models import ExpertReply, ExpertRequest, NewsMonitor, NewsRevision, NewsWatch
from app.reader_tools.schemas import ExpertCreate, Reply, RequestState, Seen, Watch

router = APIRouter()
COOKIE = admin.USER_SESSION_COOKIE
ROOT = Path(__file__).parent
VISIBLE_REQUEST = text("""NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(reader_expert_requests.publication_ids) AS refs(id)
    WHERE NOT EXISTS (SELECT 1 FROM market_intelligence.publications AS p
        WHERE p.id::text = refs.id AND p.assistant_id = reader_expert_requests.assistant_id AND p.status = 'published'))""")


@router.get('/assets/reader-tools/{asset}', include_in_schema=False)
async def asset(asset: str):
    types = {'tools.js': 'application/javascript', 'i18n.js': 'application/javascript', 'tools.css': 'text/css'}
    if asset not in types:
        raise HTTPException(404)
    return FileResponse(ROOT / asset, media_type=types[asset], headers={'Cache-Control': 'no-cache'})


async def member(s, uid, aid):
    target = await s.get(AdminUser, uid)
    if not target or not target.active or not admin.user_portal_access_allowed(target):
        raise HTTPException(404, 'colleague_unavailable')
    await project(target, aid)
    return target


def identity(user):
    return {'id': str(user.id), 'name': user.display_name or user.username}


async def request_row(s, rid, user, aid, *, lock=False):
    query = select(ExpertRequest).where(ExpertRequest.id == rid, ExpertRequest.assistant_id == aid,
        or_(ExpertRequest.requester_id == user.id, ExpertRequest.assignee_id == user.id))
    row = await s.scalar(query.with_for_update() if lock else query)
    if row is None or not await sources_visible(s, aid, row.publication_ids):
        raise HTTPException(404, 'news_unavailable')
    return row


async def request_view(s, row, user):
    requester, assignee = await s.get(AdminUser, row.requester_id), await s.get(AdminUser, row.assignee_id)
    changed = await changes.stale_sources(s, row.assistant_id, row.publication_ids, row.source_versions, row.created_at)
    seen = row.requester_seen if row.requester_id == user.id else row.assignee_seen
    return {'id': str(row.id), 'title': row.title, 'question': row.question, 'excerpt': row.excerpt,
        'requester': identity(requester), 'assignee': identity(assignee), 'publication_ids': row.publication_ids,
        'status': row.status, 'version': row.version, 'unread': row.version > seen,
        'outgoing': row.requester_id == user.id, 'changed_sources': changed,
        'created_at': row.created_at.isoformat(), 'updated_at': row.updated_at.isoformat()}


@router.get('/user/api/assistants/{aid}/research/colleagues')
async def colleagues(aid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        eligible = select(AssistantMember.user_id).where(AssistantMember.assistant_id == aid)
        rows = list((await s.scalars(select(AdminUser).where(AdminUser.active.is_(True), AdminUser.id != user.id,
            or_(AdminUser.id.in_(eligible), AdminUser.email == admin.owner_email()))
            .order_by(AdminUser.username, AdminUser.id))).all())
        return {'colleagues': [identity(row) for row in rows if admin.user_portal_access_allowed(row)]}


@router.get('/user/api/assistants/{aid}/research/expert-requests')
async def inbox(aid: uuid.UUID, before: uuid.UUID | None = None, touch: bool = True,
                token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid, touch=touch)
    async with SessionLocal() as s:
        query = select(ExpertRequest).where(ExpertRequest.assistant_id == aid,
            or_(ExpertRequest.requester_id == user.id, ExpertRequest.assignee_id == user.id))
        query = query.where(VISIBLE_REQUEST)
        unread_count = await s.scalar(query.with_only_columns(func.count()).where(ExpertRequest.version >
            case((ExpertRequest.requester_id == user.id, ExpertRequest.requester_seen), else_=ExpertRequest.assignee_seen)))
        if before:
            prior = await s.scalar(query.where(ExpertRequest.id == before))
            if prior is None:
                raise HTTPException(404, 'news_unavailable')
            query = query.where(tuple_(ExpertRequest.created_at, ExpertRequest.id) < tuple_(literal(prior.created_at), literal(prior.id)))
        rows = list((await s.scalars(query.order_by(ExpertRequest.created_at.desc(), ExpertRequest.id.desc()).limit(51))).all())
        visible = [await request_view(s, r, user) for r in rows[:50] if await sources_visible(s, aid, r.publication_ids)]
        return {'requests': visible, 'older_before': str(rows[49].id) if len(rows) > 50 else None, 'unread_count': unread_count}


@router.post('/user/api/assistants/{aid}/research/expert-requests', status_code=201)
async def create_request(aid: uuid.UUID, payload: ExpertCreate, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        await s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': changes.LOCK})
        ids = [str(pid) for pid in payload.publication_ids]
        if not await sources_visible(s, aid, ids):
            raise HTTPException(404, 'news_unavailable')
        await member(s, payload.assignee_id, aid)
        if payload.assignee_id == user.id:
            raise HTTPException(422, 'choose_colleague')
        prior = await s.get(ExpertRequest, payload.id)
        if prior:
            if prior.requester_id != user.id or prior.assistant_id != aid:
                raise HTTPException(404, 'news_unavailable')
            if (prior.assignee_id != payload.assignee_id or prior.title != payload.title or prior.question != payload.question or
                    prior.excerpt != payload.excerpt or prior.publication_ids != ids):
                raise HTTPException(409, 'idempotency_conflict')
            return await request_view(s, prior, user)
        count = await s.scalar(select(func.count()).select_from(ExpertRequest).where(ExpertRequest.requester_id == user.id))
        if (count or 0) >= 400:
            raise HTTPException(429, 'request_limit')
        versions = await changes.dependency_versions(s, user, aid, ids)
        row = ExpertRequest(id=payload.id, assistant_id=aid, requester_id=user.id, assignee_id=payload.assignee_id,
            title=payload.title, question=payload.question, excerpt=payload.excerpt, publication_ids=ids,
            source_versions=versions, status='open', version=1, requester_seen=1, assignee_seen=0)
        s.add(row)
        await s.commit()
        return await request_view(s, row, user)


@router.get('/user/api/assistants/{aid}/research/expert-requests/{rid}')
async def detail(aid: uuid.UUID, rid: uuid.UUID, before: uuid.UUID | None = None,
                 token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        row = await request_row(s, rid, user, aid)
        query = select(ExpertReply).where(ExpertReply.request_id == rid)
        if before:
            prior = await s.scalar(query.where(ExpertReply.id == before))
            if prior is None:
                raise HTTPException(404, 'news_unavailable')
            query = query.where(tuple_(ExpertReply.created_at, ExpertReply.id) < tuple_(literal(prior.created_at), literal(prior.id)))
        rows = list((await s.scalars(query.order_by(ExpertReply.created_at.desc(), ExpertReply.id.desc()).limit(31))).all())
        replies = []
        for reply in reversed(rows[:30]):
            author = await s.get(AdminUser, reply.author_id)
            replies.append({'id': str(reply.id), 'author': identity(author), 'body': reply.body,
                            'kind': 'human', 'created_at': reply.created_at.isoformat()})
        return {**await request_view(s, row, user), 'replies': replies,
                'older_before': str(rows[29].id) if len(rows) > 30 else None}


@router.post('/user/api/assistants/{aid}/research/expert-requests/{rid}/replies', status_code=201)
async def reply(aid: uuid.UUID, rid: uuid.UUID, payload: Reply, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        row = await request_row(s, rid, user, aid, lock=True)
        previous = await s.get(ExpertReply, payload.id)
        if previous:
            if previous.request_id != rid or previous.author_id != user.id:
                raise HTTPException(404, 'news_unavailable')
            if previous.body != payload.body:
                raise HTTPException(409, 'idempotency_conflict')
            return {'id': str(previous.id), 'version': row.version}
        if row.version != payload.version:
            raise HTTPException(409, 'revision_conflict')
        if row.status in {'closed', 'cancelled'}:
            raise HTTPException(409, 'request_closed')
        await member(s, row.assignee_id if user.id == row.requester_id else row.requester_id, aid)
        count = await s.scalar(select(func.count()).select_from(ExpertReply).where(ExpertReply.request_id == rid))
        if (count or 0) >= 200:
            raise HTTPException(429, 'reply_limit')
        s.add(ExpertReply(id=payload.id, request_id=rid, author_id=user.id, body=payload.body))
        row.version += 1
        row.updated_at = chat.now()
        if user.id == row.assignee_id:
            row.status, row.assignee_seen = 'answered', row.version
        else:
            row.status, row.requester_seen = 'open', row.version
        await s.commit()
        return {'id': str(payload.id), 'version': row.version}


@router.put('/user/api/assistants/{aid}/research/expert-requests/{rid}/state')
async def request_state(aid: uuid.UUID, rid: uuid.UUID, payload: RequestState,
                        token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        row = await request_row(s, rid, user, aid, lock=True)
        if row.requester_id != user.id:
            raise HTTPException(404, 'news_unavailable')
        if row.version != payload.version:
            raise HTTPException(409, 'revision_conflict')
        row.status, row.version, row.updated_at = payload.status, row.version + 1, chat.now()
        row.requester_seen = row.version
        await s.commit()
        return await request_view(s, row, user)


@router.post('/user/api/assistants/{aid}/research/expert-requests/{rid}/seen')
async def request_seen(aid: uuid.UUID, rid: uuid.UUID, payload: Seen,
                       token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        row = await request_row(s, rid, user, aid, lock=True)
        if payload.version > row.version:
            raise HTTPException(422, 'invalid_selection')
        key = 'requester_seen' if row.requester_id == user.id else 'assignee_seen'
        setattr(row, key, max(getattr(row, key), payload.version))
        await s.commit()
    return {'status': 'seen'}


@router.put('/user/api/assistants/{aid}/research/corrections/{pid}/watch')
async def watch(aid: uuid.UUID, pid: uuid.UUID, payload: Watch, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        pub = await chat.publication(s, pid, user)
        if pub.assistant_id != aid:
            raise HTTPException(404, 'news_unavailable')
        await changes.ensure_watch(s, user, pub, enabled=payload.enabled)
        await s.commit()
    return {'enabled': payload.enabled}


@router.post('/user/api/assistants/{aid}/research/corrections/{pid}/check')
async def check(aid: uuid.UUID, pid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        pub = await chat.publication(s, pid, user)
        if pub.assistant_id != aid:
            raise HTTPException(404, 'news_unavailable')
        watch = await s.get(NewsWatch, (user.id, pid))
        if not watch or not watch.enabled:
            raise HTTPException(409, 'watch_required')
    return await changes.recheck(pid, manual=True)


@router.get('/user/api/assistants/{aid}/research/corrections')
async def corrections(aid: uuid.UUID, before: uuid.UUID | None = None, touch: bool = True,
                      token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid, touch=touch)
    async with SessionLocal() as s:
        query = select(NewsWatch, NewsMonitor, Publication).select_from(NewsWatch).join(NewsMonitor, NewsMonitor.publication_id == NewsWatch.publication_id)
        query = query.join(Publication, Publication.id == NewsWatch.publication_id).where(
            NewsWatch.user_id == user.id, NewsWatch.assistant_id == aid, Publication.assistant_id == aid,
            Publication.status == 'published')
        unread_count = await s.scalar(query.with_only_columns(func.count()).where(NewsWatch.enabled.is_(True),
            NewsMonitor.version > NewsWatch.seen_version))
        if before:
            prior = (await s.execute(query.where(NewsWatch.publication_id == before))).one_or_none()
            if prior is None:
                raise HTTPException(404, 'news_unavailable')
            query = query.where(tuple_(NewsWatch.created_at, NewsWatch.publication_id) < tuple_(literal(prior[0].created_at), literal(prior[0].publication_id)))
        rows = list((await s.execute(query.order_by(NewsWatch.created_at.desc(), NewsWatch.publication_id.desc()).limit(51))).all())
        views = [{'publication_id': str(pub.id), 'title': next(iter(changes.reader_report_text(pub.message_text).splitlines()), '')[:180],
            'enabled': watch.enabled, 'version': monitor.version, 'seen_version': watch.seen_version,
            'unread': watch.enabled and monitor.version > watch.seen_version, 'check_status': monitor.check_status,
            'checked_at': monitor.checked_at.isoformat() if monitor.checked_at else None,
            'tracking_since': watch.created_at.isoformat()} for watch, monitor, pub in rows[:50]]
        return {'watches': views, 'older_before': str(rows[49][0].publication_id) if len(rows) > 50 else None, 'unread_count': unread_count}


@router.get('/user/api/assistants/{aid}/research/corrections/{pid}')
async def revisions(aid: uuid.UUID, pid: uuid.UUID, before: int | None = Query(None, ge=1),
                    token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        pub = await chat.publication(s, pid, user)
        if pub.assistant_id != aid:
            raise HTTPException(404, 'news_unavailable')
        monitor = await s.get(NewsMonitor, pid)
        query = select(NewsRevision).where(NewsRevision.publication_id == pid, NewsRevision.assistant_id == aid)
        if before:
            query = query.where(NewsRevision.version < before)
        rows = list((await s.scalars(query.order_by(NewsRevision.version.desc()).limit(21))).all())
        views = []
        for rev in rows[:20]:
            diff = '\n'.join(difflib.unified_diff(rev.before_text.splitlines()[:600], rev.after_text.splitlines()[:600], n=2))
            views.append({'id': str(rev.id), 'version': rev.version, 'channel': rev.channel, 'notice': rev.notice,
                'title': rev.title, 'diff': diff[:16000], 'complete': rev.complete and len(diff) <= 16000,
                'before_available': bool(rev.before_text), 'created_at': rev.created_at.isoformat()})
        return {'publication_id': str(pid), 'version': monitor.version if monitor else 0, 'revisions': views,
                'older_before': rows[19].version if len(rows) > 20 else None}


@router.post('/user/api/assistants/{aid}/research/corrections/{pid}/seen')
async def correction_seen(aid: uuid.UUID, pid: uuid.UUID, payload: Seen,
                          token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        pub = await chat.publication(s, pid, user)
        row = await s.get(NewsWatch, (user.id, pid), with_for_update=True)
        monitor = await s.get(NewsMonitor, pid)
        if pub.assistant_id != aid or row is None or monitor is None:
            raise HTTPException(404, 'news_unavailable')
        if payload.version > monitor.version:
            raise HTTPException(422, 'invalid_selection')
        row.seen_version = max(row.seen_version, payload.version)
        await s.commit()
    return {'status': 'seen'}


@router.get('/user/api/assistants/{aid}/research/review-needed')
async def review_needed(aid: uuid.UUID, touch: bool = True, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid, touch=touch)
    async with SessionLocal() as s:
        result = []
        rows = list((await s.scalars(select(ResearchRecord).where(ResearchRecord.user_id == user.id,
            ResearchRecord.assistant_id == aid).order_by(ResearchRecord.updated_at.desc(), ResearchRecord.id))).all())
        for row in rows:
            if not await sources_visible(s, aid, row.publication_ids):
                continue
            changed = await changes.stale_sources(s, aid, row.publication_ids, row.source_versions, row.created_at)
            if changed:
                result.append({'kind': row.kind, 'id': str(row.id), 'title': row.title, 'changed_sources': changed})
        memories = list((await s.scalars(select(ChatConversation).where(ChatConversation.user_id == user.id,
            ChatConversation.assistant_id == aid, ChatConversation.saved_at.is_not(None),
            ChatConversation.deleted_at.is_(None)).order_by(ChatConversation.saved_at.desc(), ChatConversation.id))).all())
        for memory in memories:
            ids = memory.context.get('source_ids') or [str(memory.publication_id)]
            if not await sources_visible(s, aid, ids):
                continue
            changed = await changes.stale_sources(s, aid, ids, memory.context.get('_correction_versions'), memory.saved_at)
            if changed:
                result.append({'kind': 'memory', 'id': str(memory.id), 'title': next((seg['text'][:180] for seg in memory.context.get('segments', [])), ''), 'changed_sources': changed})
        return {'items': result}


@router.post('/user/api/assistants/{aid}/research/review-needed/{kind}/{rid}')
async def reviewed(aid: uuid.UUID, kind: str, rid: uuid.UUID, token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        if kind == 'memory':
            row = await s.get(ChatConversation, rid, with_for_update=True)
            if row is None or row.user_id != user.id or row.assistant_id != aid or not row.saved_at or row.deleted_at:
                raise HTTPException(404, 'news_unavailable')
            ids = row.context.get('source_ids') or [str(row.publication_id)]
            versions = await changes.dependency_versions(s, user, aid, ids)
            row.context = {**row.context, '_correction_versions': versions}
        else:
            record = await s.get(ResearchRecord, rid, with_for_update=True)
            if record is None or record.user_id != user.id or record.assistant_id != aid or record.kind != kind:
                raise HTTPException(404, 'news_unavailable')
            record.source_versions = await changes.dependency_versions(s, user, aid, record.publication_ids)
            record.version += 1
            record.updated_at = chat.now()
        await s.commit()
    return {'status': 'reviewed'}


@router.delete('/user/api/assistants/{aid}/research/expert-requests/{rid}')
async def delete_request(aid: uuid.UUID, rid: uuid.UUID, version: int = Query(ge=1),
                         token: str | None = Cookie(None, alias=COOKIE)):
    user = await reader(token, aid)
    async with SessionLocal() as s:
        row = await s.get(ExpertRequest, rid, with_for_update=True)
        if row is None or row.requester_id != user.id or row.assistant_id != aid:
            raise HTTPException(404, 'news_unavailable')
        if row.version != version:
            raise HTTPException(409, 'revision_conflict')
        await s.delete(row)
        await s.commit()
    return {'status': 'deleted'}
