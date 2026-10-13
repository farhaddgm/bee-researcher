from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text

from app.analysis_lenses import discovery
from app.analysis_lenses.compiler import COMPILER_VERSION
from app.analysis_lenses.models import Audit, DiscoverySnapshot, Lens, LensPolicy, PreviewRun, Revision
from app.analysis_lenses.schemas import Definition, Policy, Selection, digest
from app.models import ArticleAnalysis, NormalizedArticle, Publication, Source, SourceItem
from app.news_chat import service as chat
from app.news_chat.context import context_for

LOCK = 71395001


async def lock(session):
    await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK})


async def policy(session) -> Policy:
    row = await session.get(LensPolicy, 1)
    return Policy.model_validate(row.config if row else {})


async def enabled(session):
    value = await policy(session)
    if not value.enabled:
        raise HTTPException(403, 'analysis_disabled')
    return value


async def revision(session, lid, number, *, locked=False):
    query = select(Revision).where(Revision.lens_id == lid, Revision.revision == number)
    if locked:
        query = query.with_for_update()
    row = await session.scalar(query)
    if not row:
        raise HTTPException(404, 'lens_unavailable')
    return row


def metadata(lens, row, language='en', *, include_definition=False):
    definition = Definition.model_validate(row.definition)
    labels = definition.localized_labels.get(language)
    value = {'id': str(lens.id), 'key': lens.key, 'revision': row.revision, 'hash': row.definition_hash,
             'name': labels.name if labels else definition.name, 'summary': labels.summary if labels else definition.summary,
             'source_language': definition.source_language, 'status': row.status, 'version': lens.version,
             'labels': {lang: v.model_dump() for lang, v in definition.localized_labels.items()},
             'archived': lens.archived, 'active_revision': lens.active_revision,
             'dimensions': [{'key': d.key, 'name': d.name, 'description': d.description, 'priority': d.priority} for d in definition.dimensions if d.enabled]}
    if include_definition:
        value['definition'] = definition.model_dump(mode='json')
    return value


async def catalog(session, language='en', *, owner=False):
    query = select(Lens, Revision).join(Revision, Revision.lens_id == Lens.id)
    if not owner:
        query = query.where(Lens.archived.is_(False), Revision.status == 'published', Revision.revision == Lens.active_revision)
    else:
        latest = select(func.max(Revision.revision)).where(Revision.lens_id == Lens.id).correlate(Lens).scalar_subquery()
        query = query.where(Revision.revision == latest)
    return [metadata(l, r, language, include_definition=owner) for l, r in (await session.execute(query.order_by(Lens.key, Revision.revision.desc()))).all()]


async def changed(session, lens, actor, action, definition_hash=None):
    lens.version += 1
    session.add(Audit(actor_id=actor.id, lens_id=lens.id, action=action, definition_hash=definition_hash))


async def create(session, payload, actor):
    await lock(session)
    if await session.scalar(select(Lens.id).where(Lens.key == payload.key)):
        raise HTTPException(409, 'lens_key_exists')
    if (await session.scalar(select(func.count()).select_from(Lens)) or 0) >= 50:
        raise HTTPException(429, 'lens_limit')
    lens = Lens(id=uuid.uuid4(), key=payload.key, version=1, archived=False)
    session.add(lens)
    await session.flush()
    definition = payload.definition.model_dump(mode='json')
    row = Revision(id=uuid.uuid4(), lens_id=lens.id, revision=1, definition=definition, definition_hash=digest(definition), status='draft', actor_id=actor.id)
    session.add(row)
    session.add(Audit(actor_id=actor.id, lens_id=lens.id, action='create', definition_hash=row.definition_hash))
    await session.commit()
    return metadata(lens, row, include_definition=True)


async def draft(session, lid, payload, actor):
    await lock(session)
    lens = await session.get(Lens, lid, with_for_update=True)
    if not lens:
        raise HTTPException(404, 'lens_unavailable')
    if lens.version != payload.expected_version:
        raise HTTPException(409, 'draft_conflict')
    number = (await session.scalar(select(func.max(Revision.revision)).where(Revision.lens_id == lid)) or 0) + 1
    value = payload.definition.model_dump(mode='json')
    row = Revision(id=uuid.uuid4(), lens_id=lid, revision=number, definition=value, definition_hash=digest(value), status='draft', actor_id=actor.id)
    session.add(row)
    await changed(session, lens, actor, 'draft', row.definition_hash)
    await session.commit()
    return metadata(lens, row, include_definition=True)


