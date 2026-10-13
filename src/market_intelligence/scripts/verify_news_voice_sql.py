"""Real PostgreSQL voice snapshots, ownership, budget races and deletion.

All media and accounts are synthetic; never accepts a production database.
"""
import asyncio
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException,Request
from sqlalchemy import delete,select
from unittest.mock import patch
from app import admin
from app.config import get_settings
from app.database import SessionLocal,engine
from app.models import AdminSession,AdminUser,AssistantMember,Publication
from app.news_chat import api as chat_api,providers as llm,service as chat
from app.news_chat.models import ChatConversation,ChatGeneration,ChatPolicy
from app.news_chat.schemas import ResearchStart,Question
from app.news_voice import api,service as voice,storage
from app.news_voice.models import VoiceAudio,VoiceDeletion,VoiceSaveJob,VoiceSession,VoiceUsage
from app.news_voice.schemas import Bookmark,Brief,Playback,Save,Start,TTS
from scripts import news_voice_fixture as fixture
from scripts.news_chat_fixture import fake_stream

cfg=get_settings()
if cfg.environment!='test' or cfg.postgres_db!='news_chat_test':raise RuntimeError('Isolated test database required')


async def reject(code,operation):
    try:await operation
    except HTTPException as exc:assert exc.status_code==code,(exc.status_code,exc.detail)
    else:raise AssertionError('Expected rejection '+str(code))


def request(path,headers=()):
    return Request({'type':'http','method':'GET','path':path,'scheme':'http','server':('fixture',80),'headers':list(headers),'query_string':b''})


