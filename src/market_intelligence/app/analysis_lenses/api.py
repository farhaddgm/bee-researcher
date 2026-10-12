from __future__ import annotations

import uuid
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, text

from app import admin
from app.analysis_lenses import service as svc
from app.analysis_lenses.models import Lens, LensPolicy, PreviewRun, Revision
from app.analysis_lenses.schemas import Create, Definition, Discovery, Draft, Language, Policy, Preview, RevisionAction, digest
from app.database import SessionLocal
from app.models import Publication
from app.news_chat import service as chat
from app.news_chat.api import owner
from app.news_chat.context import context_for
from app.news_chat.models import ChatConversation
from app.news_chat.schemas import Question
from app.security_controls import ADMIN_SESSION_COOKIE

class PrivateAnalysisRoute(APIRoute):
    """Unexpected database/upstream errors must not log prompt/SQL values."""
    def get_route_handler(self):
        handle = super().get_route_handler()
        async def private_handle(request):
            try:
                return await handle(request)
            except RequestValidationError as exc:
                # Return field locations, never Pydantic's raw input/context
                # (a rejected Owner definition can contain accidental secrets).
                names={'body','query','path','cookie','header','lid','pid','sid','asset','offset','assistant_id','language',
                       'definition','dimensions','localized_labels','name','summary','description','questions',
                       'required_information','priority','enabled','examples','good','bad','fa','en','tr','ar','es','it','de','fr'}
                for schema in (Create,Definition,Discovery,Draft,Policy,Preview,RevisionAction):
                    names.update(schema.model_fields)
                errors=[{'loc':[part if isinstance(part,str) and part in names else part if type(part) is int and 0<=part<100 else 'field' for part in e['loc'][:12]],
                         'type':e['type']} for e in exc.errors()[:32]]
                return JSONResponse(status_code=422,content={'detail':errors})
            except HTTPException:
                raise
            except Exception as exc:
                logging.getLogger('app.analysis_lenses').error('analysis_request_failed exception_type=%s', type(exc).__name__)
                raise HTTPException(500, 'analysis_service_error') from None
        return private_handle


router = APIRouter(route_class=PrivateAnalysisRoute)
ROOT = Path(__file__).parent
READER_COOKIE = admin.USER_SESSION_COOKIE


@router.get('/assets/analysis-lenses/{asset}', include_in_schema=False)
async def asset(asset: str):
    allowed = {'reader.js': 'application/javascript', 'admin.js': 'application/javascript', 'i18n.js': 'application/javascript', 'lenses.css': 'text/css'}
    if asset not in allowed:
        raise HTTPException(404)
    return FileResponse(ROOT / asset, media_type=allowed[asset], headers={'Cache-Control': 'no-cache'})