async def action(session, lid, payload, actor, kind):
    await lock(session)
    lens = await session.get(Lens, lid, with_for_update=True)
    if not lens:
        raise HTTPException(404, 'lens_unavailable')
    if lens.version != payload.expected_version:
        raise HTTPException(409, 'draft_conflict')
    row = await revision(session, lid, payload.revision, locked=True)
    if row.definition_hash != payload.definition_hash:
        raise HTTPException(409, 'lens_revision_changed')
    if kind == 'publish':
        preview = await session.get(PreviewRun, payload.preview_id) if payload.preview_id else None
        from app.news_chat.models import ChatConversation, ChatGeneration
        generation = await session.get(ChatGeneration, preview.generation_id) if preview else None
        if not (payload.approved and preview and preview.actor_id == actor.id and preview.lens_id == lid
                and preview.revision == row.revision and preview.definition_hash == row.definition_hash
                and preview.expires_at > chat.now() and generation and generation.status == 'completed'
                and generation.analysis_result and row.status == 'draft'):
            raise HTTPException(409, 'preview_required')
        conversation = await session.get(ChatConversation, preview.conversation_id)
        if not conversation or conversation.deleted_at:
            raise HTTPException(409, 'preview_required')
        publication = await chat.publication(session, conversation.publication_id, actor)
        if context_for(publication.message_text, None)['version'] != preview.source_version:
            raise HTTPException(409, 'context_changed')
        row.status, lens.active_revision, lens.archived = 'published', row.revision, False
    elif kind in {'archive', 'revoke'}:
        config = await policy(session)
        if lens.key == config.default_key and (kind == 'archive' or lens.active_revision == row.revision):
            replacement = await session.scalar(select(Lens).where(Lens.key == payload.replacement_key, Lens.archived.is_(False), Lens.active_revision.is_not(None), Lens.id != lid)) if payload.replacement_key else None
            if not replacement or (await revision(session, replacement.id, replacement.active_revision)).status != 'published':
                raise HTTPException(409, 'default_lens_required')
            p = await session.get(LensPolicy, 1)
            p.config = config.model_copy(update={'default_key': replacement.key, 'version': config.version + 1}).model_dump()
        if kind == 'archive':
            lens.archived = True
        else:
            if not payload.reason.strip():
                raise HTTPException(422, 'reason_required')
            row.status = 'revoked'
            if lens.active_revision == row.revision:
                lens.archived = True
    else:
        raise HTTPException(422, 'invalid_action')
    await changed(session, lens, actor, kind, row.definition_hash)
    await session.commit()
    return metadata(lens, row, include_definition=True)


def freeze(row, scope, sources) -> dict:
    value = {'schema_version': 1, 'lens_id': str(row.lens_id), 'revision': row.revision, 'definition_hash': row.definition_hash,
             'definition': row.definition, 'scope': scope, 'source_ids': [str(v) for v in sources], 'compiler_version': COMPILER_VERSION}
    value['version'] = digest(value)
    return value


async def attach(session, context, selection: Selection, sources, pub, user):
    await enabled(session)
    lens = await session.get(Lens, selection.lens_id)
    if not lens or lens.archived:
        raise HTTPException(404, 'lens_unavailable')
    row = await revision(session, lens.id, selection.lens_revision)
    if row.status != 'published' or lens.active_revision != row.revision or selection.lens_hash != row.definition_hash:
        raise HTTPException(409, 'lens_revision_changed')
    if pub.id not in sources or len(set(sources)) != len(sources):
        raise HTTPException(422, 'analysis_selection_invalid')
    if selection.scope == 'focused':
        if sources != [pub.id]:
            raise HTTPException(422, 'analysis_selection_invalid')
    else:
        snapshot = await session.get(DiscoverySnapshot, selection.discovery_snapshot_id)
        if not snapshot or snapshot.user_id != user.id or snapshot.assistant_id != pub.assistant_id or snapshot.publication_id != pub.id:
            raise HTTPException(404, 'news_unavailable')
        if snapshot.expires_at <= chat.now():
            raise HTTPException(409, 'discovery_expired')
        if selection.lookback_days != snapshot.data['lookback_days'] or not 2 <= len(sources) <= 5:
            raise HTTPException(422, 'analysis_selection_invalid')
        candidates = {r['id']: r for r in snapshot.data['candidates']}
        for sid in sources:
            if sid == pub.id:
                if context_for(pub.message_text, None)['version'] != snapshot.data['anchor_version']:
                    raise HTTPException(409, 'context_changed')
                continue
            if str(sid) not in candidates:
                raise HTTPException(422, 'analysis_selection_invalid')
            source = await chat.publication(session, sid, user)
            if context_for(source.message_text, None)['version'] != candidates[str(sid)]['version']:
                raise HTTPException(409, 'context_changed')
    context['_analysis'] = freeze(row, selection.scope, sources)
    context['_analysis']['analysis_version'] = digest({'source': context['version'], 'lens': context['_analysis']['version']})
    return context


async def validate_context(session, context, *, preview=False):
    profile = context.get('_analysis')
    if not profile:
        return
    if not preview:
        await enabled(session)
    lens = await session.get(Lens, uuid.UUID(profile['lens_id']))
    row = await revision(session, uuid.UUID(profile['lens_id']), profile['revision'])
    if not lens or (lens.archived and not preview) or row.status == 'revoked' or row.definition_hash != profile['definition_hash']:
        raise HTTPException(403, 'lens_revoked')


