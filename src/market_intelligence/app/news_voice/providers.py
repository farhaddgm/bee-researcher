"""Fixed-host ElevenLabs wire contracts; no SDK, client key or blind retry."""
import base64
import json
import math
import re
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlencode
import httpx
from websockets.asyncio.client import connect
from app.config import get_settings
from app.news_voice.storage import MAX_BYTES


class VoiceError(Exception):
    def __init__(self,code='voice_provider_failed'):self.code=code;super().__init__(code)


def key():
    s=get_settings()
    from app.news_voice.credentials import managed, CredentialError
    try:
        value=managed(s)
    except CredentialError:
        raise VoiceError('voice_unconfigured') from None
    if value is not None:
        if not value['key']:raise VoiceError('voice_unconfigured')
        return value['key']
    if s.elevenlabs_api_key_file:
        try:
            path=Path(s.elevenlabs_api_key_file)
            if path.is_symlink() or path.stat().st_mode&0o077 or path.stat().st_size>512:raise ValueError()
            value=path.read_text().strip()
            if not 16<=len(value)<=500 or any(c.isspace() for c in value):raise ValueError()
            return value
        except (OSError,ValueError):raise VoiceError('voice_unconfigured') from None
    if not s.elevenlabs_api_key:raise VoiceError('voice_unconfigured')
    return s.elevenlabs_api_key.get_secret_value()


async def catalog(candidate=None, search='', page_token=None):
    """Read-only authentication/catalog check; never synthesize or send audio."""
    secret=candidate or key()
    async def get(client,path,params=None):
        async with client.stream('GET','https://api.elevenlabs.io'+path,params=params,
                headers={'xi-api-key':secret}) as response:
            if response.status_code!=200:
                code={401:'voice_key_invalid',403:'voice_permissions_missing',429:'voice_rate_limited'}.get(
                    response.status_code,'voice_provider_failed')
                raise VoiceError(code)
            data=bytearray()
            async for part in response.aiter_bytes():
                data.extend(part)
                if len(data)>1_000_000:raise VoiceError('voice_provider_invalid')
            try:return json.loads(data)
            except (ValueError,TypeError):raise VoiceError('voice_provider_invalid') from None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10,connect=5),follow_redirects=False,trust_env=False) as client:
            models=await get(client,'/v1/models')
            params={'page_size':50,'include_total_count':'false'}
            if search:params['search']=search
            if page_token:params['next_page_token']=page_token
            voices=await get(client,'/v2/voices',params)
        if not isinstance(models,list) or not isinstance(voices,dict) or not isinstance(voices.get('voices'),list):
            raise VoiceError('voice_provider_invalid')
        supported={'eleven_v3','eleven_v3_conversational','eleven_v4','eleven_v4_turbo'}
        def safe_id(value):return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value))
        result={'models':[{'id':m['model_id'],'label':str(m.get('name') or m['model_id'])[:100]}
                          for m in models[:200] if isinstance(m,dict) and safe_id(m.get('model_id'))
                          and m['model_id'] in supported and m.get('can_do_text_to_speech') is True],
                'voices':[{'id':v['voice_id'],'label':str(v.get('name') or v['voice_id'])[:100]}
                          for v in voices['voices'][:50] if isinstance(v,dict) and safe_id(v.get('voice_id'))],
                'has_more':voices.get('has_more') is True,
                'next_page_token':voices.get('next_page_token') if isinstance(voices.get('next_page_token'),str)
                    and len(voices['next_page_token'])<=1000 else None,
                'scope':'authentication_and_catalog_only','audio_tested':False}
        return result
    except VoiceError:raise
    except Exception:raise VoiceError('voice_provider_failed') from None


def spoken_text(text):
    text=re.sub(r'\[report-\d+\]','',text)
    text=re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',text)
    text=re.sub(r'https?://\S+','',text)
    text=re.sub(r'\[[^\]\n]{1,100}\]','',text)  # Untrusted v3 expressive tags.
    text=re.sub(r'[*`#_]+','',text)
    return re.sub(r'\s+',' ',text).strip()


def alignment(value,offset=0):
    try:
        chars=value['characters'];starts=value['character_start_times_seconds'];ends=value['character_end_times_seconds']
        if not(len(chars)==len(starts)==len(ends)) or len(chars)>40000:return []
        result=[];previous=0
        for c,start,end in zip(chars,starts,ends):
            if (not isinstance(c,str) or len(c)>4 or not isinstance(start,(int,float)) or
                    not isinstance(end,(int,float)) or not math.isfinite(start) or not math.isfinite(end) or
                    not(0<=start<=end<=600) or start<previous):return []
            result.append({'text':c,'start':offset+start,'end':offset+end});previous=start
        return result
    except (KeyError,TypeError,ValueError):return []


