"""Real PostgreSQL acceptance using only the isolated synthetic fixture."""
import asyncio
import copy
import hashlib
from datetime import timedelta
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from sqlalchemy import select, text
from app import admin
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser, Publication
from app.news_chat import api as chat_api, service as chat
from app.news_chat.models import ChatConversation, ChatGeneration
from app.news_chat.schemas import Question, ResearchStart
from app.analysis_lenses import api, service
from app.analysis_lenses.models import Lens, LensPolicy, PreviewRun, Revision
from app.analysis_lenses.schemas import Draft, Preview, RevisionAction, Selection, digest

settings = get_settings()
if settings.environment != 'test' or settings.postgres_db != 'news_chat_test':
    raise RuntimeError('Isolated synthetic database required')

PROJECT = uuid.UUID('10000000-0000-4000-8000-000000000004')
NEWS = uuid.UUID('60000000-0000-4000-8000-000000000001')
UID = uuid.UUID('30000000-0000-4000-8000-000000000015')
OWNER = uuid.UUID('30000000-0000-4000-8000-000000000001')


async def denied(call, code):
    try:
        await call
    except HTTPException as error:
        assert error.status_code == code, (error.status_code, error.detail)
    else:
        raise AssertionError('Expected rejection')


async def verify():
    token, owner_token = 'synthetic-lens-user-sql', 'synthetic-lens-owner-sql'
    async with SessionLocal() as session:
        user, owner = await session.get(AdminUser, UID), await session.get(AdminUser, OWNER)
        policy = await session.get(LensPolicy, 1)
        original_policy = copy.deepcopy(policy.config)
        policy.config = {**policy.config, 'enabled': True}
        for actor, value, portal in [(user, token, 'user'), (owner, owner_token, 'admin')]:
            session.add(AdminSession(user_id=actor.id, token_hash=hashlib.sha256(value.encode()).hexdigest(), portal=portal,
                expires_at=chat.now()+timedelta(minutes=30), created_at=chat.now(), mfa_verified=True))
        await session.commit()
        lenses = await service.catalog(session, 'fa')
        assert len(lenses) == 4
        general = next(x for x in lenses if x['key'] == 'general')
        pub = await chat.publication(session, NEWS, user)
        snapshot = await service.discover(session, pub, user, 30)
        page = await service.discovery_page(session, snapshot, user)
        assert page['candidates'] and page['coverage'] == 5
        assert any('اوپن' in x['title'] for x in page['candidates'])
        assert all('text' not in x and 'score' not in x for x in snapshot.data['candidates'])
        sid = uuid.UUID(page['candidates'][0]['id'])
    selection = Selection(scope='contextual', lens_id=general['id'], lens_revision=general['revision'], lens_hash=general['hash'], discovery_snapshot_id=snapshot.id)
    payload = ResearchStart(model_key='openai:fixture-v1', source_ids=[NEWS, sid], analysis_profile=selection)
    started = await chat_api.start(NEWS, payload, token=token)
    context = started['context']
    assert context['scope'] == 'selected_research' and context['analysis']['scope'] == 'contextual'
    assert '_analysis' not in context
    question = Question(question='Bounded lens check', model_key='openai:fixture-v1', language='fa', context_version=context['version'],
        analysis_version=context['analysis']['analysis_version'], intent='lens_analysis', idempotency_key='synthetic-lens-sql-question')
    sent = await chat.send(uuid.UUID(started['id']), question, user, token)
    retry = await chat.send(uuid.UUID(started['id']), question, user, token)
    assert sent['id'] == retry['id']
    await denied(chat.send(uuid.UUID(started['id']), question.model_copy(update={'analysis_version': 'a'*64}), user, token), 409)
    # The selected source changes: no new paid work can be admitted.
    async with SessionLocal() as session:
        related = await session.get(Publication, sid)
        original_text = related.message_text
        related.message_text += '\nA revised report.'
        await session.commit()
    await denied(chat.send(uuid.UUID(started['id']), question.model_copy(update={'idempotency_key': 'synthetic-lens-changed-question'}), user, token), 409)
    async with SessionLocal() as session:
        related = await session.get(Publication, sid)
        related.message_text = original_text
        await session.commit()
    await chat_api.close_window(NEWS, uuid.UUID(started['id']), token=token)
    async with SessionLocal() as session:
        generation = await session.get(ChatGeneration, uuid.UUID(sent['id']))
        assert generation.answer == generation.question == '' and generation.analysis_result is None
        assert generation.cancel_requested and generation.reserved_usd > 0
    # Owner revisions are immutable and two tabs cannot silently overwrite.
    async with SessionLocal() as session:
        lid = uuid.UUID(general['id'])
        lens = await session.get(Lens, lid)
        old_revision = await service.revision(session, lid, lens.active_revision)
        value = copy.deepcopy(old_revision.definition)
        value['objective'] += ' SQL test clarification.'
        payload = Draft(expected_version=lens.version, definition=value)
        updated = await service.draft(session, lid, payload, owner)
    async with SessionLocal() as session:
        await denied(service.draft(session, lid, payload, owner), 409)
    preview_payload = Preview(revision=updated['revision'], definition_hash=updated['hash'], publication_id=NEWS,
        model_key='openai:fixture-v1', language='en', idempotency_key='synthetic-lens-owner-preview')
    preview = await api.preview(lid, preview_payload, token=owner_token)
    again = await api.preview(lid, preview_payload, token=owner_token)
    assert preview['id'] == again['id']
    async with SessionLocal() as session:
        record = await session.get(PreviewRun, uuid.UUID(preview['id']))
        generation = await session.get(ChatGeneration, record.generation_id)
        assert generation.audience == 'owner_preview'
        await denied(chat.authorized_generation(session, generation.id, owner), 404)
        await denied(chat.conversation(session, record.conversation_id, owner), 404)
        # Simulate only a completed, schema-validated worker result for the
        # publish state-machine test; browser tests exercise actual generation.
        generation.status = 'completed'
        generation.answer = 'A synthetic accepted result [report-0]'
        generation.analysis_result = {'schema_version': 1}
        generation.actual_usd = 0
        await session.commit()
    action = RevisionAction(expected_version=updated['version'], revision=updated['revision'], definition_hash=updated['hash'], preview_id=preview['id'], approved=True)
    async with SessionLocal() as session:
        result = await service.action(session, lid, action, owner, 'publish')
        assert result['status'] == 'published'
    async with SessionLocal() as session:
        row = await service.revision(session, lid, result['revision'])
        row.definition = {**row.definition, 'name': 'Forbidden rewrite'}
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        else:
            raise AssertionError('Database allowed a published revision rewrite')
    # Nulling/deleting a conversation cannot retain the structured answer.
    async with SessionLocal() as session:
        record = await session.get(PreviewRun, uuid.UUID(preview['id']))
        conversation = await session.get(ChatConversation, record.conversation_id)
        await session.delete(conversation)
        await session.commit()
        generation = await session.get(ChatGeneration, record.generation_id)
        await session.refresh(generation)
        assert generation.conversation_id is None and generation.analysis_result is None
    async with SessionLocal() as session:
        policy = await session.get(LensPolicy, 1)
        policy.config = original_policy
        await session.commit()
        tables = (await session.execute(text("SELECT table_schema FROM information_schema.tables WHERE table_name LIKE 'analysis_lens%'"))).scalars().all()
        assert tables and set(tables) == {'market_intelligence'}
    print('Analysis lenses: real SQL, contextual selection, immutable revisions, audience, idempotency, changes and deletion passed.')


if __name__ == '__main__':
    asyncio.run(verify())