async def discover(session, pub, user, days):
    await enabled(session)
    await chat.publication(session, pub.id, user)
    await lock(session)
    count = await session.scalar(select(func.count()).select_from(DiscoverySnapshot).where(DiscoverySnapshot.user_id == user.id, DiscoverySnapshot.expires_at > chat.now() + timedelta(minutes=9))) or 0
    if count >= 5:
        raise HTTPException(429, 'quota_exceeded')
    as_of = chat.now()
    dated = func.coalesce(Publication.published_at, Publication.created_at)
    pubs = list((await session.scalars(select(Publication).where(Publication.assistant_id == pub.assistant_id, Publication.status == 'published',
        Publication.id != pub.id, dated >= as_of - timedelta(days=days), dated <= as_of).order_by(dated.desc(), Publication.id.desc()).limit(501))).all())
    rows = []
    ids = [p.id for p in pubs[:500]]
    names = dict((await session.execute(select(Publication.id, Source.name).join(ArticleAnalysis,
        (ArticleAnalysis.id == Publication.analysis_id) & (ArticleAnalysis.assistant_id == pub.assistant_id)).join(NormalizedArticle,
        (NormalizedArticle.id == ArticleAnalysis.article_id) & (NormalizedArticle.assistant_id == pub.assistant_id)).join(SourceItem,
        (SourceItem.id == NormalizedArticle.source_item_id) & (SourceItem.assistant_id == pub.assistant_id)).join(Source,
        (Source.id == SourceItem.source_id) & (Source.assistant_id == pub.assistant_id)).where(Publication.id.in_(ids)))).all()) if ids else {}
    for p in pubs[:500]:
        ctx = context_for(p.message_text, p.published_at.isoformat() if p.published_at else None)
        plaintext = '\n'.join(x['text'] for x in ctx['segments'])
        rows.append({'id': str(p.id), 'title': plaintext.splitlines()[0][:180] if plaintext else '', 'text': plaintext,
                     'version': ctx['version'], 'source_name': names.get(p.id, ''), 'published_at': (p.published_at or p.created_at).isoformat()})
    anchor = context_for(pub.message_text, None)
    matches = discovery.rank('\n'.join(x['text'] for x in anchor['segments']), rows)
    # Snapshots contain identifiers and bounded visible excerpts, not copies
    # of fifty reports. Access is rechecked whenever the snapshot is read.
    candidates = [{**{k: v for k, v in r.items() if k not in {'text', 'score'}}, 'excerpt': r['text'][:240]} for r in matches]
    data = {'as_of': as_of.isoformat(), 'lookback_days': days, 'coverage': min(len(pubs), 500), 'limited': len(pubs) > 500,
            'anchor_version': anchor['version'], 'candidates': candidates}
    snapshot = DiscoverySnapshot(id=uuid.uuid4(), user_id=user.id, assistant_id=pub.assistant_id, publication_id=pub.id, data=data, expires_at=as_of + timedelta(minutes=10))
    session.add(snapshot)
    await session.commit()
    return snapshot


async def discovery_page(session, snapshot, user, offset=0):
    if not snapshot or snapshot.user_id != user.id:
        raise HTTPException(404, 'news_unavailable')
    await chat.publication(session, snapshot.publication_id, user)
    if snapshot.expires_at <= chat.now():
        raise HTTPException(409, 'discovery_expired')
    valid = []
    page = snapshot.data['candidates'][offset:offset + 10]
    for row in page:
        source = await session.scalar(select(Publication).where(Publication.id == uuid.UUID(row['id']), Publication.assistant_id == snapshot.assistant_id, Publication.status == 'published'))
        if source and context_for(source.message_text, None)['version'] == row['version']:
            valid.append({key: value for key, value in row.items() if key not in {'text', 'score'}})
    return {'id': str(snapshot.id), 'candidates': valid, 'next_offset': offset + 10 if len(snapshot.data['candidates']) > offset + 10 else None,
            'coverage': snapshot.data['coverage'], 'limited': snapshot.data['limited'], 'as_of': snapshot.data['as_of'], 'lookback_days': snapshot.data['lookback_days']}


async def cleanup(session):
    await session.execute(delete(DiscoverySnapshot).where(DiscoverySnapshot.expires_at <= chat.now()))
    from app.news_chat.models import ChatConversation
    for preview in (await session.scalars(select(PreviewRun).where(PreviewRun.expires_at <= chat.now(), PreviewRun.conversation_id.is_not(None)).with_for_update())).all():
        conversation = await session.get(ChatConversation, preview.conversation_id)
        if conversation and conversation.deleted_at is None:
            await chat.erase_conversation(session, conversation)
        preview.conversation_id = None
    await session.commit()
