import asyncio
import hashlib
import json
import math
import secrets
import time
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from sqlalchemy import case, delete, func, or_, select, text
from fastapi import HTTPException
from app import admin
from app.config import get_settings
from app.database import SessionLocal
from app.deployment_drain import work_lease
from app.models import AdminSession, AdminUser
from app.news_chat import service as chat
from app.news_chat.models import ChatGeneration
from app.news_voice.models import VoiceAudio, VoiceDeletion, VoicePolicy, VoiceSaveJob, VoiceSegment, VoiceSession, VoiceUsage
from app.news_voice.schemas import Policy, Voice
from app.news_voice import providers, storage, preview

now=chat.now
hash_text=lambda value: hashlib.sha256(value.encode()).hexdigest()


def digest(value):return hash_text(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False))
def money(value):return Decimal(value).quantize(Decimal('0.00000001'),rounding=ROUND_CEILING)


async def lock(s):await s.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':chat.LOCK})


async def policy(s):
    row=await s.get(VoicePolicy,1)
    value=dict(row.config) if row else {}
    revision=value.pop('_credential_revision',None)
    p=Policy.model_validate(value);p._credential_revision=revision
    return p


def configured():
    settings=get_settings()
    if not settings.news_voice_keyring_file:return False
    try:providers.key();storage.Store(settings)
    except providers.VoiceError:return False
    except (ValueError,OSError,KeyError,TypeError):return False
    return True


def enabled(p):
    if not get_settings().news_voice_enabled or not p.enabled:raise HTTPException(403,'voice_disabled')
    if not configured():raise HTTPException(503,'voice_unconfigured')
    from app.news_voice.credentials import managed
    current=managed()
    if current is not None and p._credential_revision!=current['revision']:
        raise HTTPException(503,'voice_unverified')
    if not p.price_expires_at or p.price_expires_at<=now():raise HTTPException(503,'voice_price_expired')
    if p.require_zero_retention and (not p.zero_retention_verified or len(p.retention_reference)<10):
        raise HTTPException(503,'voice_retention_unavailable')


def voice_for(p,key,language):
    enabled(p)
    for voice in p.voices:
        if voice.key==key and voice.verified and language in voice.languages:return voice
    raise HTTPException(403,'voice_unavailable')


async def charges(s,user_id,day):
    # Also carry unsettled work across midnight; a day rollover is not a refund.
    charge=func.coalesce(VoiceUsage.actual_usd,VoiceUsage.reserved_usd)
    total,own=(await s.execute(select(func.coalesce(func.sum(charge),0),
        func.coalesce(func.sum(charge).filter(VoiceUsage.user_id==user_id),0)).where(
            or_(VoiceUsage.created_at>=day,VoiceUsage.status.in_(['reserved','running','unknown']))))).one()
    return total,own


async def reserve(s,user,c,kind,key,amount,units,price,deadline):
    from app.news_chat.budget import totals
    p=await chat.policy(s)
    if not p.enabled or not get_settings().news_chat_enabled:raise HTTPException(403,'chat_disabled')
    total,own=await totals(s,user.id)
    if total+amount>p.daily_budget_usd or own+amount>p.user_daily_budget_usd:raise HTTPException(429,'budget_exhausted')
    from app.news_chat.budget import day_start
    vp=await policy(s);voice_total,voice_own=await charges(s,user.id,day_start())
    if voice_total+amount>vp.daily_budget_usd or voice_own+amount>vp.user_daily_budget_usd:
        raise HTTPException(429,'budget_exhausted')
    old=await s.scalar(select(VoiceUsage).where(VoiceUsage.user_id==user.id,VoiceUsage.idempotency_key==key))
    if old:raise HTTPException(409,'idempotency_conflict')
    u=VoiceUsage(id=uuid.uuid4(),user_id=user.id,assistant_id=c.assistant_id,conversation_id=c.id,
        kind=kind,idempotency_key=key,status='reserved',reserved_usd=amount,actual_usd=None,
        units=units,price=price,deadline=deadline,created_at=now())
    s.add(u);await s.flush();return u


async def capacity(s,user_id,aid,p):
    used=await s.scalar(select(func.coalesce(func.sum(case((VoiceAudio.status.in_(['preparing','running']),p.max_audio_bytes),
        else_=VoiceAudio.byte_count)),0)).where(VoiceAudio.user_id==user_id,VoiceAudio.assistant_id==aid,
            VoiceAudio.deleted_at.is_(None),VoiceAudio.status.not_in(['failed','deleting']))) or 0
    saves=await s.scalar(select(func.count()).select_from(VoiceSaveJob).where(VoiceSaveJob.user_id==user_id,
        VoiceSaveJob.assistant_id==aid,VoiceSaveJob.status.in_(['preparing','running']),VoiceSaveJob.deadline>now())) or 0
    inputs=await s.scalar(select(func.count()).select_from(VoiceSession).where(VoiceSession.user_id==user_id,
        VoiceSession.assistant_id==aid,VoiceSession.status.in_(['created','running']),
        VoiceSession.config['retain_user_audio_for_save'].as_boolean().is_(True))) or 0
    if used+(saves+inputs+1)*p.max_audio_bytes>p.storage_bytes:raise HTTPException(429,'voice_storage_full')