async def run():
    fixture.configure();await fixture.seed()
    uid,peer_id=uuid.uuid4(),uuid.uuid4()
    aid=uuid.UUID('10000000-0000-4000-8000-000000000001');pid=uuid.UUID('20000000-0000-4000-8000-000000000001')
    token,peer_token=['synthetic-voice-sql-'+str(v) for v in (uid,peer_id)]
    async with SessionLocal() as s:
        original=(await s.get(ChatPolicy,1)).config.copy()
        for id,key in [(uid,token),(peer_id,peer_token)]:
            u=AdminUser(id=id,username='voice-sql-'+id.hex[:8],email=id.hex+'@gmail.com',role='viewer',display_name='Voice SQL fixture',
                active=True,password_hash='unused-synthetic',preferences={'news_chat_enabled':True,'user_portal_access':{'enabled':True}})
            s.add(u);await s.flush()
            s.add(AssistantMember(assistant_id=aid,user_id=id,role='viewer'))
            s.add(AdminSession(user_id=id,token_hash=voice.hash_text(key),portal='user',mfa_verified=True,
                created_at=chat.now(),expires_at=chat.now()+timedelta(minutes=30)))
        await s.commit()
    user=await admin.current_reader(token,touch=False)
    try:
        c=await chat_api.start(pid,ResearchStart(model_key='openai:fixture-v1'),token=token);cid=uuid.UUID(c['id'])
        start=Start(idempotency_key=uuid.uuid4().hex,language='fa',transfer_consent=True,retain_user_audio_for_save=True)
        session=await voice.create_session(cid,start,user,token)
        retry=await voice.create_session(cid,start,user,token);assert retry['id']==session['id'] and retry['ticket']!=session['ticket']
        await reject(409,voice.create_session(cid,start.model_copy(update={'language':'en'}),user,token))
        sid=uuid.UUID(session['id'])
        async with SessionLocal() as s:
            row=await s.get(VoiceSession,sid);row.status='running'
            u=await s.get(VoiceUsage,row.usage_id);u.status='running';await s.commit()
        raw_input=b'\x00\x20'*16000
        await voice.finish_session(sid,raw_input,'Original recognized question',1,True,True)
        q=Question(model_key='openai:fixture-v1',question='Edited submitted question',language='fa',
            context_version=c['context']['version'],voice_session_ids=[sid],idempotency_key=uuid.uuid4().hex)
        generation=await chat.send(cid,q,user,token);gid=uuid.UUID(generation['id'])
        assert (await chat.send(cid,q,user,token))['id']==generation['id']
        with patch.object(llm,'stream',fake_stream):await chat.generate(gid)
        async with SessionLocal() as s:
            g=await s.get(ChatGeneration,gid);assert g.status=='completed',g.status
        tts=TTS(idempotency_key=uuid.uuid4().hex,voice_key='eleven_v3:syntheticvoice001',transfer_consent=True,input_session_ids=[sid])
        a=await voice.request_tts(gid,tts,user,token);asset_id=uuid.UUID(a['id'])
        assert a['id']==(await voice.request_tts(gid,tts,user,token))['id']
        async with SessionLocal() as s:
            row=await s.get(VoiceAudio,asset_id);row.status='running';await s.commit()
        await voice.generate(asset_id)
        async with SessionLocal() as s:
            row=await voice.authorized_audio(s,asset_id,user);assert row.status=='ready',row.metadata_json
            assert storage.pcm(storage.Store().read(row))==fixture.PCM
            peer=await s.get(AdminUser,peer_id);owner=await s.scalar(select(AdminUser).where(AdminUser.username=='chat-owner'))
            await reject(404,voice.authorized_audio(s,asset_id,peer));await reject(404,voice.authorized_audio(s,asset_id,owner))
            assert row.metadata_json['timing'] and row.metadata_json['timing_text']==row.metadata_json['spoken_text']
        assert (await voice.request_tts(gid,tts.model_copy(update={'idempotency_key':uuid.uuid4().hex}),user,token))['id']==a['id']
        payload=Save(idempotency_key=uuid.uuid4().hex,title='Private genuine voice dialogue',scope='dialogue',
            selections=[{'asset_id':asset_id}],retain_conversation=True)
        jobs=await asyncio.gather(voice.request_save(cid,payload,user),voice.request_save(cid,payload,user))
        assert jobs[0]['id']==jobs[1]['id'];jid=uuid.UUID(jobs[0]['id'])
        await reject(409,voice.request_save(cid,payload.model_copy(update={'title':'Different'}),user))
        # Accepted save survives window close until its bounded worker lease.
        async with SessionLocal() as s:await chat.close_window(s,cid,pid,user)
        async with SessionLocal() as s:
            job=await s.get(VoiceSaveJob,jid);job.status='running';await s.commit()
        await voice.finalize_save(jid)
        async with SessionLocal() as s:
            job=await s.get(VoiceSaveJob,jid);assert job.status=='completed',job.error_code
            saved_id=job.asset_id;a=await voice.authorized_audio(s,saved_id,user)
            assert storage.pcm(storage.Store().read(a))==raw_input+fixture.PCM
            original_wav=storage.Store().read(a);assert a.saved_at and a.metadata_json['complete']
            assert (await s.get(ChatConversation,cid)).saved_at
        manifest=await api.manifest(saved_id,token=token)
        assert [r['speaker'] for r in manifest['segments']]==['user','ai']
        assert manifest['segments'][0]['recognized_text']=='Original recognized question'
        assert manifest['segments'][0]['submitted_question']=='Edited submitted question'
        before_count=None
        async with SessionLocal() as s:
            usages=list((await s.scalars(select(VoiceUsage).where(VoiceUsage.user_id==uid))).all());before_count=len(usages)
        download=await api.content(saved_id,request('/user/api/voice-audio/'+str(saved_id)+'/download'),token=token)
        assert download.body==original_wav and 'attachment' in download.headers['content-disposition']
        partial=await api.content(saved_id,request('/content',[(b'range',b'bytes=0-43')]),token=token)
        assert partial.status_code==206 and partial.body==original_wav[:44]
        await reject(416,api.content(saved_id,request('/content',[(b'range',b'bytes=999999999-')]),token=token))
        await reject(404,api.content(saved_id,request('/content'),token=peer_token))
        await api.playback(asset_id,Playback(played_seconds=2,played_ranges=[(0,.5),(1,2)],interrupted=True),token=token)
        mark=await api.bookmark(saved_id,Bookmark(version=0,seconds=1,label='Review this evidence'),token=token)
        assert mark['version']==1;await reject(409,api.bookmark(saved_id,Bookmark(version=0,seconds=1,label='Lost update'),token=token))
        await reject(409,chat_api.unsave_memory(cid,remove_audio=False,token=token))
        async with SessionLocal() as s:
            assert len(list((await s.scalars(select(VoiceUsage).where(VoiceUsage.user_id==uid))).all()))==before_count
            row=await s.get(VoiceAudio,asset_id);assert row.metadata_json['played_ranges']==[[0,.5],[1,2]]
        # Clip is the original PCM slice, not another provider call.
        clip=payload.model_copy(update={'idempotency_key':uuid.uuid4().hex,'scope':'ai','title':'One second clip',
            'selections':Save.model_validate({**payload.model_dump(mode='json'),'selections':[{'asset_id':str(asset_id),'start_seconds':.5,'end_seconds':1.5}]}).selections})
        jobdata=await voice.request_save(cid,clip,user)
        async with SessionLocal() as s:
            j=await s.get(VoiceSaveJob,uuid.UUID(jobdata['id']));j.status='running';await s.commit()
        await voice.finalize_save(uuid.UUID(jobdata['id']))
        async with SessionLocal() as s:
            j=await s.get(VoiceSaveJob,uuid.UUID(jobdata['id']));assert j.status=='completed',j.error_code
            clipped=await s.get(VoiceAudio,j.asset_id);assert storage.pcm(storage.Store().read(clipped))==fixture.PCM[16000:48000]
        # Audio-only delete immediately denies URLs and leaves saved text intact.
        await api.remove(saved_id,token=token)
        async with SessionLocal() as s:
            await reject(404,voice.authorized_audio(s,saved_id,user));assert (await s.get(ChatConversation,cid)).saved_at
            deleted=await s.get(VoiceAudio,saved_id);object_key=deleted.object_key
            assert await s.scalar(select(VoiceDeletion.id).where(VoiceDeletion.object_key==object_key))
        await voice.maintenance_once();assert not storage.Store().path(object_key).exists()
        # Parent cascade retains a standalone cleanup job and charge ledger.
        async with SessionLocal() as s:
            a=await s.get(VoiceAudio,clipped.id);object_key=a.object_key
            await s.execute(delete(ChatConversation).where(ChatConversation.id==cid));await s.commit()
        async with SessionLocal() as s:
            assert await s.scalar(select(VoiceDeletion.id).where(VoiceDeletion.object_key==object_key))
            assert await s.scalar(select(VoiceUsage.id).where(VoiceUsage.user_id==uid,VoiceUsage.conversation_id.is_(None)))
        await voice.maintenance_once();assert not storage.Store().path(object_key).exists()
        # Run the real LLM and voice producers concurrently. The first PCM
        # must exist while the canonical LLM row is still running.
        from app.news_voice import preview
        for remove_parent in (False,True):
            c=await chat_api.start(pid,ResearchStart(model_key='openai:fixture-v1'),token=token)
            progressive_cid=uuid.UUID(c['id'])
            generation=await chat.send(progressive_cid,Question(model_key='openai:fixture-v1',
                question='Progressive synthetic speech',context_version=c['context']['version'],
                idempotency_key=uuid.uuid4().hex),user,token)
            progressive_gid=uuid.UUID(generation['id'])
            asset=await voice.request_tts(progressive_gid,TTS(idempotency_key=uuid.uuid4().hex,
                voice_key='eleven_v3:syntheticvoice001',transfer_consent=True,streaming=True),user,token)
            progressive_aid=uuid.UUID(asset['id'])
            async with SessionLocal() as s:
                g=await s.get(ChatGeneration,progressive_gid);g.status='running'
                a=await s.get(VoiceAudio,progressive_aid);a.status='running';usage_id=a.usage_id
                u=await s.get(VoiceUsage,usage_id);u.status='running';await s.commit()
            first_pcm=asyncio.Event();finish_llm=asyncio.Event();cancelled=asyncio.Event();calls=[]
            async def llm_parts(*args):
                yield {'text':'First sentence. '}
                await finish_llm.wait()
                yield {'text':'Final sentence. [report-1]'}
                yield {'usage':{'input_tokens':120,'output_tokens':25},'done':True}
            async def progressive_tts(text,profile,language,zero_retention=False,on_chunk=None):
                calls.append(text)
                try:
                    async def output(pcm):
                        await on_chunk(pcm);first_pcm.set()
                        if remove_parent:await asyncio.Event().wait()
                    return await fixture.fake_tts(text,profile,language,zero_retention,on_chunk=output)
                finally:cancelled.set()
            with patch.object(llm,'stream',llm_parts),patch.object(fixture.providers,'http_tts',progressive_tts):
                llm_job=asyncio.create_task(chat.generate(progressive_gid))
                voice_job=asyncio.create_task(voice.generate(progressive_aid))
                try:
                    await asyncio.wait_for(first_pcm.wait(),5)
                    async with SessionLocal() as s:
                        assert (await s.get(ChatGeneration,progressive_gid)).status=='running'
                    assert preview.buffers[progressive_aid].size>0
                    if remove_parent:
                        async with SessionLocal() as s:
                            await s.execute(delete(ChatConversation).where(ChatConversation.id==progressive_cid));await s.commit()
                        await asyncio.wait_for(voice_job,2)
                        assert progressive_aid not in preview.buffers
                        assert cancelled.is_set()
                        async with SessionLocal() as s:
                            u=await s.get(VoiceUsage,usage_id);assert u.status=='unknown' and u.actual_usd is None
                    else:
                        finish_llm.set();await asyncio.wait_for(asyncio.gather(llm_job,voice_job),8)
                        async with SessionLocal() as s:
                            a=await s.get(VoiceAudio,progressive_aid)
                            assert a.status=='ready' and a.metadata_json['complete'],a.metadata_json
                            assert a.metadata_json['spoken_text']=='First sentence. Final sentence.'
                            assert storage.pcm(storage.Store().read(a))==fixture.PCM*2
                        assert len(calls)==2
                        replay=await voice.request_tts(progressive_gid,TTS(idempotency_key=uuid.uuid4().hex,
                            voice_key='eleven_v3:syntheticvoice001',transfer_consent=True),user,token)
                        assert replay['id']==asset['id'] and len(calls)==2
                finally:
                    finish_llm.set()
                    # Let authorization failure and final accounting finish;
                    # cancelling during the final transaction leaves an
                    # artificial active row for the subsequent budget race.
                    await asyncio.wait({llm_job,voice_job},timeout=2)
                    for task in (llm_job,voice_job):
                        if not task.done():task.cancel()
                    await asyncio.gather(llm_job,voice_job,return_exceptions=True)
                    async with SessionLocal() as s:
                        await s.execute(delete(ChatConversation).where(ChatConversation.id==progressive_cid));await s.commit()
        # Failed/ambiguous upstream work keeps its reservation after midnight.
        async with SessionLocal() as s:
            unknown=VoiceUsage(id=uuid.uuid4(),user_id=uid,assistant_id=aid,idempotency_key=uuid.uuid4().hex,kind='tts',status='unknown',
                reserved_usd=Decimal('.999'),units=100,price={'reference':'Synthetic unknown bill'},deadline=chat.now()-timedelta(days=1),
                created_at=chat.now()-timedelta(days=1))
            s.add(unknown);await s.commit()
        c=await chat_api.start(pid,ResearchStart(model_key='openai:fixture-v1'),token=token);cid=uuid.UUID(c['id'])
        q=Question(model_key='openai:fixture-v1',question='Blocked by carried voice reservation',context_version=c['context']['version'],idempotency_key=uuid.uuid4().hex)
        await reject(429,chat.send(cid,q,user,token))
        async with SessionLocal() as s:await s.execute(delete(VoiceUsage).where(VoiceUsage.id==unknown.id));await s.commit()
        # Measure the actual admission bound; earlier stopped generations
        # correctly retain money and must not be deleted to manufacture a cap.
        async with SessionLocal() as s:
            p=await s.get(ChatPolicy,1);p.config=original
            await s.execute(delete(VoiceUsage).where(VoiceUsage.user_id==uid));await s.commit()
        probe_q=q.model_copy(update={'idempotency_key':uuid.uuid4().hex})
        admitted=await chat.send(cid,probe_q,user,token);probe_gid=uuid.UUID(admitted['id'])
        async with SessionLocal() as s:
            g=await s.get(ChatGeneration,probe_gid);llm_bound=g.reserved_usd;g.cancel_requested=True;await s.commit()
        # Cancel before any upstream contact: a genuine zero-cost dry admission.
        await chat.generate(probe_gid)
        q=q.model_copy(update={'idempotency_key':uuid.uuid4().hex})
        async with SessionLocal() as s:
            from app.news_chat.budget import totals
            _,baseline=await totals(s,uid)
            vp=await voice.policy(s);stt_bound=voice.money(vp.stt_usd_per_minute*Decimal(vp.max_input_seconds+20)/60)
            ceiling=voice.money(baseline+max(llm_bound,stt_bound)+min(llm_bound,stt_bound)/2)
            p=await s.get(ChatPolicy,1);p.config={**original,'user_daily_budget_usd':str(ceiling)};await s.commit()
        race=await asyncio.gather(chat.send(cid,q,user,token),voice.create_session(cid,
            Start(idempotency_key=uuid.uuid4().hex,transfer_consent=True),user,token),return_exceptions=True)
        assert sum(isinstance(r,HTTPException) and r.status_code==429 for r in race)==1,race
        async with SessionLocal() as s:
            from app.news_chat.budget import totals
            total,own=await totals(s,uid);assert own<=ceiling
        print('Reader voice SQL passed: real migration, private PCM/WAV, same-owner ACL including Owner, cost-free replay/download, exact clip/dialogue bytes, idempotency, save-close lease, manifest, range, bookmarks, unsave guard, deletion outbox/cascade and shared LLM/STT budget race.')
    finally:
        async with SessionLocal() as s:
            p=await s.get(ChatPolicy,1);p.config=original
            # Delete only the accounts created by this synthetic gate.
            await s.execute(delete(AdminUser).where(AdminUser.id.in_([uid,peer_id])));await s.commit()
        await voice.maintenance_once();await engine.dispose()


if __name__=='__main__':asyncio.run(run())
