"""Authenticated Bee websocket proxy with server time/byte ceilings."""
import asyncio
import json
import secrets
import time
import uuid
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from app.config import get_settings
from app.database import SessionLocal
from app.deployment_drain import work_lease
from app.news_voice import providers, service
from app.news_voice.models import VoiceSession, VoiceUsage


def origin_allowed(ws):
    s=get_settings();origin=ws.headers.get('origin','')
    allowed={f'https://{host}' for host in (s.domain,s.legacy_domain) if host}
    if s.environment!='production':
        host=ws.headers.get('host','')
        allowed.update({f'http://{host}',f'https://{host}'})
    return origin in allowed


async def run(ws:WebSocket,sid:uuid.UUID):
    if not origin_allowed(ws):await ws.close(code=1008);return
    token=ws.cookies.get('research_bee_user_session','')
    texts:list[str]=[]
    accepted=False;claimed=False;finished=False;contacted=False;success=False;pcm=bytearray();start=time.monotonic();tasks=[]
    stopping=asyncio.Event();final=asyncio.Event();retained=False
    try:
        row=await service.live_session(sid,token)
        await ws.accept();accepted=True
        raw=await asyncio.wait_for(ws.receive_text(),5)
        if len(raw)>1024:raise HTTPException(403,'voice_ticket_invalid')
        boot=json.loads(raw)
        async with SessionLocal() as s:
            await service.lock(s);row=await s.get(VoiceSession,sid,with_for_update=True)
            if (not row or row.status!='created' or row.ticket_expires_at<=service.now() or
                not secrets.compare_digest(service.hash_text(str(boot.get('ticket',''))),row.ticket_hash)
                or row.session_hash!=service.hash_text(token) or set(boot)!={'ticket'}):
                raise HTTPException(403,'voice_ticket_invalid')
            row.ticket_hash='';row.status='running';retained=row.config['retain_user_audio_for_save']
            usage=await s.get(VoiceUsage,row.usage_id)
            if not usage:raise HTTPException(410,'voice_session_closed')
            usage.status='running'
            config=row.config;await s.commit();claimed=True
        async with work_lease():
            contacted=True;start=time.monotonic()
            async with providers.scribe(config['language'],config['continuous'],config['keyterms'],config['_zero_retention']) as upstream:
                async def incoming():
                    sequence=0;total=0;pending=None
                    while True:
                        event=await ws.receive()
                        if event['type']=='websocket.disconnect':raise WebSocketDisconnect()
                        chunk=event.get('bytes')
                        if chunk is not None:
                            if len(chunk)<6 or len(chunk)>32004 or (len(chunk)-4)%2 or int.from_bytes(chunk[:4],'little')!=sequence:
                                raise HTTPException(422,'voice_frame_invalid')
                            sequence+=1;raw=chunk[4:];total+=len(raw)
                            if total>(time.monotonic()-start+1)*32000 or total>config['_max_seconds']*32000 or sequence>(time.monotonic()-start+1)*10:
                                raise HTTPException(429,'voice_frame_limit')
                            if retained:pcm.extend(raw)
                            if pending is not None:await upstream.send(providers.audio_chunk(pending))
                            pending=raw
                        else:
                            control=event.get('text','')
                            if len(control)>100 or json.loads(control)!={'type':'stop'}:raise HTTPException(422,'voice_frame_invalid')
                            stopping.set()
                            if pending is not None:await upstream.send(providers.audio_chunk(pending,commit=True))
                            return

                async def outgoing():
                    index=0
                    async for raw in upstream:
                        part=json.loads(raw);kind=part.get('message_type')
                        if kind=='warning' and config['_zero_retention']:raise HTTPException(503,'voice_retention_unavailable')
                        if kind=='session_started':await ws.send_json({'type':'listening'})
                        elif kind in ['partial_transcript','committed_transcript']:
                            value=str(part.get('text',''))[:4000]
                            if kind=='committed_transcript':
                                if sum(len(t) for t in texts)+len(value)>4000:raise HTTPException(422,'voice_transcript_limit')
                                texts.append(value);index+=1;final.set()
                            await ws.send_json({'type':'final' if kind=='committed_transcript' else 'partial','text':value,'sequence':index})
                            if kind=='committed_transcript' and stopping.is_set():return
                        elif kind not in ['warning','committed_transcript_with_timestamps','edited_transcript']:
                            if kind!='session_started':raise providers.VoiceError('voice_provider_rejected')

                async def watchdog():
                    while True:
                        await asyncio.sleep(.5);await service.live_session(sid,token)
                        if time.monotonic()-start>config['_max_seconds']:
                            raise HTTPException(410,'voice_duration_limit')

                tasks=[asyncio.create_task(incoming()),asyncio.create_task(outgoing()),asyncio.create_task(watchdog())]
                done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                for task in done:task.result()
                if stopping.is_set():
                    try:await asyncio.wait_for(asyncio.shield(tasks[1]),3)
                    except TimeoutError:pass
                    success=bool(texts)
                else:raise providers.VoiceError('voice_provider_incomplete')
                for task in tasks:
                    if not task.done():task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
        audio=await service.finish_session(sid,bytes(pcm),' '.join(texts),min(time.monotonic()-start,config['_max_seconds']+20),success,contacted)
        finished=True
        await ws.send_json({'type':'done','session_id':str(sid),'audio_id':audio,'text':' '.join(texts),'complete':success})
    except (WebSocketDisconnect,asyncio.CancelledError):
        pass
    except Exception as exc:
        if accepted:
            code=str(exc.detail) if isinstance(exc,HTTPException) else (exc.code if isinstance(exc,providers.VoiceError) else 'voice_failed')
            try:await ws.send_json({'type':'error','error_code':code})
            except Exception:pass
    finally:
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        # Also finalize on disconnect/error; otherwise a lost tab keeps spend
        # reserved/running forever or a microphone stream survives its owner.
        if claimed and not finished:
            try:await service.finish_session(sid,b'','',max(0,time.monotonic()-start),False,contacted)
            except Exception:pass
        try:await ws.close(code=1000 if success else 1008)
        except Exception:pass
