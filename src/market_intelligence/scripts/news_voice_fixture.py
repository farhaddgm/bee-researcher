"""Synthetic PCM and provider wire behaviour. Test database only; no network."""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import math
from pathlib import Path
import secrets
import struct
import tempfile
from pydantic import SecretStr
from app.config import get_settings
from app.database import SessionLocal
from app.news_voice import providers, service
from app.news_voice.models import VoicePolicy
from app.news_voice.schemas import Policy,Voice


settings=get_settings()
if settings.environment!='test' or settings.postgres_db!='news_chat_test':
    raise RuntimeError('Isolated voice fixture required')


def configure():
    root=Path(tempfile.mkdtemp(prefix='bee-voice-fixture-'))
    key=root/'keyring.json'
    key.write_text(json.dumps({'active':'fixture','keys':{'fixture':base64.b64encode(secrets.token_bytes(32)).decode()}}))
    key.chmod(0o600)
    settings.news_voice_enabled=True
    settings.news_voice_keyring_file=str(key)
    settings.news_voice_storage_path=str(root/'audio')
    settings.elevenlabs_api_key=SecretStr('synthetic-elevenlabs-not-a-real-key')
    providers.http_tts=fake_tts
    providers.ttd_tts=fake_tts
    providers.scribe=fake_scribe


async def seed():
    voice=Voice(voice_id='syntheticvoice001',label='Synthetic PCM test voice',languages=['fa','en','tr','ar','es','it','de','fr'],
        verified=True,timing=True,usd_per_1000_chars='0.05')
    p=Policy(enabled=True,stt_verified=True,continuous_enabled=True,voices=[voice],
        price_reference='Synthetic fixture price; never a production tariff',price_expires_at=service.now()+timedelta(days=1))
    async with SessionLocal() as s:
        row=await s.get(VoicePolicy,1)
        if not row:row=VoicePolicy(id=1,config={});s.add(row)
        row.config=p.model_dump(mode='json');await s.commit()


PCM=b''.join(struct.pack('<h',round(math.sin(i*2*math.pi*440/16000)*2400)) for i in range(48000))


async def fake_tts(text,voice,language,zero_retention=False,on_chunk=None):
    if any(v in text for v in ['INTERNAL BUSINESS SECRET','INTERNAL FULL ORIGINAL','PREGENERATED_','PEER_MEMORY_CANARY']):
        raise RuntimeError('Private context crossed the voice prompt boundary')
    for i in range(0,len(PCM),6400):
        if on_chunk:await on_chunk(PCM[i:i+6400])
        await asyncio.sleep(.06)
    size=max(1,len(text))
    return PCM,[{'text':c,'start':i*3/size,'end':(i+1)*3/size} for i,c in enumerate(text)]


class Scribe:
    def __init__(self,continuous):
        self.queue=asyncio.Queue();self.bytes=0;self.continuous=continuous;self.emitted=False
        self.queue.put_nowait(json.dumps({'message_type':'session_started'}))

    async def send(self,raw):
        value=json.loads(raw)
        assert value['message_type']=='input_audio_chunk' and value['sample_rate']==16000
        audio=base64.b64decode(value['audio_base_64'],validate=True)
        assert len(audio)%2==0
        self.bytes+=len(audio)
        await self.queue.put(json.dumps({'message_type':'partial_transcript','text':'Synthetic speech'}))
        if (value['commit'] or (self.continuous and self.bytes>=16000)) and not self.emitted:
            self.emitted=True
            await self.queue.put(json.dumps({'message_type':'committed_transcript','text':'Synthetic speech about published batteries.'}))
    def __aiter__(self):return self
    async def __anext__(self):return await self.queue.get()


@asynccontextmanager
async def fake_scribe(language,continuous,keyterms,zero_retention):
    yield Scribe(continuous)
