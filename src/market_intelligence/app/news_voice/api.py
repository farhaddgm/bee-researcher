import asyncio
import base64
import json
import re
import uuid
from pathlib import Path
from decimal import Decimal
from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, literal, select, text, tuple_
from app import admin
from app.config import get_settings
from app.database import SessionLocal
from app.news_chat.api import owner
from app.security_controls import ADMIN_SESSION_COOKIE
from app.news_chat import service as chat
from app.news_voice import gateway, service as svc, storage, preview, credentials, providers, pricing
from app.news_voice.models import VoiceAudio, VoicePolicy, VoiceSaveJob, VoiceSegment, VoiceSession, VoiceUsage
from app.news_voice.schemas import Bookmark, Brief, ConnectionCheck, CredentialUpdate, Playback, Policy, Reconcile, Save, Start, TTS

router=APIRouter();COOKIE=admin.USER_SESSION_COOKIE;ROOT=Path(__file__).parent


@router.get('/assets/news-voice/{asset}',include_in_schema=False)
async def asset(asset:str):
    files={'pcm-worklet.js':'application/javascript','pcm.js':'application/javascript','admin.js':'application/javascript','admin.css':'text/css','i18n.js':'application/javascript','admin-i18n.js':'application/javascript'}
    if asset not in files:raise HTTPException(404)
    if asset=='pcm-worklet.js':
        # Ship a single external module; worklet module graphs are less
        # consistent across engines than ordinary window ESM loading.
        source=(ROOT/'pcm.js').read_text().replace('export class PCMEncoder','class PCMEncoder')
        source+='\n'+(ROOT/asset).read_text().replace("import {PCMEncoder} from './pcm.js';",'')
        return Response(source,media_type='application/javascript',headers={'Cache-Control':'no-cache'})
    return FileResponse(ROOT/asset,media_type=files[asset],headers={'Cache-Control':'no-cache'})


@router.get('/user/api/voice/capabilities')
async def capabilities(assistant_id:uuid.UUID,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token);chat.require(user)
    from app.reader_research.service import project
    await project(user,assistant_id)
    async with SessionLocal() as s:
        p=await svc.policy(s);reason=None
        try:svc.enabled(p)
        except HTTPException as exc:reason=exc.detail
        return {'enabled':reason is None,'reason':reason,'continuous_enabled':p.continuous_enabled,
            'consent_version':'voice-1','max_input_seconds':p.max_input_seconds,'storage_bytes':p.storage_bytes,
            'voices':[{'key':v.key,'label':v.label,'languages':v.languages} for v in p.voices if v.verified]}


@router.post('/user/api/conversations/{cid}/voice-sessions',status_code=201)
async def start(cid:uuid.UUID,payload:Start,token:str|None=Cookie(None,alias=COOKIE)):
    return await svc.create_session(cid,payload,await admin.current_reader(token),token or '')


@router.websocket('/user/api/voice-sessions/{sid}/input')
async def input_audio(ws:WebSocket,sid:uuid.UUID):await gateway.run(ws,sid)


