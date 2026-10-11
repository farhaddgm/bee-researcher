"""Small paid capability probe, only with explicit server-side account setup.

Uses synthetic text and returns only capability metadata. It never enables
the feature or claims that an automatic transcript proves voice quality.
"""
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.news_voice import providers
from app.news_voice.schemas import Voice


async def probe(args):
    # No network request is made unless a valid server secret is available.
    providers.key()
    v=Voice(voice_id=args.voice_id,label='Account probe',model_id=args.model,transport=args.transport,
        languages=[args.language],timing=args.timing,usd_per_1000_chars=args.usd_per_1000_chars)
    phrase={'fa':'این یک آزمون مصنوعی است. پروژه بی در سال ۲۰۲۶ پژوهش می‌کند.',
        'en':'This is a synthetic test. Bee researches published news in 2026.'}.get(args.language)
    if not phrase:raise ValueError('probe supports fa and en; verify other languages separately')
    started=time.monotonic();first=None
    async def chunk(pcm):
        nonlocal first
        if first is None:first=time.monotonic()-started
    pcm,timing=await asyncio.wait_for((providers.http_tts if v.transport=='http' else providers.ttd_tts)(
        phrase,v,args.language,args.zero_retention,on_chunk=chunk),30)
    elapsed=time.monotonic()-started
    committed=''
    async with providers.scribe(args.language,False,(),args.zero_retention) as ws:
        for offset in range(0,len(pcm),6400):
            part=pcm[offset:offset+6400]
            await ws.send(providers.audio_chunk(part,offset+6400>=len(pcm)))
            await asyncio.sleep(len(part)/32000)
        async with asyncio.timeout(10):
            async for raw in ws:
                event=json.loads(raw)
                if event.get('message_type')=='warning' and args.zero_retention:raise ValueError('zero retention unavailable')
                if event.get('message_type')=='committed_transcript':
                    committed=str(event.get('text',''));break
    if not committed.strip():raise ValueError('empty STT result')
    if args.language=='fa' and not any('\u0600'<=c<='\u06ff' for c in committed):raise ValueError('Persian transcript not returned')
    exact=''.join(c['text'] for c in timing)==phrase
    return {'at':datetime.now(timezone.utc).isoformat(),'model':v.model_id,'transport':v.transport,
        'language':args.language,'voice_id':v.voice_id,'format':'pcm_16000','duration_seconds':len(pcm)/32000,
        'first_audio_seconds':first,'tts_seconds':elapsed,'timing_matches_spoken_text':exact,'stt_nonempty':True,
        'synthetic_sample':True,'quality_review_required':True,'enabled':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--voice-id',required=True);p.add_argument('--model',default='eleven_v3')
    p.add_argument('--transport',choices=['http','ttd'],default='http');p.add_argument('--language',choices=['fa','en'],default='fa')
    p.add_argument('--usd-per-1000-chars',required=True);p.add_argument('--timing',action='store_true')
    p.add_argument('--zero-retention',action='store_true');p.add_argument('--confirm-paid-sample',action='store_true')
    args=p.parse_args()
    if not args.confirm_paid_sample:p.error('--confirm-paid-sample required; this uses billable STT/TTS')
    try:print(json.dumps(asyncio.run(probe(args)),sort_keys=True))
    except Exception:
        # A provider/network exception may contain headers or a raw response.
        print(json.dumps({'verified':False,'error':'account_probe_failed_or_unconfigured','enabled':False}))
        raise SystemExit(1)


if __name__=='__main__':main()
