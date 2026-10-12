"""Real SQL: quotas, boundary carry, legacy ledger, races, erasure and ACL."""
import asyncio
import hashlib
from datetime import timedelta, timezone
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import delete, func, select, text
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.answer_length import AnswerLength
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser, AssistantMember, Publication
from app.news_chat import api as chat_api, service as chat
from app.news_chat.models import ChatConversation, ChatGeneration
from app.news_chat.schemas import Question, ResearchStart
from app.news_chat.context import prompt
from app.token_quotas import api, service
from app.token_quotas.models import TokenLimit
from app.token_quotas.schemas import Limits, SaveLimit

if get_settings().environment != 'test' or get_settings().postgres_db != 'news_chat_test':
    raise RuntimeError('Isolated synthetic database required')
REQUEST = Request({'type':'http','path':'/user/api/token-quotas/owner','headers':[],'scheme':'http','server':('127.0.0.1',8010)})


async def refused(code, call):
    try:
        await call
    except HTTPException as e:
        assert e.status_code == code, (e.status_code, code, e.detail)
        return e
    raise AssertionError('Expected refusal '+str(code))


async def main():
    aid=uuid.UUID('10000000-0000-4000-8000-000000000003')
    other=uuid.UUID('10000000-0000-4000-8000-000000000001')
    uid,peerid=uuid.uuid4(),uuid.uuid4()
    tokens={u:'quota-fixture-'+str(u) for u in (uid,peerid)}
    owner_token='quota-owner-fixture-'+str(uuid.uuid4())
    at=chat.now().astimezone(timezone.utc).replace(hour=12,minute=0,second=0,microsecond=0)
    async with SessionLocal() as s:
        owner=await s.scalar(select(AdminUser).where(AdminUser.email==chat.admin.owner_email()))
        assert owner is not None
        s.add(AdminSession(user_id=owner.id,token_hash=hashlib.sha256(owner_token.encode()).hexdigest(),portal='user',created_at=chat.now(),expires_at=chat.now()+timedelta(hours=1)))
        pubs={a:await s.scalar(select(Publication).where(Publication.assistant_id==a,Publication.status=='published').limit(1)) for a in (aid,other)}
        model=(await chat.policy(s)).models[0].model_dump(mode='json')
        for actor in (uid,peerid):
            s.add(AdminUser(id=actor,username='quota-'+actor.hex,role='viewer',active=True,password_hash='synthetic-unused',preferences={'user_portal_access':{'enabled':True},'news_chat_enabled':True}))
            await s.flush()
            for project in (aid,other):s.add(AssistantMember(user_id=actor,assistant_id=project,role='viewer'))
            s.add(AdminSession(user_id=actor,token_hash=hashlib.sha256(tokens[actor].encode()).hexdigest(),portal='user',created_at=chat.now(),expires_at=chat.now()+timedelta(hours=1)))
        await s.commit()
    async def save(a=None,u=None,limits=None,inherit=False,version=None):
        async with SessionLocal() as s:
            row=await s.get(TokenLimit,service.key(a,u))
            v=row.version if row else 0
        return await api.save(SaveLimit(assistant_id=a,user_id=u,limits=limits or Limits(),inherit=inherit,version=v if version is None else version),REQUEST,None,owner_token)
    async def add(actor,project,when,inp=None,out=None,status='completed',reserved=200,usage=None):
        cid,gid=uuid.uuid4(),uuid.uuid4()
        async with SessionLocal() as s:
            s.add(ChatConversation(id=cid,user_id=actor,assistant_id=project,publication_id=pubs[project].id,context={},provider='openai',created_at=when))
            await s.flush()
            s.add(ChatGeneration(id=gid,conversation_id=cid,user_id=actor,assistant_id=project,idempotency_key=str(gid),session_hash='',question='PRIVATE_QUOTA_CANARY',answer='PRIVATE_ANSWER_CANARY',language='en',model=model,citations=[],status=status,cancel_requested=False,reserved_usd=0,actual_usd=0 if inp is not None else None,reserved_tokens=reserved,input_tokens=inp,output_tokens=out,usage=usage or {},created_at=when,deadline=chat.now()+timedelta(minutes=1)))
            await s.commit()
        return cid,gid
    try:
        old_cid,old_gid=await add(uid,aid,at-timedelta(hours=25),10,10)
        _,recent_gid=await add(uid,aid,at-timedelta(hours=1),10,20)
        await add(uid,other,at,30,40)
        await add(peerid,aid,at,40,40)
        pending_cid,pending_gid=await add(uid,aid,at-timedelta(days=40),status='running',reserved=500)
        async with SessionLocal() as s:
            r=await service.report(s,aid,uid,at)
            windows={w['window']:w for w in r['windows']}
            assert windows['six_hours']['actual_tokens']==30
            assert windows['six_hours']['reserved_tokens']==500
            assert windows['total']['charged_tokens']==550
            assert windows['daily']['actual_tokens']==30
            assert windows['monthly']['actual_tokens']==(50 if at-timedelta(hours=25)>=service.boundaries(at)['monthly'][0] else 30)
            assert windows['monthly']['reserved_tokens']==500 and windows['daily']['reserved_tokens']==500
            assert windows['total']['input_tokens']==20 and windows['total']['output_tokens']==30
            pending=await s.get(ChatGeneration,pending_gid);pending.status='unknown';await s.commit()
            assert (await service.counters(s,aid,uid,at))['six_hours']['reserved_tokens']==0
            assert (await service.counters(s,aid,uid,at))['total']['reserved_tokens']==500
            pending.input_tokens,pending.output_tokens=0,0;pending.status='stopped';await s.commit()
        await save(limits=Limits(daily=9000))
        await save(aid,limits=Limits(daily=8000))
        user_policy=await save(aid,uid,Limits(daily=7000))
        async with SessionLocal() as s:
            assert (await service.effective(s,aid,uid))[0].daily==7000
            assert (await service.effective(s,aid,peerid))[0].daily==8000
            assert (await service.effective(s,other,uid))[0].daily==9000
        raced=await asyncio.gather(*(save(aid,uid,Limits(daily=n),version=user_policy['version']) for n in (7100,7200)),return_exceptions=True)
        assert sum(isinstance(v,HTTPException) and v.status_code==409 for v in raced)==1
        assert sum(isinstance(v,dict) for v in raced)==1
        await save(aid,uid,inherit=True)
        async with SessionLocal() as s:assert (await service.effective(s,aid,uid))[0].daily==8000
        await save(aid,inherit=True)
        async with SessionLocal() as s:assert (await service.effective(s,aid,uid))[0].daily==9000
        await save(aid,uid,Limits())
        async with SessionLocal() as s:assert (await service.effective(s,aid,uid))[0].daily is None
        # Ledger remains private, available when chat permission is disabled.
        async with SessionLocal() as s:
            actor=await s.get(AdminUser,uid);actor.preferences={'user_portal_access':{'enabled':True},'news_chat_enabled':False};await s.commit()
        report=await api.report(aid,None,tokens[uid]);assert 'PRIVATE_' not in str(report)
        await refused(404,api.report(aid,recent_gid,tokens[peerid]))
        await refused(403,api.catalog(REQUEST,None,None,tokens[uid]))
        async with SessionLocal() as s:
            actor=await s.get(AdminUser,uid);actor.preferences={'user_portal_access':{'enabled':True},'news_chat_enabled':True};await s.commit()
        for window in service.WINDOWS:
            await save(aid,uid,Limits(**{window:0}))
            started=await chat_api.start(pubs[aid].id,ResearchStart(model_key='openai:fixture-v1',source_ids=[pubs[aid].id]),tokens[uid])
            cid=uuid.UUID(started['id'])
            q=Question(question='A quota question',model_key='openai:fixture-v1',context_version=started['context']['version'],idempotency_key=str(uuid.uuid4()),language='en')
            e=await refused(429,chat.send(cid,q,actor,tokens[uid]))
            assert e.detail['code']=='token_quota_exhausted' and e.detail['window']==window
        await save(aid,uid,Limits(total=100000))
        started=await chat_api.start(pubs[aid].id,ResearchStart(model_key='openai:fixture-v1',source_ids=[pubs[aid].id]),tokens[uid]);cid=uuid.UUID(started['id'])
        q=Question(question='Admit exactly once',model_key='openai:fixture-v1',context_version=started['context']['version'],idempotency_key=str(uuid.uuid4()),language='en')
        async with SessionLocal() as s:
            c=await s.get(ChatConversation,cid)
            spec=(await chat.policy(s)).models[0]
            messages=prompt(c.context,q.question,q.language,[],None,spec.max_input_chars,q.intent,AnswerLength())
            bound=sum(len(m['content'].encode())+100 for m in messages)
            counts=(await service.counters(s,aid,uid,chat.now()))['total']
        await save(aid,uid,Limits(total=counts['actual_tokens']+counts['reserved_tokens']+bound+250))
        results=await asyncio.gather(chat.send(cid,q,actor,tokens[uid]),chat.send(cid,q,actor,tokens[uid]))
        assert results[0]['id']==results[1]['id']
        gid=uuid.UUID(results[0]['id'])
        async with SessionLocal() as s:
            g=await s.get(ChatGeneration,gid);assert g.reserved_tokens==g.usage['input_bound']+g.model['max_output_tokens'];assert g.model['max_output_tokens']==250
        async with SessionLocal() as s:
            g=await s.get(ChatGeneration,gid);g.cancel_requested=True;g.status='running';await s.commit()
        with patch.object(chat.providers,'stream') as upstream:
            await chat.generate(gid)
            upstream.assert_not_called()
        async with SessionLocal() as s:
            g=await s.get(ChatGeneration,gid);assert g.input_tokens==0 and g.output_tokens==0 and g.actual_usd==0
            c=await s.get(ChatConversation,cid);await chat.erase_conversation(s,c);await s.commit()
            g=await s.get(ChatGeneration,gid);assert g.input_tokens==0 and g.output_tokens==0
        # Cancellation before contacting the provider settles zero.
        async with SessionLocal() as s:
            await s.execute(delete(ChatConversation).where(ChatConversation.id==old_cid));await s.commit()
            g=await s.get(ChatGeneration,old_gid);assert g.conversation_id is None and g.input_tokens+g.output_tokens==20
        _,legacy=await add(uid,aid,at,reserved=0,usage={'input_tokens':123,'output_tokens':7})
        async with SessionLocal() as s:
            g=await s.get(ChatGeneration,legacy);assert (g.input_tokens,g.output_tokens)==(123,7)
            await s.execute(delete(AssistantMember).where(AssistantMember.user_id==uid,AssistantMember.assistant_id==aid));await s.commit()
        await refused(404,api.report(aid,None,tokens[uid]))
        async with SessionLocal() as s:
            assert await s.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_indexes WHERE schemaname='market_intelligence' AND indexname='ix_reader_token_usage')"))
            assert await s.scalar(select(func.count()).select_from(ChatGeneration).where(ChatGeneration.user_id==uid,ChatGeneration.idempotency_key==q.idempotency_key))==1
        print('Token quota SQL passed: four windows, inheritance, optimistic race, idempotency, reservations, erasure, private reports and revocation.')
    finally:
        await save(limits=Limits())
        await save(aid,inherit=True)
        async with SessionLocal() as s:
            await s.execute(delete(AdminUser).where(AdminUser.id.in_([uid,peerid])))
            await s.execute(delete(AdminSession).where(AdminSession.token_hash==hashlib.sha256(owner_token.encode()).hexdigest()))
            await s.commit()
        await engine.dispose()


if __name__=='__main__':asyncio.run(main())