@router.post('/user/api/voice-sessions/{sid}/stop')
async def stop(sid:uuid.UUID,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:
        await svc.lock(s);row=await s.get(VoiceSession,sid,with_for_update=True)
        if not row or row.user_id!=user.id:raise HTTPException(404,'news_unavailable')
        if row.status=='created':
            u=await s.get(VoiceUsage,row.usage_id)
            if not u:raise HTTPException(410,'voice_session_closed')
            u.actual_usd=Decimal(0);u.units=Decimal(0);u.status='settled'
        if row.status in ['created','running']:row.status='stopped'
        await s.commit()
    return {'status':'stopped'}


@router.post('/user/api/chat-generations/{gid}/audio',status_code=202)
async def tts(gid:uuid.UUID,payload:TTS,token:str|None=Cookie(None,alias=COOKIE)):
    return await svc.request_tts(gid,payload,await admin.current_reader(token),token or '')


@router.post('/user/api/assistants/{aid}/brief-audio',status_code=202)
async def brief(aid:uuid.UUID,payload:Brief,token:str|None=Cookie(None,alias=COOKIE)):
    return await svc.request_brief(aid,payload,await admin.current_reader(token),token or '')


@router.get('/user/api/voice-audio/{aid}/events')
async def events(aid:uuid.UUID,request:Request,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:await svc.authorized_audio(s,aid,user)
    async def output():
        while not await request.is_disconnected():
            try:
                user=await admin.current_reader(token,touch=False)
                async with SessionLocal() as s:data=svc.view(await svc.authorized_audio(s,aid,user))
                yield 'event: snapshot\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
                if data['status'] not in ['preparing','running']:return
            except HTTPException:
                yield 'event: access_denied\ndata: {}\n\n';return
            await asyncio.sleep(.5)
    return StreamingResponse(output(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})


@router.get('/user/api/voice-audio/{aid}/content')
@router.get('/user/api/voice-audio/{aid}/download')
async def content(aid:uuid.UUID,request:Request,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:
        a=await svc.authorized_audio(s,aid,user)
        if a.status!='ready' or not a.object_key:raise HTTPException(409,'voice_audio_not_ready')
        try:data=await asyncio.to_thread(storage.Store().read,a)
        except Exception:raise HTTPException(503,'voice_storage_unavailable') from None
        # Recheck after filesystem I/O; revocation must win even during decrypt.
        await s.refresh(a);await svc.authorized_audio(s,aid,await admin.current_reader(token,touch=False))
    headers={'Cache-Control':'private, no-store','Accept-Ranges':'bytes','X-Content-Type-Options':'nosniff','Content-Encoding':'identity'}
    if request.url.path.endswith('/download'):headers['Content-Disposition']=f'attachment; filename="bee-voice-{aid}.wav"'
    status=200;size=len(data);interval=request.headers.get('range')
    if interval:
        match=re.fullmatch(r'bytes=(\d{0,10})-(\d{0,10})',interval)
        if not match or not any(match.groups()):raise HTTPException(416,'voice_range_invalid',headers={'Content-Range':f'bytes */{size}'})
        first,last=match.groups()
        if first:start=int(first);end=min(int(last) if last else size-1,size-1)
        else:start=max(0,size-int(last));end=size-1
        if not 0<=start<=end<size:raise HTTPException(416,'voice_range_invalid',headers={'Content-Range':f'bytes */{size}'})
        headers['Content-Range']=f'bytes {start}-{end}/{size}';data=data[start:end+1];status=206
    return Response(data,status_code=status,media_type='audio/wav',headers=headers)


@router.get('/user/api/voice-audio/{aid}/stream')
async def pcm_stream(aid:uuid.UUID,request:Request,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:await svc.authorized_audio(s,aid,user)
    async def output():
        index=0;sent=0;fallback=None
        while not await request.is_disconnected():
            try:
                actor=await admin.current_reader(token,touch=False)
                async with SessionLocal() as s:a=await svc.authorized_audio(s,aid,actor)
                b=preview.buffers.get(aid)
                if b:
                    # One frame per ACL check; cancellation is bounded even
                    # when the producer has finished faster than playback.
                    if index<len(b.chunks):
                        part=b.chunks[index];index+=1;sent+=len(part)
                        yield json.dumps({'sequence':index,'pcm':base64.b64encode(part).decode()})+'\n'
                        continue
                if a.status=='ready':
                    if not b:
                        if fallback is None:
                            data=await asyncio.to_thread(storage.Store().read,a)
                            fallback=storage.pcm(data)
                        # Process-local preview may have expired or been
                        # produced elsewhere. Resume canonical bytes only.
                        part=fallback[sent:sent+16000]
                        if part:
                            sent+=len(part);index+=1
                            yield json.dumps({'sequence':index,'pcm':base64.b64encode(part).decode()})+'\n';continue
                    yield '{"done":true}\n';return
                if a.status not in ['preparing','running']:yield '{"error":"voice_failed"}\n';return
            except (HTTPException,ValueError,OSError,KeyError):
                yield '{"error":"voice_access_denied"}\n';return
            await asyncio.sleep(.1)
    return StreamingResponse(output(),media_type='application/x-ndjson',headers={'Cache-Control':'private, no-store','X-Accel-Buffering':'no','Content-Encoding':'identity'})


@router.get('/user/api/conversations/{cid}/voice-audio')
async def conversation_audio(cid:uuid.UUID,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:
        await chat.conversation(s,cid,user)
        rows=(await s.scalars(select(VoiceAudio).where(VoiceAudio.conversation_id==cid,VoiceAudio.user_id==user.id,
            VoiceAudio.deleted_at.is_(None),VoiceAudio.scope!='user').order_by(VoiceAudio.created_at.desc(),VoiceAudio.id.desc()).limit(101))).all()
        return {'audio':[svc.view(a) for a in reversed(rows[:100]) if a.saved_at or a.expires_at>svc.now()], 'truncated':len(rows)>100}


@router.post('/user/api/conversations/{cid}/audio-saves',status_code=202)
async def save(cid:uuid.UUID,payload:Save,token:str|None=Cookie(None,alias=COOKIE)):
    return await svc.request_save(cid,payload,await admin.current_reader(token))


@router.get('/user/api/conversations/{cid}/audio-saves/{jid}')
async def job(cid:uuid.UUID,jid:uuid.UUID,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:
        await chat.conversation(s,cid,user)
        row=await s.get(VoiceSaveJob,jid)
        if not row or row.user_id!=user.id or row.conversation_id!=cid:raise HTTPException(404,'news_unavailable')
        return svc.job_view(row)


@router.get('/user/api/assistants/{aid}/voice-audio')
async def memories(aid:uuid.UUID,before:uuid.UUID|None=None,q:str=Query('',max_length=120),
                   language:str=Query('',max_length=8),token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    from app.reader_research.service import project
    await project(user,aid);chat.require(user)
    async with SessionLocal() as s:
        query=select(VoiceAudio).where(VoiceAudio.user_id==user.id,VoiceAudio.assistant_id==aid,VoiceAudio.saved_at.is_not(None),VoiceAudio.deleted_at.is_(None))
        if q.strip():
            needle=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            query=query.where(VoiceAudio.title.ilike('%'+needle+'%',escape='\\'))
        if language:query=query.where(VoiceAudio.metadata_json['language'].as_string()==language)
        if before:
            prior=await s.scalar(query.where(VoiceAudio.id==before))
            if not prior:raise HTTPException(404,'news_unavailable')
            query=query.where(tuple_(VoiceAudio.saved_at,VoiceAudio.id)<tuple_(literal(prior.saved_at),literal(prior.id)))
        rows=(await s.scalars(query.order_by(VoiceAudio.saved_at.desc(),VoiceAudio.id.desc()).limit(31))).all()
        visible=[]
        for a in rows[:30]:
            try:await svc.authorized_audio(s,a.id,user);visible.append(svc.view(a))
            except HTTPException:continue
        return {'audio':visible,'older_before':str(rows[29].id) if len(rows)>30 else None}


@router.get('/user/api/voice-audio/{aid}/manifest')
async def manifest(aid:uuid.UUID,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:
        a=await svc.authorized_audio(s,aid,user)
        c=await chat.conversation(s,a.conversation_id,user)
        rows=(await s.scalars(select(VoiceSegment).where(VoiceSegment.asset_id==aid).order_by(VoiceSegment.position))).all()
        return {'segments':[r.manifest for r in rows],'conversation_id':str(c.id),'assistant_id':str(c.assistant_id),'publication_id':str(c.publication_id)}


@router.delete('/user/api/voice-audio/{aid}')
async def remove(aid:uuid.UUID,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token)
    async with SessionLocal() as s:
        await svc.lock(s);a=await svc.authorized_audio(s,aid,user);await svc.tombstone(s,a);await s.commit()
    return {'status':'deleted'}


@router.post('/user/api/voice-audio/{aid}/playback')
async def playback(aid:uuid.UUID,payload:Playback,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    async with SessionLocal() as s:
        await svc.lock(s);a=await svc.authorized_audio(s,aid,user)
        ranges=a.metadata_json.get('played_ranges',[])+[list(r) for r in payload.played_ranges]
        bound=a.duration_ms/1000 if a.status=='ready' else 600
        merged:list[list[float]]=[]
        for start,end in sorted(ranges):
            end=min(end,bound)
            if end<=start:continue
            if merged and start<=merged[-1][1]+.05:merged[-1][1]=max(merged[-1][1],end)
            else:merged.append([start,end])
        a.metadata_json={**a.metadata_json,'played_seconds':min(payload.played_seconds,bound),
            'played_ranges':merged[:100],
            'interrupted':payload.interrupted or a.metadata_json.get('interrupted',False)}
        await s.commit()
    return {'status':'saved'}


@router.get('/admin/api/news-voice/usage')
async def unsettled(token:str|None=Cookie(None,alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as s:
        rows=(await s.scalars(select(VoiceUsage).where(VoiceUsage.actual_usd.is_(None))
            .order_by(VoiceUsage.created_at,VoiceUsage.id).limit(100))).all()
        return {'operations':[{'id':str(u.id),'kind':u.kind,'status':u.status,'units':str(u.units),
            'reserved_usd':str(u.reserved_usd),'price_reference':u.price.get('reference',''),
            'created_at':u.created_at.isoformat()} for u in rows]}


@router.post('/admin/api/news-voice/usage/{uid}/reconcile')
async def reconcile(uid:uuid.UUID,payload:Reconcile,token:str|None=Cookie(None,alias=ADMIN_SESSION_COOKIE)):
    actor=await owner(token)
    async with SessionLocal() as s:
        await svc.lock(s);u=await s.get(VoiceUsage,uid,with_for_update=True)
        if not u:raise HTTPException(404,'voice_usage_unavailable')
        if u.status in ['reserved','running']:raise HTTPException(409,'voice_usage_running')
        if u.actual_usd is not None:
            if u.actual_usd!=payload.actual_usd or u.price.get('provider_reference')!=payload.provider_reference:raise HTTPException(409,'revision_conflict')
        else:
            u.actual_usd=payload.actual_usd;u.status='settled'
            u.price={**u.price,'provider_reference':payload.provider_reference,'reconciled_by':str(actor.id),'reconciled_at':svc.now().isoformat()}
            await s.commit()
    await admin._audit(actor.id,'news_voice.reconcile',details={'usage_id':str(uid),'actual_usd':str(payload.actual_usd)})
    return {'status':'settled'}


@router.post('/user/api/voice-audio/{aid}/bookmarks')
async def bookmark(aid:uuid.UUID,payload:Bookmark,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token)
    async with SessionLocal() as s:
        await svc.lock(s);a=await svc.authorized_audio(s,aid,user)
        marks=a.metadata_json.get('bookmarks',[])
        if not a.saved_at or a.version!=payload.version:raise HTTPException(409,'revision_conflict')
        if payload.seconds>a.duration_ms/1000 or len(marks)>=50:raise HTTPException(422,'voice_bookmark_invalid')
        a.metadata_json={**a.metadata_json,'bookmarks':marks+[{'seconds':payload.seconds,'label':payload.label}]};a.version+=1
        await s.commit();return svc.view(a)


@router.get('/user/api/voice/usage')
async def usage(assistant_id:uuid.UUID,token:str|None=Cookie(None,alias=COOKIE)):
    user=await admin.current_reader(token,touch=False)
    from app.reader_research.service import project
    from app.news_chat.budget import totals,day_start
    await project(user,assistant_id);chat.require(user)
    async with SessionLocal() as s:
        p=await chat.policy(s);vp=await svc.policy(s);total,own=await totals(s,user.id)
        rows=(await s.execute(select(VoiceUsage.kind,func.sum(VoiceUsage.units),func.sum(func.coalesce(VoiceUsage.actual_usd,VoiceUsage.reserved_usd)))
            .where(VoiceUsage.user_id==user.id,VoiceUsage.created_at>=day_start()).group_by(VoiceUsage.kind))).all()
        used=await s.scalar(select(func.coalesce(func.sum(VoiceAudio.byte_count),0)).where(VoiceAudio.user_id==user.id,
            VoiceAudio.assistant_id==assistant_id,VoiceAudio.deleted_at.is_(None)))
        return {'scope':'personal_all_projects_daily_budget','remaining_budget_usd':str(max(Decimal(0),min(p.daily_budget_usd-total,p.user_daily_budget_usd-own))),
            'operations':[{'kind':kind,'units':str(units),'reserved_or_settled_usd':str(cost)} for kind,units,cost in rows],
            'storage_bytes':used,'storage_limit':vp.storage_bytes,'daily_stt_seconds':vp.daily_stt_seconds,
            'stt_seconds_remaining':max(0,vp.daily_stt_seconds-next((float(u) for k,u,c in rows if k=='stt'),0)),
            'cost_status':'conservative_reservations_until_provider_reconciliation'}


@router.get('/admin/api/news-voice/policy')
async def get_policy(token:str|None=Cookie(None,alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as s:return {'policy':(await svc.policy(s)).model_dump(mode='json'),
        'configured':svc.configured(),'server_enabled':get_settings().news_voice_enabled,
        'credential':await asyncio.to_thread(credentials.status),'published_pricing':pricing.snapshot()}


@router.put('/admin/api/news-voice/credential')
async def put_credential(payload:CredentialUpdate,token:str|None=Cookie(None,alias=ADMIN_SESSION_COOKIE)):
    actor=await owner(token)
    try:
        def update():
            return credentials.Credentials().update(payload.api_key.get_secret_value() if payload.api_key else '',payload.expected_revision)
        result=await asyncio.to_thread(update)
    except credentials.CredentialError as exc:
        raise HTTPException(409 if exc.code=='revision_conflict' else 503,exc.code) from None
    except Exception:
        raise HTTPException(503,'voice_credential_unavailable') from None
    await admin._audit(actor.id,'news_voice.credential',details={'action':payload.action})
    return {'status':'saved','credential':result}


@router.post('/admin/api/news-voice/connection-check')
async def connection_check(payload:ConnectionCheck,token:str|None=Cookie(None,alias=ADMIN_SESSION_COOKIE)):
    actor=await owner(token)
    # The shared database lock serializes diagnostics, also across workers.
    # A transaction-scoped lock is released even on timeout/cancellation.
    async with SessionLocal() as s:
        available=await s.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':918473202})
        if not available:raise HTTPException(429,'voice_rate_limited')
        try:
            async with asyncio.timeout(22):
                result=await providers.catalog(payload.api_key.get_secret_value() if payload.api_key else None,payload.search,payload.page_token)
        except providers.VoiceError as exc:
            raise HTTPException(422,exc.code) from None
        except TimeoutError:
            raise HTTPException(503,'voice_provider_failed') from None
    await admin._audit(actor.id,'news_voice.connection_check',details={'audio_tested':False})
    return result


@router.post('/admin/api/news-voice/account-check')
async def account_check(token:str|None=Cookie(None,alias=ADMIN_SESSION_COOKIE)):
    await owner(token)
    async with SessionLocal() as s:
        available=await s.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':918473202})
        if not available:raise HTTPException(429,'voice_rate_limited')
        try:
            async with asyncio.timeout(12):return await providers.subscription()
        except providers.VoiceError as exc:raise HTTPException(422,exc.code) from None
        except TimeoutError:raise HTTPException(503,'voice_provider_failed') from None


@router.put('/admin/api/news-voice/policy')
async def put_policy(payload:Policy,token:str|None=Cookie(None,alias=ADMIN_SESSION_COOKIE),
        expected_credential_revision:str|None=Header(None,alias='X-Voice-Credential-Revision')):
    actor=await owner(token)
    if payload.enabled and payload.require_zero_retention and (not payload.zero_retention_verified or len(payload.retention_reference)<10):
        raise HTTPException(422,'voice_retention_unavailable')
    if payload.enabled and payload.price_expires_at<=svc.now():raise HTTPException(422,'voice_price_expired')
    if payload.enabled and not svc.configured():raise HTTPException(422,'voice_unconfigured')
    credential=credentials.status()
    if payload.enabled and credential['source']=='owner' and expected_credential_revision!=credential['revision']:
        raise HTTPException(409,'revision_conflict')
    async with SessionLocal() as s:
        row=await s.get(VoicePolicy,1,with_for_update=True)
        if not row:row=VoicePolicy(id=1,config={});s.add(row)
        row.config={**payload.model_dump(mode='json'),'_credential_revision':credential['revision']};await s.commit()
    await admin._audit(actor.id,'news_voice.policy',details={'enabled':payload.enabled,'voice_count':len(payload.voices)})
    return {'status':'saved'}