@router.get('/admin/api/analysis-lenses')
async def admin_catalog(language: Language = 'fa', token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as session:
        return {'lenses': await svc.catalog(session, language, owner=True), 'policy': (await svc.policy(session)).model_dump()}


@router.post('/admin/api/analysis-lenses', status_code=201)
async def create(payload: Create, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as session:
        return await svc.create(session, payload, actor)


@router.put('/admin/api/analysis-lenses/{lid}/draft')
async def draft(lid: uuid.UUID, payload: Draft, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as session:
        return await svc.draft(session, lid, payload, actor)


@router.post('/admin/api/analysis-lenses/{lid}/validate')
async def validate(lid: uuid.UUID, payload: Definition, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as session:
        if not await session.get(Lens, lid):
            raise HTTPException(404, 'lens_unavailable')
    return {'valid': True, 'hash': digest(payload.model_dump(mode='json'))}


@router.get('/admin/api/analysis-lenses/{lid}/revisions')
async def revisions(lid: uuid.UUID, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as session:
        lens = await session.get(Lens, lid)
        if not lens:
            raise HTTPException(404, 'lens_unavailable')
        rows = (await session.scalars(select(Revision).where(Revision.lens_id == lid).order_by(Revision.revision.desc()).limit(100))).all()
        return {'revisions': [svc.metadata(lens, r, include_definition=True) for r in rows]}


@router.post('/admin/api/analysis-lenses/{lid}/restore')
async def restore(lid: uuid.UUID, payload: RevisionAction, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as session:
        row = await svc.revision(session, lid, payload.revision)
        if row.definition_hash != payload.definition_hash:
            raise HTTPException(409, 'lens_revision_changed')
        return await svc.draft(session, lid, Draft(expected_version=payload.expected_version, definition=Definition.model_validate(row.definition)), actor)


@router.post('/admin/api/analysis-lenses/{lid}/publish')
async def publish(lid: uuid.UUID, payload: RevisionAction, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as session:
        return await svc.action(session, lid, payload, actor, 'publish')


@router.post('/admin/api/analysis-lenses/{lid}/archive')
async def archive(lid: uuid.UUID, payload: RevisionAction, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as session:
        return await svc.action(session, lid, payload, actor, 'archive')


@router.post('/admin/api/analysis-lenses/{lid}/revoke')
async def revoke(lid: uuid.UUID, payload: RevisionAction, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as session:
        return await svc.action(session, lid, payload, actor, 'revoke')


@router.put('/admin/api/analysis-lenses/policy')
async def set_policy(payload: Policy, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as session:
        await svc.lock(session)
        current = await svc.policy(session)
        if payload.version != current.version:
            raise HTTPException(409, 'draft_conflict')
        target = await session.scalar(select(Lens).where(Lens.key == payload.default_key, Lens.archived.is_(False), Lens.active_revision.is_not(None)))
        if not target or (await svc.revision(session, target.id, target.active_revision)).status != 'published':
            raise HTTPException(422, 'default_lens_required')
        row = await session.get(LensPolicy, 1)
        config = payload.model_copy(update={'version': current.version + 1}).model_dump()
        if row:
            row.config = config
        else:
            session.add(LensPolicy(id=1, config=config))
        await session.commit()
        return {'policy': config}


@router.get('/admin/api/analysis-lenses/policy')
async def get_policy(token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as session:
        return {'policy': (await svc.policy(session)).model_dump()}


@router.get('/admin/api/analysis-lenses/preview-sources')
async def preview_sources(assistant_id: uuid.UUID | None = None, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    projects = await admin.reader_assistants(actor)
    assistants = cast(list[dict[str, Any]], projects['assistants'])
    if assistant_id and str(assistant_id) not in {str(a['id']) for a in assistants}:
        raise HTTPException(404, 'news_unavailable')
    async with SessionLocal() as session:
        publications = []
        if assistant_id:
            rows = (await session.scalars(select(Publication).where(Publication.assistant_id == assistant_id, Publication.status == 'published').order_by(Publication.published_at.desc(), Publication.id.desc()).limit(100))).all()
            publications = [{'id': str(p.id), 'title': '\n'.join(s['text'] for s in context_for(p.message_text, None)['segments']).splitlines()[0][:180]} for p in rows if p.message_text.strip()]
        config = await chat.policy(session)
        from app.config import get_settings
        from app.news_chat.providers import configured
        models = [{'key': m.key, 'label': m.label, 'input_usd': str(m.input_usd), 'output_usd': str(m.output_usd)} for m in config.models
                  if m.enabled and m.verified and m.max_output_tokens >= 1000 and configured(get_settings(), m.provider)]
        return {'assistants': projects['assistants'], 'publications': publications, 'models': models}


@router.post('/admin/api/analysis-lenses/{lid}/preview', status_code=202)
async def preview(lid: uuid.UUID, payload: Preview, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    # Serialize preview creation with ordinary admission, including retry.
    async with SessionLocal() as session:
        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': chat.LOCK})
        row = await svc.revision(session, lid, payload.revision)
        if row.definition_hash != payload.definition_hash or row.status == 'revoked':
            raise HTTPException(409, 'lens_revision_changed')
        pub = await chat.publication(session, payload.publication_id, actor)
        model = chat.model_for(await chat.policy(session), pub.assistant_id, payload.model_key)
        from app.news_chat.models import ChatGeneration
        prior = await session.scalar(select(ChatGeneration).where(ChatGeneration.user_id == actor.id, ChatGeneration.idempotency_key == payload.idempotency_key))
        if prior:
            existing = await session.scalar(select(PreviewRun).where(PreviewRun.generation_id == prior.id, PreviewRun.actor_id == actor.id))
            prior_conversation = await session.get(ChatConversation, prior.conversation_id) if prior.conversation_id else None
            if not existing or not prior_conversation or prior_conversation.publication_id != pub.id or existing.lens_id != lid or existing.revision != row.revision or existing.definition_hash != row.definition_hash or prior.language != payload.language or prior.model['model_id'] != model.model_id or prior.model['provider'] != model.provider:
                raise HTTPException(409, 'idempotency_conflict')
            return {'id': str(existing.id), 'generation': chat.view(prior)}
        context = context_for(pub.message_text, pub.published_at.isoformat() if pub.published_at else None)
        context['_audience'] = 'owner_preview'
        context['_analysis'] = svc.freeze(row, 'focused', [pub.id])
        context['_analysis']['analysis_version'] = digest({'source': context['version'], 'lens': context['_analysis']['version']})
        conversation = ChatConversation(id=uuid.uuid4(), user_id=actor.id, assistant_id=pub.assistant_id, publication_id=pub.id, context=context, provider=model.provider, created_at=chat.now())
        session.add(conversation)
        await session.flush()
        question = Question(question='Analyze this selected report using the supplied lens.', model_key=payload.model_key, language=payload.language,
                            context_version=context['version'], analysis_version=context['_analysis']['analysis_version'], intent='lens_analysis', idempotency_key=payload.idempotency_key)
        generation = await chat.send(conversation.id, question, actor, token or '', audience='owner_preview', _session=session)
        # These mappers use FK IDs rather than ORM relationships. Explicitly
        # insert the queued generation before its dependent preview row;
        # both are still invisible to the worker until the one outer commit.
        await session.flush()
        record = PreviewRun(id=uuid.uuid4(), actor_id=actor.id, lens_id=lid, revision=row.revision, definition_hash=row.definition_hash,
            conversation_id=conversation.id, generation_id=uuid.UUID(generation['id']), source_version=context['version'], expires_at=chat.now() + timedelta(hours=24))
        session.add(record)
        await session.commit()
        return {'id': str(record.id), 'generation': generation}


@router.get('/admin/api/analysis-lenses/previews/{pid}')
async def preview_status(pid: uuid.UUID, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await admin.current_admin(token, touch=False)
    if not admin.is_owner(actor):
        raise HTTPException(403, 'owner_required')
    async with SessionLocal() as session:
        row = await session.get(PreviewRun, pid)
        if not row or row.actor_id != actor.id:
            raise HTTPException(404, 'news_unavailable')
        if row.expires_at <= chat.now() or not row.conversation_id:
            raise HTTPException(410, 'preview_expired')
        value = await chat.authorized_generation(session, row.generation_id, actor, audience='owner_preview')
        return {'id': str(row.id), 'source_version': row.source_version, 'generation': chat.view(value), 'valid': value.status == 'completed' and bool(value.analysis_result)}


@router.post('/admin/api/analysis-lenses/previews/{pid}/cancel')
async def cancel_preview(pid: uuid.UUID, token: str | None = Cookie(None, alias=ADMIN_SESSION_COOKIE)):
    actor = await owner(token)
    async with SessionLocal() as session:
        row = await session.get(PreviewRun, pid)
        if not row or row.actor_id != actor.id:
            raise HTTPException(404, 'news_unavailable')
        value = await chat.authorized_generation(session, row.generation_id, actor, audience='owner_preview')
        value.cancel_requested = True
        await session.commit()
        return {'status': 'cancel_requested'}


@router.get('/user/api/analysis-lenses')
async def reader_catalog(assistant_id: uuid.UUID, language: Language = 'fa', token: str | None = Cookie(None, alias=READER_COOKIE)):
    user = await admin.current_reader(token)
    chat.require(user)
    from app.reader_research.service import project
    await project(user, assistant_id)
    async with SessionLocal() as session:
        config = await svc.policy(session)
        return {'enabled': config.enabled, 'lenses': await svc.catalog(session, language) if config.enabled else [], 'default_key': config.default_key}


@router.post('/user/api/publications/{pid}/analysis-discovery')
async def discover(pid: uuid.UUID, payload: Discovery, token: str | None = Cookie(None, alias=READER_COOKIE)):
    user = await admin.current_reader(token)
    chat.require(user)
    async with SessionLocal() as session:
        pub = await chat.publication(session, pid, user)
        snapshot = await svc.discover(session, pub, user, payload.lookback_days)
        return await svc.discovery_page(session, snapshot, user)


@router.get('/user/api/analysis-discovery/{sid}')
async def discovery_page(sid: uuid.UUID, offset: int = Query(0, ge=0, le=40), token: str | None = Cookie(None, alias=READER_COOKIE)):
    user = await admin.current_reader(token, touch=False)
    chat.require(user)
    from app.analysis_lenses.models import DiscoverySnapshot
    async with SessionLocal() as session:
        return await svc.discovery_page(session, await session.get(DiscoverySnapshot, sid), user, offset)
