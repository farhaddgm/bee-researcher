"""SQL gates run after synthetic browser tests, against a fresh isolated schema."""
import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from sqlalchemy import func, select, text
from app.config import get_settings
from app import admin
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser
from app.news_chat import api, service as svc
from app.news_chat.context import context_for
from app.news_chat.models import ChatConversation,ChatGeneration
from app.news_chat.schemas import Question, Start

settings=get_settings()
if settings.environment!='test' or settings.postgres_db!='news_chat_test':raise RuntimeError('Synthetic database required')


async def verify():
    uid=uuid.UUID('30000000-0000-4000-8000-000000000004');pid=uuid.UUID('20000000-0000-4000-8000-000000000001');aid=uuid.UUID('10000000-0000-4000-8000-000000000001')
    token='synthetic-sql-session';token_hash=hashlib.sha256(token.encode()).hexdigest()
    async with SessionLocal() as s:
        user=await s.get(AdminUser,uid);user.preferences={**user.preferences,'news_chat_enabled':True}
        session=AdminSession(user_id=uid,token_hash=token_hash,portal='user',expires_at=svc.now()+timedelta(minutes=30),mfa_verified=True,created_at=svc.now())
        s.add(session)
        c=ChatConversation(user_id=uid,assistant_id=aid,publication_id=pid,provider='openai',context=context_for((await svc.publication(s,pid,user)).message_text,None));s.add(c);await s.commit();cid=c.id;version=c.context['version']
    q=Question(question='Deadline check',model_key='openai:fixture-v1',language='en',context_version=version,idempotency_key='sql-session-expiry-fixture')
    g=await svc.send(cid,q,user,token)
    async with SessionLocal() as s:
        row=await s.get(ChatGeneration,uuid.UUID(g['id']))
        assert row.deadline<=session.expires_at
        assert row.deadline<=admin._reader_nightly_expiry(session.created_at)
        row.deadline=svc.now()-timedelta(seconds=1);await s.commit()
    try:await svc.live(uuid.UUID(g['id']))
    except HTTPException as e:assert e.status_code==401
    else:raise AssertionError('Expired job stayed authorized')
    # Database cascade must delete conversation text immediately, while keeping spend.
    async with SessionLocal() as s:
        await s.delete(await s.get(ChatConversation,cid));await s.commit()
        row=await s.get(ChatGeneration,uuid.UUID(g['id']));await s.refresh(row)
        assert row.conversation_id is None and row.question=='' and row.answer=='' and row.citations==[]
        assert row.reserved_usd>0 and row.cancel_requested
        trigger=await s.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname='clear_deleted_news_chat'"));assert trigger==1
    # New schema is closed under this project; no cross-service tables were touched.
    async with engine.connect() as c:
        columns=(await c.execute(text("SELECT table_schema FROM information_schema.tables WHERE table_name LIKE 'news_chat_%'"))).scalars().all()
        assert columns and set(columns)=={'market_intelligence'}
    # Retention also covers orphaned rows and does not forgive charged work.
    async with SessionLocal() as s:
        row=await s.get(ChatGeneration,uuid.UUID(g['id']));row.created_at=svc.now()-timedelta(days=100);row.question='Synthetic old orphan';row.answer='Synthetic private answer';row.session_hash='';row.status='completed';await s.commit()
    await svc.maintenance_once()
    async with SessionLocal() as s:
        row=await s.get(ChatGeneration,uuid.UUID(g['id']));assert row.question==row.answer=='' and row.citations==[] and row.reserved_usd>0
    # Sixty-five rows with exactly the same timestamp must appear once each,
    # including the last page; an exactly-full page must have no phantom cursor.
    async with SessionLocal() as s:
        user=await s.get(AdminUser,uid)
        c=ChatConversation(user_id=uid,assistant_id=aid,publication_id=pid,provider='openai',context=context_for((await svc.publication(s,pid,user)).message_text,None));s.add(c);await s.flush();history_cid=c.id
        model=(await svc.policy(s)).models[0].model_dump(mode='json');stamp=svc.now()-timedelta(days=2);ids=[uuid.uuid4() for _ in range(65)]
        for n,gid in enumerate(ids):
            s.add(ChatGeneration(id=gid,conversation_id=c.id,user_id=uid,assistant_id=aid,idempotency_key=f'sql-pagination-fixture-{n:03}',session_hash='',question=f'Old question {n}',answer=f'Old answer {n}',language='en',model=model,citations=[],status='completed',cancel_requested=False,reserved_usd=0,actual_usd=0,usage={},deadline=stamp,created_at=stamp,finished_at=stamp))
        await s.commit()
    seen=[];before=None;pages=[]
    while True:
        page=await api.messages(history_cid,before=before,token=token);rows=[uuid.UUID(r['id']) for r in page['messages']];pages.append(rows);seen=rows+seen
        if not page['older_before']:break
        before=uuid.UUID(page['older_before'])
        assert len(pages)<=3,'History cursor looped'
    assert [len(page) for page in pages]==[30,30,5]
    assert seen==sorted(ids) and len(set(seen))==65,'Timestamp ties lost or duplicated messages'
    exactly_full=await api.messages(history_cid,before=sorted(ids)[30],token=token)
    assert len(exactly_full['messages'])==30 and exactly_full['older_before'] is None
    try:await api.messages(history_cid,before=uuid.uuid4(),token=token)
    except HTTPException as e:assert e.status_code==404
    else:raise AssertionError('Invented history cursor accepted')
    # Two simultaneous tabs cannot both allocate the final slot. Existing
    # conversation IDs are not loaded just to calculate the cap.
    async with SessionLocal() as s:
        current=await s.scalar(select(func.count()).select_from(ChatConversation).where(ChatConversation.user_id==uid,ChatConversation.deleted_at.is_(None)))
        for _ in range(499-current):
            s.add(ChatConversation(user_id=uid,assistant_id=aid,publication_id=pid,provider='openai',context=c.context))
        await s.commit()
    result=await asyncio.gather(api.start(pid,Start(model_key='openai:fixture-v1'),token=token),api.start(pid,Start(model_key='openai:fixture-v1'),token=token),return_exceptions=True)
    assert sum(isinstance(r,dict) for r in result)==1
    assert sum(isinstance(r,HTTPException) and r.status_code==429 for r in result)==1
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(ChatConversation).where(ChatConversation.user_id==uid,ChatConversation.deleted_at.is_(None)))==500
    accessible=await api.conversations(pid,token=token)
    assert len(accessible['conversations'])==500 and history_cid in {uuid.UUID(c['id']) for c in accessible['conversations']}
    print('Chat SQL passed: real session/02:00 deadline, expiry refusal, cascade privacy erase, orphan retention, retained reservation, schema isolation, 65 equal-timestamp messages without skips/duplicates, exact-full final cursor, concurrent conversation cap and all 500 conversations accessible.')


async def main():
    try:await verify()
    finally:await engine.dispose()


if __name__=='__main__':asyncio.run(main())
