"""Real database: source evidence, late saves, racing human replies and revocation."""
import asyncio
import hashlib
from dataclasses import replace
from decimal import Decimal
from datetime import timedelta
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser, AssistantMember, Publication
from app.news_chat import api as chat_api, service as chat
from app.news_chat.models import ChatConversation, ChatGeneration
from app.news_chat.schemas import ResearchStart
from app.reader_research import api as research
from app.reader_research.schemas import Record
from app.reader_tools import api, corrections as changes
from app.reader_tools.models import ExpertReply, ExpertRequest, NewsMonitor, NewsRevision, NewsWatch
from app.reader_tools.schemas import ExpertCreate, Reply, Watch
from app.article_extraction import ArticleDocument

cfg = get_settings()
if cfg.environment != 'test' or cfg.postgres_db != 'news_chat_test':
    raise RuntimeError('Isolated synthetic database required')


async def expect(code, call):
    try:
        await call
    except HTTPException as exc:
        assert exc.status_code == code, (exc.status_code, code)
    else:
        raise AssertionError('Expected refusal '+str(code))


async def main():
    aid=uuid.UUID('10000000-0000-4000-8000-000000000003')
    uid,peerid,pid=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
    tokens=['synthetic-reader-tools-'+str(v) for v in (uid,peerid)]
    async with SessionLocal() as s:
        anchor=await s.scalar(select(Publication).where(Publication.assistant_id==aid).limit(1))
        pub=Publication(id=pid,assistant_id=aid,analysis_id=anchor.analysis_id,idempotency_key=str(pid),status='published',
                        message_text='SQL report headline\nThe reported amount was ten.',published_at=chat.now())
        s.add(pub)
        for actor,token in zip((uid,peerid),tokens):
            s.add(AdminUser(id=actor,username='tools-sql-'+actor.hex,role='viewer',active=True,password_hash='synthetic-unused',
                preferences={'user_portal_access':{'enabled':True},'news_chat_enabled':True}))
            await s.flush()
            s.add(AssistantMember(user_id=actor,assistant_id=aid,role='viewer'))
            s.add(AdminSession(user_id=actor,token_hash=hashlib.sha256(token.encode()).hexdigest(),portal='user',
                created_at=chat.now(),expires_at=chat.now()+timedelta(hours=1)))
        await s.commit()
    payload=ExpertCreate(id=uuid.uuid4(),assignee_id=peerid,title='Evidence question',question='What independent evidence is available?',
                        excerpt='Selected excerpt only',publication_ids=[pid])
    first=await api.create_request(aid,payload,tokens[0]);again=await api.create_request(aid,payload,tokens[0]);assert first['id']==again['id']
    await expect(409,api.create_request(aid,payload.model_copy(update={'question':'A different question'}),tokens[0]))
    rid=uuid.UUID(first['id'])
    duplicate=Reply(id=uuid.uuid4(),version=1,body='Human evidence response')
    answers=await asyncio.gather(api.reply(aid,rid,duplicate,tokens[1]),api.reply(aid,rid,duplicate,tokens[1]))
    assert answers[0]['id']==answers[1]['id']
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(ExpertReply).where(ExpertReply.request_id==rid))==1
    second=await api.create_request(aid,payload.model_copy(update={'id':uuid.uuid4()}),tokens[0]);rid2=uuid.UUID(second['id'])
    raced=await asyncio.gather(*(api.reply(aid,rid2,Reply(id=uuid.uuid4(),version=1,body=value),tokens[1]) for value in ['Reply A','Reply B']),return_exceptions=True)
    assert sum(isinstance(v,HTTPException) and v.status_code==409 for v in raced)==1
    assert sum(isinstance(v,dict) for v in raced)==1

    started=await chat_api.start(pid,ResearchStart(model_key='openai:fixture-v1',source_ids=[pid]),tokens[0])
    cid=uuid.UUID(started['id']);gid=uuid.uuid4()
    async with SessionLocal() as s:
        model=(await chat.policy(s)).models[0]
        s.add(ChatGeneration(id=gid,conversation_id=cid,user_id=uid,assistant_id=aid,idempotency_key=str(gid),
            session_hash=hashlib.sha256(tokens[0].encode()).hexdigest(),question='Private analysis',answer='An analysis of the old amount.',
            language='en',model=model.model_dump(mode='json'),citations=[],status='completed',cancel_requested=False,
            reserved_usd=0,actual_usd=Decimal('0.001'),usage={'analysis_hash':'PRIVATE_HASH_CANARY','target_generation_id':str(uuid.uuid4())},
            created_at=chat.now(),deadline=chat.now()+timedelta(minutes=1),finished_at=chat.now()))
        await s.commit()
    document=ArticleDocument(url='https://synthetic.invalid/source',canonical_url='https://synthetic.invalid/source',
        title='Correction: synthetic study',author=None,published_at=None,language='en',text='A public correction states 25.',
        raw_html=None,extraction_status='complete',extraction_method='fixture',quality_score=1,content_hash=None,provenance={})
    class Fetcher:
        def __init__(self, settings):pass
        async def fetch(self, **kwargs):return document
    with patch.object(changes,'ArticleFetcher',Fetcher):
        assert (await changes.recheck(pid,manual=True))['version']==1
    late=await research.create_record(aid,Record(kind='meeting',title='Late-saved analysis',body='Based on the old amount.',
        publication_ids=[pid],generation_id=gid),tokens[0])
    await chat_api.save_memory(cid,tokens[0])
    review=(await api.review_needed(aid,token=tokens[0]))['items']
    assert any(v['id']==late['id'] for v in review)
    assert any(v['id']==str(cid) for v in review)
    assert (await api.review_needed(aid,token=tokens[1]))['items']==[]
    # Failure/incomplete fetches preserve evidence and are never retractions.
    async with SessionLocal() as s:
        monitor=await s.get(NewsMonitor,pid);monitor.checked_at=chat.now()-timedelta(minutes=6);await s.commit()
    document=replace(document,extraction_status='partial',text='A login page.')
    with patch.object(changes,'ArticleFetcher',Fetcher):
        result=await changes.recheck(pid,manual=True);assert result['status']=='incomplete' and result['version']==1
    async with SessionLocal() as s:
        monitor=await s.get(NewsMonitor,pid);monitor.checked_at=chat.now()-timedelta(minutes=6);await s.commit()
    document=replace(document,extraction_status='complete',text='A public correction states 25.')
    with patch.object(changes,'ArticleFetcher',Fetcher):
        assert (await changes.recheck(pid,manual=True))['version']==1,'Equal source created a duplicate revision'
    # A report edit is detected separately and does not acknowledge source edits.
    async with SessionLocal() as s:
        pub=await s.get(Publication,pid);pub.message_text='SQL report headline\nThe report spelling changed.';await s.commit()
    await api.watch(aid,pid,Watch(enabled=True),tokens[0])
    async with SessionLocal() as s:
        rows=list((await s.scalars(select(NewsRevision).where(NewsRevision.publication_id==pid).order_by(NewsRevision.version))).all())
        assert [r.channel for r in rows]==['source','report']
        assert all('PRIVATE_HASH_CANARY' not in r.before_text+r.after_text for r in rows)
        for table in ['reader_news_revisions','reader_expert_replies']:
            assert await s.scalar(text("SELECT has_table_privilege('startup_fixture',:table,'SELECT')"),{'table':'market_intelligence.'+table})
            assert not await s.scalar(text("SELECT has_table_privilege('startup_fixture',:table,'UPDATE')"),{'table':'market_intelligence.'+table})
    # Attaching legacy work is idempotent and preserves a deliberate opt-out.
    from app.reader_tools.backfill import backfill
    await api.watch(aid,pid,Watch(enabled=False),tokens[0])
    await backfill()
    async with SessionLocal() as s:
        before=await s.scalar(select(func.count()).select_from(NewsWatch))
        assert (await s.get(NewsWatch,(uid,pid))).enabled is False
    await backfill()
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(NewsWatch))==before
        assert (await s.get(NewsWatch,(uid,pid))).enabled is False
    # Revoking project membership prevents receiving or posting further replies.
    async with SessionLocal() as s:
        await s.execute(delete(AssistantMember).where(AssistantMember.user_id==peerid,AssistantMember.assistant_id==aid));await s.commit()
    await expect(404,api.detail(aid,rid,token=tokens[1]))
    await expect(404,api.reply(aid,rid,Reply(id=uuid.uuid4(),version=2,body='After revocation'),tokens[1]))
    # Closing private analyses erases target/hash metadata while retaining spend.
    async with SessionLocal() as s:
        c=await s.get(ChatConversation,cid);c.saved_at=None;await chat.erase_conversation(s,c);await s.commit()
        row=await s.get(ChatGeneration,gid);assert not row.question and not row.answer
        assert 'analysis_hash' not in row.usage and 'target_generation_id' not in row.usage
        assert row.actual_usd>0
        # Source withdrawal hides human threads; physical deletion cascades evidence.
        pub=await s.get(Publication,pid);pub.status='archived';await s.commit()
    await expect(404,api.detail(aid,rid,token=tokens[0]))
    async with SessionLocal() as s:
        pub=await s.get(Publication,pid);await s.delete(pub);await s.commit()
        assert await s.get(NewsMonitor,pid) is None
        assert not await s.scalar(select(NewsRevision.id).where(NewsRevision.publication_id==pid))
        assert not await s.scalar(select(NewsWatch.publication_id).where(NewsWatch.publication_id==pid))
    print('Reader tools SQL passed: atomic/idempotent replies, stale versions, late-save evidence, source/report distinction, incomplete/equal fetches, append-only grants, revocation, source withdrawal, cascade erase and preserved spend.')


if __name__=='__main__':
    async def checked():
        try:await main()
        finally:await engine.dispose()
    asyncio.run(checked())
