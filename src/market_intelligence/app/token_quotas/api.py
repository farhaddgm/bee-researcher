from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import literal, or_, select, text, tuple_
from app import admin
from app.database import SessionLocal
from app.models import AdminUser, AssistantMember, AssistantWorkspace
from app.news_chat.models import ChatGeneration
from app.news_chat.service import LOCK
from app.security_controls import ADMIN_SESSION_COOKIE
from app.token_quotas import service
from app.token_quotas.models import TokenLimit
from app.token_quotas.schemas import SaveLimit

router = APIRouter()
COOKIE = admin.USER_SESSION_COOKIE
ROOT = Path(__file__).parent


@router.get('/assets/token-quotas/{asset}', include_in_schema=False)
async def asset(asset: str):
    types = {'quotas.js': 'application/javascript', 'i18n.js': 'application/javascript', 'quotas.css': 'text/css'}
    if asset not in types:
        raise HTTPException(404)
    return FileResponse(ROOT / asset, media_type=types[asset], headers={'Cache-Control': 'no-cache'})


async def owner(request, admin_token, reader_token):
    actor = await admin.current_admin(admin_token) if request.url.path.startswith('/admin/') else await admin.current_reader(reader_token)
    if not admin.is_owner(actor):
        raise HTTPException(403, 'owner_required')
    return actor


async def target(s, aid, uid):
    if aid is None:
        return
    project = await s.get(AssistantWorkspace, aid)
    if not project or project.deleted_at is not None:
        raise HTTPException(404, 'news_unavailable')
    if uid is not None:
        user = await s.get(AdminUser, uid)
        member = await s.scalar(select(AssistantMember.id).where(AssistantMember.assistant_id == aid, AssistantMember.user_id == uid))
        if not user or (not admin.is_owner(user) and member is None):
            raise HTTPException(404, 'news_unavailable')


@router.get('/admin/api/token-quotas')
@router.get('/user/api/token-quotas/owner')
async def catalog(request: Request, assistant_id: uuid.UUID | None = None,
                  admin_token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE),
                  reader_token: str | None = Cookie(None, alias=COOKIE)):
    await owner(request, admin_token, reader_token)
    async with SessionLocal() as s:
        await target(s, assistant_id, None)
        projects = (await s.scalars(select(AssistantWorkspace).where(AssistantWorkspace.deleted_at.is_(None)).order_by(AssistantWorkspace.name, AssistantWorkspace.id))).all()
        result = {'projects': [{'id': str(p.id), 'name': p.name} for p in projects],
                  'default': service.row_view(await s.get(TokenLimit, service.key())), 'users': []}
        if assistant_id:
            result['project'] = service.row_view(await s.get(TokenLimit, service.key(assistant_id)), assistant_id)
            users = (await s.scalars(select(AdminUser).where(or_(AdminUser.email == admin.owner_email(),
                AdminUser.id.in_(select(AssistantMember.user_id).where(AssistantMember.assistant_id == assistant_id))))
                .order_by(AdminUser.display_name, AdminUser.username, AdminUser.id))).all()
            rows = {r.user_id: r for r in (await s.scalars(select(TokenLimit).where(TokenLimit.assistant_id == assistant_id, TokenLimit.user_id.is_not(None)))).all()}
            result['users'] = [{'id': str(u.id), 'name': u.display_name or u.username, 'username': u.username, 'active': u.active,
                                'policy': service.row_view(rows.get(u.id), assistant_id, u.id)} for u in users]
        return result


@router.put('/admin/api/token-quotas')
@router.put('/user/api/token-quotas/owner')
async def save(payload: SaveLimit, request: Request,
               admin_token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE),
               reader_token: str | None = Cookie(None, alias=COOKIE)):
    actor = await owner(request, admin_token, reader_token)
    async with SessionLocal() as s:
        # Configuration and requests serialize together. No stale limit reads
        # or lost reset updates, even when the initial row doesn't exist.
        await s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK})
        await target(s, payload.assistant_id, payload.user_id)
        identity = service.key(payload.assistant_id, payload.user_id)
        row = await s.get(TokenLimit, identity, with_for_update=True)
        if payload.version != (row.version if row else 0):
            raise HTTPException(409, 'revision_conflict')
        if row is None:
            row = TokenLimit(id=identity, assistant_id=payload.assistant_id, user_id=payload.user_id, version=0)
            s.add(row)
        row.inherit, row.limits = payload.inherit, payload.limits.model_dump()
        row.version += 1
        row.updated_by, row.updated_at = actor.id, datetime.now(timezone.utc)
        await s.commit()
        result = service.row_view(row, payload.assistant_id, payload.user_id)
    await admin._audit(actor.id, 'reader.token_limits', assistant_id=payload.assistant_id,
                       details={'user_id': str(payload.user_id) if payload.user_id else None,
                                'inherit': payload.inherit, 'limits': payload.limits.model_dump(), 'version': result['version']})
    return result


def usage_view(g):
    return {'id': str(g.id), 'created_at': g.created_at.isoformat(), 'status': g.status,
            'provider': g.model.get('provider', ''), 'model': g.model.get('label', ''),
            'input_tokens': g.input_tokens, 'output_tokens': g.output_tokens,
            'reserved_tokens': g.reserved_tokens if g.input_tokens is None or g.output_tokens is None else 0}


@router.get('/user/api/assistants/{aid}/token-report')
async def report(aid: uuid.UUID, before: uuid.UUID | None = None, token: str | None = Cookie(None, alias=COOKIE)):
    user = await admin.current_reader(token)
    from app.reader_research.service import project
    await project(user, aid)
    async with SessionLocal() as s:
        summary = await service.report(s, aid, user.id, datetime.now(timezone.utc))
        query = select(ChatGeneration).where(ChatGeneration.user_id == user.id, ChatGeneration.assistant_id == aid)
        if before:
            prior = await s.scalar(query.where(ChatGeneration.id == before))
            if not prior:
                raise HTTPException(404, 'news_unavailable')
            query = query.where(tuple_(ChatGeneration.created_at, ChatGeneration.id) < tuple_(literal(prior.created_at), literal(prior.id)))
        rows = (await s.scalars(query.order_by(ChatGeneration.created_at.desc(), ChatGeneration.id.desc()).limit(51))).all()
        return {**summary, 'requests': [usage_view(g) for g in rows[:50]], 'older_before': str(rows[49].id) if len(rows) > 50 else None}