async def deadline(s,user,token,seconds):
    row=await s.scalar(select(AdminSession).where(AdminSession.token_hash==hash_text(token),
        AdminSession.user_id==user.id,AdminSession.portal=='user'))
    if not row:raise HTTPException(401,'session_expired')
    return min(row.expires_at,admin._reader_nightly_expiry(row.created_at),
        row.created_at+timedelta(hours=get_settings().session_absolute_hours),now()+timedelta(seconds=seconds))


async def create_session(cid,payload,user,token):
    async with work_lease(),SessionLocal() as s:
        await lock(s);c=await chat.conversation(s,cid,user);p=await policy(s);enabled(p)
        if not p.stt_verified:raise HTTPException(503,'voice_unverified')
        if payload.continuous and not p.continuous_enabled:raise HTTPException(403,'voice_continuous_disabled')
        request=payload.model_dump(mode='json');request_hash=digest({'cid':str(cid),'request':request})
        prior=await s.scalar(select(VoiceSession).where(VoiceSession.user_id==user.id,VoiceSession.idempotency_key==payload.idempotency_key))
        ticket=secrets.token_urlsafe(32)
        if prior:
            if prior.config.get('_request_hash')!=request_hash or prior.session_hash!=hash_text(token):raise HTTPException(409,'idempotency_conflict')
            if prior.status!='created' or prior.deadline<=now():raise HTTPException(409,'voice_session_closed')
            prior.ticket_hash=hash_text(ticket);prior.ticket_expires_at=now()+timedelta(seconds=30)
            await s.commit();return {'id':str(prior.id),'ticket':ticket,'deadline':prior.deadline.isoformat(),'max_input_seconds':p.max_input_seconds}
        active=await s.scalar(select(VoiceSession.id).where(VoiceSession.user_id==user.id,VoiceSession.status.in_(['created','running'])))
        if active:raise HTTPException(429,'voice_busy')
        max_seconds=p.max_input_seconds
        if payload.continuous:
            # A continuous chain belongs to this conversation and login. Its
            # server limit includes AI response time and survives reconnects.
            key='_voice_continuous_started_at'
            from datetime import datetime
            try:start=datetime.fromisoformat(c.context[key])
            except (KeyError,ValueError,TypeError):start=now()
            remaining=p.max_session_seconds-(now()-start).total_seconds()
            if remaining<=0:raise HTTPException(410,'voice_continuous_limit')
            c.context={**c.context,key:start.isoformat()}
            max_seconds=min(max_seconds,max(1,int(remaining)))
        else:c.context={k:v for k,v in c.context.items() if k!='_voice_continuous_started_at'}
        from app.news_chat.budget import day_start
        seconds=await s.scalar(select(func.coalesce(func.sum(VoiceUsage.units),0)).where(VoiceUsage.user_id==user.id,
            VoiceUsage.kind=='stt',VoiceUsage.created_at>=day_start())) or 0
        if seconds+p.max_input_seconds+20>p.daily_stt_seconds:raise HTTPException(429,'voice_quota_exceeded')
        if payload.retain_user_audio_for_save:await capacity(s,user.id,c.assistant_id,p)
        end=await deadline(s,user,token,max_seconds+30)
        if payload.continuous:end=min(end,start+timedelta(seconds=p.max_session_seconds))
        rate=p.stt_usd_per_minute*(p.keyterms_multiplier if payload.keyterms else 1)
        cost=money(rate*Decimal(p.max_input_seconds+20)/60)
        usage=await reserve(s,user,c,'stt',payload.idempotency_key,cost,p.max_input_seconds+20,
            {'rate':str(rate),'unit':'minute','reference':p.price_reference},end)
        row=VoiceSession(id=uuid.uuid4(),user_id=user.id,assistant_id=c.assistant_id,conversation_id=cid,
            usage_id=usage.id,idempotency_key=payload.idempotency_key,session_hash=hash_text(token),
            ticket_hash=hash_text(ticket),ticket_expires_at=now()+timedelta(seconds=30),deadline=end,
            status='created',config={**request,'_request_hash':request_hash,'_max_seconds':max_seconds,
                '_zero_retention':p.require_zero_retention},transcript='',created_at=now())
        s.add(row);await s.commit()
        return {'id':str(row.id),'ticket':ticket,'deadline':end.isoformat(),'max_input_seconds':max_seconds}


async def live_session(sid,token):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:
        row=await s.get(VoiceSession,sid)
        if not row or row.user_id!=user.id or row.session_hash!=hash_text(token):raise HTTPException(404,'news_unavailable')
        if row.status not in ['created','running'] or row.deadline<=now():raise HTTPException(410,'voice_session_closed')
        await chat.conversation(s,row.conversation_id,user);enabled(await policy(s));return row


