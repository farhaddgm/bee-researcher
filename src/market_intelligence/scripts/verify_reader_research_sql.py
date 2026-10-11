"""Real SQL research ownership, revision races, keyset paging and context revocation."""
import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
import sys
import uuid
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from app import admin
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser, AssistantMember, Publication
from app.news_chat import api as chat_api, service as chat
from app.news_chat.models import ChatConversation, ChatGeneration
from app.news_chat.schemas import ResearchStart, Question
from app.reader_research import api, service
from app.reader_research.models import ResearchProfile, ResearchRecord
from app.reader_research.schemas import Profile, Record

cfg=get_settings()
if cfg.environment!='test' or cfg.postgres_db!='news_chat_test':raise RuntimeError('Isolated database required')


async def expect(code,call):
    try:await call
    except HTTPException as exc:assert exc.status_code==code,(exc.status_code,code)
    else:raise AssertionError('Expected access/validation rejection '+str(code))


async def run():
    aid=uuid.UUID('10000000-0000-4000-8000-000000000003')
    pids=[uuid.UUID('40000000-0000-4000-8000-00000000000'+str(n)) for n in range(1,4)]
    uid,peerid=uuid.uuid4(),uuid.uuid4();tokens=['synthetic-research-sql-'+str(v) for v in (uid,peerid)]
    users=[]
    async with SessionLocal() as s:
        for actor,token in zip((uid,peerid),tokens):
            user=AdminUser(id=actor,username='research-sql-'+actor.hex[:8],email=actor.hex+'@gmail.com',display_name='SQL synthetic reader',password_hash='synthetic-unused',active=True,role='viewer',preferences={'user_portal_access':{'enabled':True},'news_chat_enabled':True})
            s.add(user);await s.flush();users.append(user)
            s.add(AssistantMember(assistant_id=aid,user_id=actor,role='viewer'))
            s.add(AdminSession(user_id=actor,token_hash=hashlib.sha256(token.encode()).hexdigest(),portal='user',mfa_verified=True,created_at=chat.now(),expires_at=chat.now()+timedelta(minutes=30)))
        await s.commit()
    token,peer_token=tokens
    try:
        profile=await api.save_profile(aid,Profile(interests=['Battery'],business_context='SQL_SELECTED_BUSINESS'),token=token)
        assert profile['version']==1
        assert not (await api.profile(aid,token=peer_token))['business_context']
        race=await asyncio.gather(api.save_profile(aid,Profile(version=1,interests=['One']),token=token),api.save_profile(aid,Profile(version=1,interests=['Two']),token=token),return_exceptions=True)
        assert sum(isinstance(v,HTTPException) and v.status_code==409 for v in race)==1
        assert (await api.profile(aid,token=token))['version']==2
        rid=uuid.uuid4();draft=Record(id=rid,kind='action',title='Confirm an evidence review',publication_ids=pids[:2],attributes={'due_on':'2026-11-01','assignee':'Synthetic reviewer'})
        created=await api.create_record(aid,draft,token=token)
        replay=await api.create_record(aid,draft,token=token)
        assert created==replay
        await expect(409,api.create_record(aid,draft.model_copy(update={'body':'Different'}),token=token))
        await expect(404,api.update_record(aid,rid,draft.model_copy(update={'version':1}),token=peer_token))
        await expect(404,api.delete_record(aid,rid,version=1,token=peer_token))
        updated=await api.update_record(aid,rid,draft.model_copy(update={'version':1,'attributes':draft.attributes.model_copy(update={'status':'done'})}),token=token)
        assert updated['version']==2 and updated['attributes']['status']=='done'
        await expect(409,api.update_record(aid,rid,draft.model_copy(update={'version':1}),token=token))
        shared=await api.create_record(aid,Record(kind='shared',title='Explicit selected result',body='Only this text is shared',publication_ids=[pids[0]]),token=token)
        peers=await api.records(aid,kind='shared',token=peer_token)
        assert any(r['id']==shared['id'] and r['conversation_id'] is None and not r['owned'] for r in peers['records'])
        assert not (await api.records(aid,kind='action',token=peer_token))['records']
        async with SessionLocal() as s:
            fixed=chat.now();ids=sorted(uuid.uuid4() for _ in range(65))
            for id in ids:s.add(ResearchRecord(id=id,user_id=uid,assistant_id=aid,kind='decision',title='Same timestamp '+str(id),body='Synthetic decision',attributes={'status':'active'},publication_ids=[str(pids[0])],version=1,created_at=fixed,updated_at=fixed))
            await s.commit()
        seen=[];before=None
        while True:
            data=await api.records(aid,kind='decision',before=before,token=token)
            seen.extend(uuid.UUID(r['id']) for r in data['records'])
            if not data['older_before']:break
            before=uuid.UUID(data['older_before'])
        assert seen==list(reversed(ids)),'Equal-date research pages lost or repeated records'
        # Independent checks before and during provider work; losing membership
        # or any selected report/memory cancels the new research request.
        async with SessionLocal() as s:
            pub=await s.get(Publication,pids[0]);original=pub.message_text
            model=(await chat.policy(s)).models[0]
            cid=uuid.uuid4();context=await service.selected_context(s,pub,users[0],pids[:2],[],False)
            assert 'INTERNAL' not in str(context) and 'SQL_SELECTED_BUSINESS' not in str(context)
            c=ChatConversation(id=cid,user_id=uid,assistant_id=aid,publication_id=pids[0],context=context,provider=model.provider,created_at=chat.now(),saved_at=chat.now());s.add(c);await s.flush()
            g=ChatGeneration(conversation_id=cid,user_id=uid,assistant_id=aid,idempotency_key='synthetic-context-'+str(cid),session_hash='',question='Saved battery question',answer='Saved result [report-0]',language='en',model=model.model_dump(mode='json'),citations=[],status='completed',cancel_requested=False,reserved_usd=0,actual_usd=0,usage={},created_at=chat.now(),finished_at=chat.now(),deadline=chat.now());s.add(g);await s.commit()
        filtered=await chat_api.project_memory(aid,q='Battery research',model=model.key,token=token)
        assert any(m['id']==str(cid) for m in filtered['memories']), 'Headline + model memory filter failed'
        await expect(404,chat_api.memory_reference(cid,token=peer_token))
        async with SessionLocal() as s:
            pub=await s.get(Publication,pids[0]);current=await s.get(ChatConversation,cid)
            selected=await service.selected_context(s,pub,users[0],[pids[0]],[cid],False)
            assert any(seg.get('memory_id')==str(cid) for seg in selected['segments'])
            await s.execute(update(Publication).where(Publication.id==pids[1]).values(status='archived'));await s.commit()
        assert not (await api.records(aid,kind='action',token=token))['records'],'Withdrawn report still exposed dependent record'
        await expect(404,chat_api.messages(cid,token=token))
        async with SessionLocal() as s:
            await s.execute(update(Publication).where(Publication.id==pids[1]).values(status='published'));await s.execute(update(Publication).where(Publication.id==pids[0]).values(message_text=original+'\nUpdated'));await s.commit()
            c=await s.get(ChatConversation,cid);pub=await s.get(Publication,pids[0]);await expect(409,service.validate_context(s,c,pub,users[0]))
            await s.execute(update(Publication).where(Publication.id==pids[0]).values(message_text=original));await s.commit()
        await chat_api.unsave_memory(cid,token=token)
        async with SessionLocal() as s:
            pub=await s.get(Publication,pids[0]);await expect(404,service.selected_context(s,pub,users[0],[pids[0]],[cid],False))
        # Ledger feedback survives transcript deletion, while other readers
        # still cannot alter it or the budget.
        await chat_api.remove(cid,token=token)
        from app.news_chat.schemas import Feedback
        await api.usage_feedback(aid,g.id,Feedback(value=1),token=token)
        await expect(404,api.usage_feedback(aid,g.id,Feedback(value=-1),token=peer_token))
        await expect(409,api.delete_record(aid,rid,version=1,token=token))
        await api.delete_record(aid,rid,version=2,token=token)
        async with SessionLocal() as s:
            await s.execute(delete(AssistantMember).where(AssistantMember.user_id==peerid));await s.commit()
        await expect(404,api.records(aid,kind='shared',token=peer_token))
        print('Research SQL acceptance passed: profile race, explicit confirmation, private/shared ACL, 65 timestamp ties, model/topic memory filters, withdrawal, context changes, unsaving and ledger-only feedback.')
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(AdminUser).where(AdminUser.id.in_([uid,peerid])));await s.commit()
        await engine.dispose()

if __name__=='__main__':asyncio.run(run())