async def http_tts(text,voice,language,zero_retention=False,on_chunk=None):
    suffix='/stream/with-timestamps' if voice.timing else '/stream'
    params={'output_format':'pcm_16000','enable_logging':str(not zero_retention).lower()}
    body={'text':text,'model_id':voice.model_id,'language_code':language}
    if voice.pronunciation_dictionaries:body['pronunciation_dictionary_locators']=voice.pronunciation_dictionaries
    output=bytearray();timing=[];forwarded=0
    async with httpx.AsyncClient(timeout=httpx.Timeout(15,connect=10),follow_redirects=False,trust_env=False) as client:
        async with client.stream('POST','https://api.elevenlabs.io/v1/text-to-speech/'+voice.voice_id+suffix,
                params=params,json=body,headers={'xi-api-key':key()}) as response:
            if response.status_code!=200:raise VoiceError('voice_provider_rejected')
            if voice.timing:
                async for line in response.aiter_lines():
                    if not line.strip():continue
                    if len(line)>2_000_000:raise VoiceError('voice_provider_invalid')
                    try:
                        part=json.loads(line)
                        timing.extend(alignment(part.get('alignment') or {},len(output)/32000))
                        output.extend(base64.b64decode(part['audio_base64'],validate=True))
                    except (ValueError,KeyError,TypeError):raise VoiceError('voice_provider_invalid') from None
                    if len(output)>min(MAX_BYTES-44,600*32000):raise VoiceError('audio_too_large')
                    end=len(output)//2*2
                    if on_chunk and end>forwarded:await on_chunk(bytes(output[forwarded:end]));forwarded=end
            else:
                async for part in response.aiter_bytes():
                    output.extend(part)
                    if len(output)>min(MAX_BYTES-44,600*32000):raise VoiceError('audio_too_large')
                    end=len(output)//2*2
                    if on_chunk and end>forwarded:await on_chunk(bytes(output[forwarded:end]));forwarded=end
    if not output or len(output)%2 or output[:4]==b'RIFF':raise VoiceError('voice_provider_invalid')
    return bytes(output),timing


async def ttd_tts(text,voice,language,zero_retention=False,on_chunk=None):
    params={'model_id':voice.model_id,'output_format':'pcm_16000','language_code':language,
            'sync_alignment':str(voice.timing).lower(),'enable_logging':str(not zero_retention).lower()}
    output=bytearray();timing=[];forwarded=0;terminal=False
    async with connect('wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input?'+urlencode(params),
            additional_headers={'xi-api-key':key()},proxy=None,open_timeout=10,max_size=2_000_000) as ws:
        first={'voices':[voice.voice_id]}
        if voice.pronunciation_dictionaries:first['pronunciation_dictionary_locators']=voice.pronunciation_dictionaries
        await ws.send(json.dumps(first))
        for offset in range(0,len(text),200):
            await ws.send(json.dumps({'inputs':[{'text':text[offset:offset+200],'voice_id':voice.voice_id}]}))
        await ws.send(json.dumps({'flush':True}))
        await ws.send(json.dumps({'close_socket':True}))
        async for raw in ws:
            try:
                part=json.loads(raw)
                if part.get('error'):raise VoiceError('voice_provider_rejected')
                if 'audio' in part:
                    timing.extend(alignment(part.get('alignment') or {},len(output)/32000))
                    output.extend(base64.b64decode(part['audio'],validate=True))
                if len(output)>min(MAX_BYTES-44,600*32000):raise VoiceError('audio_too_large')
                end=len(output)//2*2
                if on_chunk and end>forwarded:await on_chunk(bytes(output[forwarded:end]));forwarded=end
                if part.get('is_final'):terminal=True;break
            except (ValueError,KeyError,TypeError):raise VoiceError('voice_provider_invalid') from None
    if not terminal:raise VoiceError('voice_provider_incomplete')
    if not output or len(output)%2 or output[:4]==b'RIFF':raise VoiceError('voice_provider_invalid')
    return bytes(output),timing


@asynccontextmanager
async def scribe(language,continuous=False,keyterms=(),zero_retention=False):
    params=[('model_id','scribe_v2_realtime'),('audio_format','pcm_16000'),('language_code',language),
            ('commit_strategy','vad' if continuous else 'manual'),('enable_logging',str(not zero_retention).lower())]
    params.extend(('keyterms',s) for s in keyterms)
    async with connect('wss://api.elevenlabs.io/v1/speech-to-text/realtime?'+urlencode(params),
            additional_headers={'xi-api-key':key()},proxy=None,open_timeout=10,max_size=128000,max_queue=8) as ws:
        yield ws


def audio_chunk(pcm,commit=False):
    return json.dumps({'message_type':'input_audio_chunk','audio_base_64':base64.b64encode(pcm).decode(),
                       'sample_rate':16000,'commit':commit})