async def finish_session(sid,pcm,transcript,elapsed,success,contacted):
    async with SessionLocal() as s:
        await lock(s);row=await s.get(VoiceSession,sid,with_for_update=True)
        if not row:return None
        usage=await s.get(VoiceUsage,row.usage_id,with_for_update=True)
        usage.status='estimated' if success else ('unknown' if contacted else 'settled')
        usage.units=Decimal(str(round(elapsed,3))) if contacted else Decimal(0)
        # No refund for ambiguous requests; the reservation remains chargeable.
        if not contacted:usage.actual_usd=Decimal(0);usage.units=Decimal(0)
        else:usage.price={**usage.price,'estimated_usd':str(money(Decimal(usage.price['rate'])*Decimal(str(elapsed))/60))}
        c=await s.get(chat.ChatConversation,row.conversation_id)
        user=await s.get(AdminUser,row.user_id)
        valid=False
        try:
            if row.status=='running' and c and user:
                await chat.conversation(s,c.id,user);valid=True
        except HTTPException:pass
        row.status='completed' if success and valid else 'stopped'
        row.transcript=transcript[:4000] if valid else ''
        if valid and success and pcm and row.config['retain_user_audio_for_save']:
            p=await policy(s)
            audio=VoiceAudio(id=uuid.uuid4(),user_id=row.user_id,assistant_id=row.assistant_id,conversation_id=c.id,
                identity=digest({'stt':str(row.id)}),scope='user',status='ready',title='',
                metadata_json={'language':row.config['language'],'recognized_text':row.transcript,'session_id':str(row.id),'complete':True},
                byte_count=0,duration_ms=len(pcm)*1000//32000,version=0,expires_at=now()+timedelta(seconds=p.staging_seconds))
            data=storage.wav(pcm);audio.byte_count=len(data)
            if len(data)<=p.max_audio_bytes:
                audio.object_key,audio.sha256=await asyncio.to_thread(storage.Store().write,audio,data)
                s.add(audio);row.audio_id=audio.id
        await s.commit();return str(row.audio_id) if row.audio_id else None


def view(a):
    meta={k:v for k,v in a.metadata_json.items() if not k.startswith('_')}
    return {'id':str(a.id),'conversation_id':str(a.conversation_id),'generation_id':str(a.generation_id) if a.generation_id else None,
        'scope':a.scope,'status':a.status,'title':a.title,'duration_seconds':a.duration_ms/1000,
        'saved_at':a.saved_at.isoformat() if a.saved_at else None,'expires_at':a.expires_at.isoformat(),
        'version':a.version,'metadata':meta,'content_url':f'/user/api/voice-audio/{a.id}/content' if a.status=='ready' else None}


def voice_identity(v):
    return {k:value for k,value in v.model_dump(mode='json').items() if k in
        {'voice_id','model_id','transport','timing','pronunciation_dictionaries'}}


async def authorized_audio(s,aid,user):
    a=await s.scalar(select(VoiceAudio).where(VoiceAudio.id==aid,VoiceAudio.user_id==user.id,VoiceAudio.deleted_at.is_(None)))
    if not a:raise HTTPException(404,'news_unavailable')
    c=await chat.conversation(s,a.conversation_id,user)
    if a.saved_at and not c.saved_at:raise HTTPException(404,'news_unavailable')
    if not a.saved_at and a.expires_at<=now():raise HTTPException(410,'voice_audio_expired')
    return a


async def request_tts(gid,payload,user,token):
    async with work_lease(),SessionLocal() as s:
        await lock(s);g=await chat.authorized_generation(s,gid,user)
        streaming=payload.streaming and g.status in ('queued','running')
        if not streaming and (g.status!='completed' or not g.answer):raise HTTPException(409,'completed_answer_required')
        c=await chat.conversation(s,g.conversation_id,user);p=await policy(s)
        voice=voice_for(p,payload.voice_key,g.language);spoken=providers.spoken_text(g.answer)
        if len(spoken)>voice.max_chars or (not streaming and not spoken):raise HTTPException(422,'voice_text_too_large')
        request_hash=digest({'gid':str(gid),'request':payload.model_dump(mode='json')})
        prior_usage=await s.scalar(select(VoiceUsage).where(VoiceUsage.user_id==user.id,VoiceUsage.idempotency_key==payload.idempotency_key))
        if prior_usage:
            prior=await s.scalar(select(VoiceAudio).where(VoiceAudio.usage_id==prior_usage.id))
            if not prior or prior.metadata_json.get('_request_hash')!=request_hash:raise HTTPException(409,'idempotency_conflict')
            return view(await authorized_audio(s,prior.id,user))
        identity=digest({'generation':str(gid),'voice':voice_identity(voice),'language':g.language,'preprocessing':2})
        legacy=digest({'generation':str(gid),'text':spoken,'voice':voice_identity(voice),'language':g.language,'preprocessing':1})
        prior=await s.scalar(select(VoiceAudio).where(VoiceAudio.user_id==user.id,VoiceAudio.assistant_id==c.assistant_id,
            VoiceAudio.identity.in_([identity,legacy])).order_by(VoiceAudio.created_at.desc()).limit(1))
        if prior:
            if prior.deleted_at or prior.status=='failed' or (not prior.saved_at and prior.expires_at<=now()):
                if not payload.regenerate:raise HTTPException(409,'voice_retry_confirmation_required')
                await tombstone(s,prior)
                prior.identity=digest({'retired':str(prior.id)})
            else:return view(prior)
        busy=await s.scalar(select(VoiceAudio.id).where(VoiceAudio.user_id==user.id,VoiceAudio.status.in_(['preparing','running']),VoiceAudio.deleted_at.is_(None)))
        if busy:raise HTTPException(429,'voice_busy')
        await capacity(s,user.id,c.assistant_id,p)
        inputs=[]
        server_inputs=[uuid.UUID(sid) for sid in g.usage.get('voice_session_ids',[])]
        if set(payload.input_session_ids)-set(server_inputs):raise HTTPException(409,'voice_input_not_linked')
        sessions=[]
        for sid in server_inputs:
            session=await s.get(VoiceSession,sid,with_for_update=True)
            if not session or session.user_id!=user.id or session.conversation_id!=c.id or session.status!='completed':raise HTTPException(404,'news_unavailable')
            if session.generation_id and session.generation_id!=gid:raise HTTPException(409,'voice_input_already_linked')
            session.generation_id=gid
            sessions.append(session)
        for session in sorted(sessions,key=lambda row:(row.created_at,str(row.id))):
            inputs.append({'session_id':str(session.id),'audio_id':str(session.audio_id) if session.audio_id else None,
                'recognized_text':session.transcript,'submitted_question':g.question})
        end=await deadline(s,user,token,get_settings().news_chat_timeout_seconds)
        units=voice.max_chars if streaming else len(spoken)
        reserve_cost=money(voice.usd_per_1000_chars*units/1000)
        u=await reserve(s,user,c,'tts',payload.idempotency_key,reserve_cost,units,
            {'rate':str(voice.usd_per_1000_chars),'unit':'1000_characters','reference':p.price_reference},end)
        a=VoiceAudio(id=uuid.uuid4(),user_id=user.id,assistant_id=c.assistant_id,conversation_id=c.id,generation_id=gid,
            usage_id=u.id,identity=identity,scope='ai',status='preparing',title='',byte_count=0,duration_ms=0,version=0,
            expires_at=now()+timedelta(seconds=p.staging_seconds),metadata_json={'language':g.language,'model':voice.model_id,
                'voice':voice.label,'spoken_text':'' if streaming else spoken,'original_text_hash':hash_text(g.answer),
                'inputs':inputs,'complete':not streaming,'_streaming':streaming,
                '_voice':voice.model_dump(mode='json'),'_session_hash':hash_text(token),'_deadline':end.isoformat(),
                '_zero_retention':p.require_zero_retention,'_request_hash':request_hash})
        s.add(a);await s.commit();return view(a)


async def request_brief(aid,payload,user,token):
    from app.reader_research.service import project
    from app.news_chat.context import reader_report_text
    await project(user,aid);chat.require(user)
    async with work_lease(),SessionLocal() as s:
        await lock(s);p=await policy(s);voice=voice_for(p,payload.voice_key,payload.language)
        request_hash=digest({'project':str(aid),'request':payload.model_dump(mode='json')})
        prior_usage=await s.scalar(select(VoiceUsage).where(VoiceUsage.user_id==user.id,VoiceUsage.idempotency_key==payload.idempotency_key))
        if prior_usage:
            a=await s.scalar(select(VoiceAudio).where(VoiceAudio.usage_id==prior_usage.id))
            if not a or a.metadata_json.get('_request_hash')!=request_hash:raise HTTPException(409,'idempotency_conflict')
            return view(await authorized_audio(s,a.id,user))
        segments=[];sources=[];words_left=payload.minutes*120
        for pid in payload.publication_ids:
            pub=await chat.publication(s,pid,user)
            if pub.assistant_id!=aid:raise HTTPException(404,'news_unavailable')
            if (pub.published_at or pub.created_at)<now()-timedelta(hours=24):raise HTTPException(422,'voice_brief_requires_recent_news')
            clean=reader_report_text(pub.message_text);words=clean.split()
            take=min(80,words_left,len(words));snippet=' '.join(words[:take]);words_left-=take
            if not snippet:continue
            sources.append(str(pid));segments.append({'id':'report-'+str(len(segments)),'text':snippet,
                'publication_id':str(pid),'scope':'published_report','source_hash':hash_text(clean),'excerpt':True})
        spoken=providers.spoken_text('\n'.join(seg['text'] for seg in segments))
        if not spoken or len(spoken)>voice.max_chars:raise HTTPException(422,'voice_text_too_large')
        source_ranges=[];offset=0
        for seg in segments:
            part=providers.spoken_text(seg['text']);start=spoken.find(part,offset)
            if part and start>=0:
                source_ranges.append({'publication_id':seg['publication_id'],'start':start,'end':start+len(part)})
                offset=start+len(part)
        identity=digest({'brief':segments,'voice':voice_identity(voice),'language':payload.language,'preprocessing':1})
        cached=await s.scalar(select(VoiceAudio).where(VoiceAudio.user_id==user.id,VoiceAudio.assistant_id==aid,VoiceAudio.identity==identity))
        if cached:
            if not cached.deleted_at and (cached.saved_at or cached.expires_at>now()):return view(await authorized_audio(s,cached.id,user))
            await tombstone(s,cached);cached.identity=digest({'retired':str(cached.id)})
        busy=await s.scalar(select(VoiceAudio.id).where(VoiceAudio.user_id==user.id,VoiceAudio.status.in_(['preparing','running']),VoiceAudio.deleted_at.is_(None)))
        if busy:raise HTTPException(429,'voice_busy')
        await capacity(s,user.id,aid,p)
        count=await s.scalar(select(func.count()).select_from(chat.ChatConversation).where(chat.ChatConversation.user_id==user.id,chat.ChatConversation.deleted_at.is_(None)))
        if count>=500:raise HTTPException(429,'quota_exceeded')
        c=chat.ChatConversation(id=uuid.uuid4(),user_id=user.id,assistant_id=aid,publication_id=uuid.UUID(sources[0]),
            provider='voice',created_at=now(),context={'version':digest(segments),'scope':'voice_brief','complete':False,
                'segments':segments,'source_ids':sources,'_ephemeral':True,'_session_hash':hash_text(token),
                '_expires_at':(now()+timedelta(seconds=chat.WINDOW_LEASE_SECONDS)).isoformat()})
        s.add(c);await s.flush();end=await deadline(s,user,token,get_settings().news_chat_timeout_seconds)
        u=await reserve(s,user,c,'tts',payload.idempotency_key,money(voice.usd_per_1000_chars*len(spoken)/1000),len(spoken),
            {'rate':str(voice.usd_per_1000_chars),'unit':'1000_characters','reference':p.price_reference},end)
        a=VoiceAudio(id=uuid.uuid4(),user_id=user.id,assistant_id=aid,conversation_id=c.id,usage_id=u.id,
            identity=identity,scope='ai',status='preparing',title='',byte_count=0,duration_ms=0,version=0,
            expires_at=now()+timedelta(seconds=p.staging_seconds),metadata_json={'kind':'brief','source_ids':sources,
                'source_ranges':source_ranges,
                'language':payload.language,'model':voice.model_id,'voice':voice.label,'spoken_text':spoken,
                'original_text_hash':hash_text(spoken),'inputs':[],'complete':True,'_voice':voice.model_dump(mode='json'),
                '_session_hash':hash_text(token),'_deadline':end.isoformat(),'_zero_retention':p.require_zero_retention,
                '_request_hash':request_hash})
        s.add(a);await s.commit();return view(a)


async def producer_live(aid):
    async with SessionLocal() as s:
        a=await s.get(VoiceAudio,aid)
        if not a or a.deleted_at or a.status!='running':raise HTTPException(410,'voice_audio_cancelled')
        if a.metadata_json.get('_streaming'):
            g=await s.get(ChatGeneration,a.generation_id)
            if not g or g.cancel_requested:raise HTTPException(410,'voice_audio_cancelled')
        sess=await s.scalar(select(AdminSession).where(AdminSession.token_hash==a.metadata_json['_session_hash'],
            AdminSession.portal=='user',AdminSession.expires_at>now()))
        if not sess:raise HTTPException(401,'session_expired')
        user=await s.get(AdminUser,sess.user_id)
        await chat.conversation(s,a.conversation_id,user)
        voice_for(await policy(s),Voice.model_validate(a.metadata_json['_voice']).key,a.metadata_json['language'])
        return a


async def generate(aid):
    ready=False
    try:
        ready=await _generate(aid)
    finally:
        # Missing cascade rows, database errors and task cancellation all leave
        # this path. No private preview can survive an unsuccessful producer.
        if ready:preview.finish(aid)
        else:preview.remove(aid)


async def _generate(aid):
    contacted=False;result=None;error=None;stream_state=None;usage_id=None
    try:
        a=await producer_live(aid);usage_id=getattr(a,'usage_id',None);voice=Voice.model_validate(a.metadata_json['_voice'])
        from datetime import datetime
        end=datetime.fromisoformat(a.metadata_json['_deadline'])
        async with asyncio.timeout(max(.01,(end-now()).total_seconds())):
            preview.start(aid)
            if a.metadata_json.get('_streaming'):
                from app.news_voice import incremental
                stream_state={'spoken_text':'','complete':False}
                def contact():
                    nonlocal contacted
                    contacted=True
                operation=incremental.synthesize(incremental.answer_parts(a.generation_id,voice.max_chars,stream_state),
                    voice,a.metadata_json['language'],a.metadata_json['_zero_retention'],
                    on_chunk=lambda pcm:preview.append(aid,pcm),on_contact=contact)
            else:
                contacted=True
                operation=(providers.http_tts if voice.transport=='http' else providers.ttd_tts)(
                    a.metadata_json['spoken_text'],voice,a.metadata_json['language'],a.metadata_json['_zero_retention'],
                    on_chunk=lambda pcm:preview.append(aid,pcm))
            op=asyncio.create_task(operation)
            try:
                while not op.done():
                    await asyncio.wait({op},timeout=.5);await producer_live(aid)
                result=op.result()
            finally:
                if not op.done():op.cancel()
                await asyncio.gather(op,return_exceptions=True)
        await producer_live(aid)
    except providers.VoiceError as exc:error=exc.code
    except HTTPException as exc:error=str(exc.detail)
    except BaseException:error='voice_generation_unknown'
    async with SessionLocal() as s:
        await lock(s);a=await s.get(VoiceAudio,aid,with_for_update=True)
        if not a:
            if usage_id:
                usage=await s.get(VoiceUsage,usage_id,with_for_update=True)
                if usage and usage.status in ('reserved','running'):
                    usage.status='unknown' if contacted else 'settled'
                    if not contacted:usage.actual_usd=Decimal(0);usage.units=Decimal(0)
                    await s.commit()
            return
        u=await s.get(VoiceUsage,a.usage_id,with_for_update=True)
        u.status='unknown' if contacted else 'settled'
        if not contacted:u.actual_usd=Decimal(0);u.units=Decimal(0)
        if result and not a.deleted_at and a.status=='running':
            try:
                raw,timing=result;data=storage.wav(raw)
                if stream_state:a.metadata_json={**a.metadata_json,**stream_state}
                if len(data)>(await policy(s)).max_audio_bytes:raise ValueError('audio_too_large')
                a.byte_count=len(data);a.duration_ms=len(raw)*1000//32000
                a.object_key,a.sha256=await asyncio.to_thread(storage.Store().write,a,data)
                # Normalization or malformed timing must never highlight an
                # invented correspondence with the canonical spoken text.
                if (''.join(x['text'] for x in timing)!=a.metadata_json['spoken_text'] or
                    any(x['end']>len(raw)/32000+.1 for x in timing) or
                    any(timing[i]['start']<timing[i-1]['start'] for i in range(1,len(timing)))):timing=[]
                a.status='ready';a.metadata_json={**a.metadata_json,'timing':timing,
                    'timing_text':''.join(x['text'] for x in timing), '_session_hash':''}
                if timing and a.metadata_json.get('kind')=='brief':
                    spans=[];offset=0
                    for cue in timing:
                        spans.append((offset,offset+len(cue['text']),cue));offset+=len(cue['text'])
                    chapters=[]
                    for source in a.metadata_json.get('source_ranges',[]):
                        cues=[cue for first,last,cue in spans if last>source['start'] and first<source['end']]
                        if cues:chapters.append({'publication_id':source['publication_id'],
                            'start_seconds':cues[0]['start'],'end_seconds':cues[-1]['end']})
                    a.metadata_json={**a.metadata_json,'chapters':chapters}
                u.units=Decimal(len(a.metadata_json['spoken_text']))
                estimate=money(Decimal(u.price['rate'])*u.units/1000)
                u.status='estimated';u.price={**u.price,'estimated_usd':str(estimate)}
            except Exception:error='voice_storage_failed';a.status='failed'
        elif not a.deleted_at:a.status='failed'
        if error:a.metadata_json={**a.metadata_json,'error_code':error,'_session_hash':''}
        await s.commit()
    return a.status=='ready' and not error


async def request_save(cid,payload,user):
    async with work_lease(),SessionLocal() as s:
        await lock(s);c=await chat.conversation(s,cid,user);p=await policy(s)
        body=payload.model_dump(mode='json');request_hash=digest({'cid':str(cid),'request':body})
        old=await s.scalar(select(VoiceSaveJob).where(VoiceSaveJob.user_id==user.id,VoiceSaveJob.idempotency_key==payload.idempotency_key))
        if old:
            if old.payload_hash!=request_hash:raise HTTPException(409,'idempotency_conflict')
            return job_view(old)
        await capacity(s,user.id,c.assistant_id,p)
        for selected in payload.selections:
            a=await authorized_audio(s,selected.asset_id,user)
            if a.conversation_id!=cid or a.scope!='ai' or a.status!='ready':raise HTTPException(409,'voice_audio_not_ready')
            if selected.end_seconds and selected.end_seconds>a.duration_ms/1000:raise HTTPException(422,'voice_clip_range_invalid')
            if not a.saved_at:a.expires_at=max(a.expires_at,now()+timedelta(seconds=60))
            if payload.scope=='dialogue':
                for input in a.metadata_json.get('inputs',[]):
                    if not input.get('audio_id'):continue
                    try:
                        raw=await authorized_audio(s,uuid.UUID(input['audio_id']),user)
                        if raw.conversation_id==cid and not raw.saved_at:raw.expires_at=max(raw.expires_at,now()+timedelta(seconds=60))
                    except HTTPException:pass
        job=VoiceSaveJob(id=uuid.uuid4(),user_id=user.id,assistant_id=c.assistant_id,conversation_id=c.id,
            idempotency_key=payload.idempotency_key,payload_hash=request_hash,status='preparing',
            deadline=now()+timedelta(seconds=60),payload=body,created_at=now())
        s.add(job)
        # Bounded hold: close/retention must see an accepted save, not a UI guess.
        if not c.saved_at:c.context={**c.context,'_voice_save_until':job.deadline.isoformat()}
        await s.commit();return job_view(job)


def job_view(job):return {'id':str(job.id),'status':job.status,'asset_id':str(job.asset_id) if job.asset_id else None,'error_code':job.error_code}


async def finalize_save(jid):
    async with SessionLocal() as s:
        await lock(s);job=await s.get(VoiceSaveJob,jid,with_for_update=True)
        if not job or job.status!='running':return
        try:
            if job.deadline<=now():raise HTTPException(410,'voice_save_expired')
            user=await s.get(AdminUser,job.user_id);c=await chat.conversation(s,job.conversation_id,user)
            p=await policy(s);store=storage.Store();raw=bytearray();manifest=[];complete=True;identity=[]
            selections=[]
            for selected in job.payload['selections']:
                a=await authorized_audio(s,uuid.UUID(selected['asset_id']),user)
                if a.status!='ready' or a.scope!='ai' or a.conversation_id!=c.id:raise HTTPException(409,'voice_audio_not_ready')
                if a.metadata_json.get('kind')=='brief':
                    from types import SimpleNamespace
                    g=SimpleNamespace(id=None,created_at=a.created_at,answer=a.metadata_json['spoken_text'],question='',
                        citations=[{'publication_id':sid,'scope':'published_report'} for sid in a.metadata_json['source_ids']])
                else:
                    g=await s.get(ChatGeneration,a.generation_id)
                    if not g or g.status!='completed' or a.metadata_json['original_text_hash']!=hash_text(g.answer):raise HTTPException(409,'voice_text_changed')
                selections.append((g.created_at,g.id,a,selected,g))
            # Caller order never invents a conversation chronology.
            selections.sort(key=lambda x:(x[0],str(x[1])))
            def append_part(pcm,speaker,gid,meta):
                start=len(raw)*1000//32000;raw.extend(pcm)
                if len(raw)+44>p.max_audio_bytes or len(raw)>600*32000:raise HTTPException(422,'audio_too_large')
                manifest.append({'speaker':speaker,'generation_id':str(gid) if gid else None,'start_ms':start,'end_ms':len(raw)*1000//32000,**meta})
            for _,__,a,selected,g in selections:
                inputs=a.metadata_json.get('inputs',[])
                if job.payload['scope']=='dialogue':
                    if not inputs:complete=False
                    for item in inputs:
                        if not item.get('audio_id'):complete=False;continue
                        try:
                            user_audio=await authorized_audio(s,uuid.UUID(item['audio_id']),user)
                            pcm=storage.pcm(await asyncio.to_thread(store.read,user_audio))
                            append_part(pcm,'user',g.id,{'recognized_text':item['recognized_text'],'submitted_question':g.question})
                            identity.append([str(user_audio.id),user_audio.sha256])
                        except HTTPException:complete=False
                pcm=storage.pcm(await asyncio.to_thread(store.read,a))
                begin=round((selected['start_seconds'] or 0)*16000)*2
                end=round(selected['end_seconds']*16000)*2 if selected['end_seconds'] is not None else len(pcm)
                if not(0<=begin<end<=len(pcm)):raise HTTPException(422,'voice_clip_range_invalid')
                interrupted=a.metadata_json.get('interrupted',False)
                if job.payload['scope']=='dialogue':complete=complete and not interrupted and begin==0 and end==len(pcm)
                append_part(pcm[begin:end],'ai',g.id,{'text':g.answer,'spoken_text':a.metadata_json['spoken_text'],
                    'clip_start_seconds':begin/32000,'clip_end_seconds':end/32000,'citations':g.citations,
                    'produced_audio':True,'interrupted':interrupted,'played_seconds':a.metadata_json.get('played_seconds',0)})
                manifest[-1]['played_ranges']=a.metadata_json.get('played_ranges',[])
                identity.append([str(a.id),a.sha256,begin,end])
            if not complete and not job.payload['allow_partial']:raise HTTPException(409,'voice_full_recording_unavailable')
            snapshot=digest({'conversation':str(c.id),'scope':job.payload['scope'],'sources':identity,'format':'wav_pcm_16000_v1'})
            asset=await s.scalar(select(VoiceAudio).where(VoiceAudio.user_id==user.id,VoiceAudio.assistant_id==c.assistant_id,VoiceAudio.identity==snapshot))
            if asset and asset.deleted_at:raise HTTPException(410,'voice_snapshot_deleted')
            if not asset:
                data=storage.wav(bytes(raw))
                asset=VoiceAudio(id=uuid.uuid4(),user_id=user.id,assistant_id=c.assistant_id,conversation_id=c.id,
                    identity=snapshot,scope=job.payload['scope'],status='ready',title=job.payload['title'],
                    byte_count=len(data),duration_ms=len(raw)*1000//32000,version=0,saved_at=now(),expires_at=now(),
                    metadata_json={'complete':complete,'format':'wav_pcm_16000','ordered_turns':True,'bookmarks':[],
                        'language':selections[0][2].metadata_json['language'],'snapshot':snapshot,
                        'generation_ids':[str(x[4].id) for x in selections if x[4].id]})
                asset.object_key,asset.sha256=await asyncio.to_thread(store.write,asset,data)
                s.add(asset);await s.flush()
                for i,segment in enumerate(manifest):
                    s.add(VoiceSegment(id=uuid.uuid4(),asset_id=asset.id,generation_id=uuid.UUID(segment['generation_id']) if segment['generation_id'] else None,
                        position=i,speaker=segment['speaker'],start_ms=segment['start_ms'],end_ms=segment['end_ms'],manifest=segment))
            elif asset.title!=job.payload['title']:
                asset.title=job.payload['title'];asset.version+=1
            c.saved_at=c.saved_at or now();c.context={k:v for k,v in c.context.items() if not k.startswith('_') or k=='_voice_continuous_started_at'}
            job.asset_id=asset.id;job.status='completed';job.payload={};job.error_code=None
        except HTTPException as exc:job.status='failed';job.error_code=str(exc.detail);job.payload={}
        except Exception:job.status='failed';job.error_code='voice_storage_failed';job.payload={}
        await s.commit()


async def tombstone(s,a):
    if a.deleted_at:return
    a.deleted_at=now();a.status='deleting';a.metadata_json={};a.title=''
    preview.remove(a.id)
    await s.execute(delete(VoiceSegment).where(VoiceSegment.asset_id==a.id))


async def erase_conversation(s,cid):
    for a in (await s.scalars(select(VoiceAudio).where(VoiceAudio.conversation_id==cid,VoiceAudio.deleted_at.is_(None)).with_for_update())).all():
        await tombstone(s,a)
    for row in (await s.scalars(select(VoiceSession).where(VoiceSession.conversation_id==cid))).all():
        row.status='stopped';row.transcript='';row.config={};row.ticket_hash='';row.session_hash=''
    for job in (await s.scalars(select(VoiceSaveJob).where(VoiceSaveJob.conversation_id==cid,VoiceSaveJob.status.in_(['preparing','running'])))).all():
        job.status='failed';job.payload={};job.error_code='conversation_closed'
    await s.flush()  # Persist audio tombstones before clearing saved_at.


def save_lease(c):
    from datetime import datetime
    try:return datetime.fromisoformat(c.context.get('_voice_save_until',''))>now()
    except ValueError:return False


async def close_ephemeral(s,cid):
    for a in (await s.scalars(select(VoiceAudio).where(VoiceAudio.conversation_id==cid,VoiceAudio.saved_at.is_(None),VoiceAudio.deleted_at.is_(None)))).all():await tombstone(s,a)
    for row in (await s.scalars(select(VoiceSession).where(VoiceSession.conversation_id==cid,VoiceSession.status.in_(['created','running'])))).all():
        if row.status=='created':
            usage=await s.get(VoiceUsage,row.usage_id);usage.status='settled';usage.actual_usd=Decimal(0);usage.units=0
        row.status='stopped';row.transcript='';row.config={};row.ticket_hash='';row.session_hash=''


async def maintenance_once():
    preview.sweep()
    async with SessionLocal() as s:
        await lock(s)
        for session in (await s.scalars(select(VoiceSession).where(VoiceSession.status=='created',VoiceSession.ticket_expires_at<now()))).all():
            session.status='stopped';session.transcript=''
            u=await s.get(VoiceUsage,session.usage_id);u.status='settled';u.actual_usd=Decimal(0);u.units=0
        for u in (await s.scalars(select(VoiceUsage).where(VoiceUsage.status.in_(['reserved','running']),VoiceUsage.deadline<now()-timedelta(seconds=10)))).all():
            u.status='unknown'
        for a in (await s.scalars(select(VoiceAudio).join(VoiceUsage,VoiceUsage.id==VoiceAudio.usage_id).where(
                VoiceAudio.deleted_at.is_(None),VoiceAudio.status.in_(['preparing','running']),
                VoiceUsage.deadline<now()-timedelta(seconds=10)))).all():
            a.status='failed';a.metadata_json={**a.metadata_json,'error_code':'voice_generation_unknown','_session_hash':''}
            preview.remove(a.id)
        for row in (await s.scalars(select(VoiceSession).where(VoiceSession.status=='running',VoiceSession.deadline<now()))).all():row.status='stopped';row.transcript=''
        p=await policy(s)
        for a in (await s.scalars(select(VoiceAudio).where(VoiceAudio.deleted_at.is_(None),or_(
                (VoiceAudio.saved_at.is_(None)) & (VoiceAudio.expires_at<now()),
                (VoiceAudio.saved_at<now()-timedelta(days=p.retention_days or 36500)) if p.retention_days else False)))).all():
            await tombstone(s,a)
        for job in (await s.scalars(select(VoiceSaveJob).where(VoiceSaveJob.status.in_(['preparing','running']),VoiceSaveJob.deadline<now()))).all():
            job.status='failed';job.error_code='voice_save_expired';job.payload={}
        await s.commit()
        if not get_settings().news_voice_keyring_file:return
        store=storage.Store()
        for row in (await s.scalars(select(VoiceDeletion).where(VoiceDeletion.status=='pending').limit(100).with_for_update(skip_locked=True))).all():
            try:await asyncio.to_thread(store.remove,row.object_key);row.status='completed'
            except (OSError,ValueError):row.attempts+=1
        await s.commit()
        # Reconcile abandoned writes after a crash between fsync and SQL commit.
        known=set((await s.scalars(select(VoiceAudio.id).where(VoiceAudio.deleted_at.is_(None)))).all())
        for path in store.root.iterdir():
            if path.suffix not in ['.aead','.pending'] or path.stat().st_mtime>time.time()-120:continue
            try:ident=uuid.UUID(hex=path.stem)
            except ValueError:continue
            if ident not in known:await asyncio.to_thread(store.remove,ident.hex)


async def worker(stop):
    while not stop.is_set():
        try:
            async with work_lease(),SessionLocal() as s:
                a=await s.scalar(select(VoiceAudio).where(VoiceAudio.status=='preparing',VoiceAudio.deleted_at.is_(None)).order_by(VoiceAudio.created_at).limit(1).with_for_update(skip_locked=True))
                job=None
                if a:a.status='running';await s.commit();await generate(a.id)
                else:
                    job=await s.scalar(select(VoiceSaveJob).where(VoiceSaveJob.status=='preparing').order_by(VoiceSaveJob.created_at).limit(1).with_for_update(skip_locked=True))
                    if job:job.status='running';await s.commit();await finalize_save(job.id)
            if not a and not job:await asyncio.wait_for(stop.wait(),.5)
        except TimeoutError:pass
        except Exception:
            try:await asyncio.wait_for(stop.wait(),2)
            except TimeoutError:pass


async def maintenance(stop):
    while not stop.is_set():
        try:
            async with work_lease():await maintenance_once()
        except Exception:pass
        try:await asyncio.wait_for(stop.wait(),15)
        except TimeoutError:pass
