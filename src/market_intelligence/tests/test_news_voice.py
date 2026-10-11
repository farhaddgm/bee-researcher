"""Provider contracts, private media integrity, consent and capability gates."""
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
import uuid
from urllib.parse import parse_qs,urlsplit
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr,ValidationError
from cryptography.exceptions import InvalidTag
from app.config import Settings
from app.main import app
from app.news_voice import gateway,preview,providers,service,storage
from app.news_voice.schemas import Bookmark,Playback,Policy,Save,Start,Voice


def voice(**changes):
    return Voice(voice_id='testvoice001',label='Test',languages=['fa','en'],usd_per_1000_chars='.1',**changes)


class VoiceValidationTests(unittest.TestCase):
    def test_consent_and_real_recording_are_separate_and_required(self):
        with self.assertRaises(ValidationError):Start(idempotency_key=uuid.uuid4().hex)
        p=Start(idempotency_key=uuid.uuid4().hex,transfer_consent=True)
        self.assertFalse(p.retain_user_audio_for_save);self.assertFalse(p.continuous)
        with self.assertRaises(ValidationError):Start(**{**p.model_dump(),'transfer_consent':False})
        with self.assertRaises(ValidationError):Start(**{**p.model_dump(),'keyterms':['x']*51})

    def test_enable_requires_price_and_account_verification(self):
        with self.assertRaises(ValidationError):Policy(enabled=True,voices=[voice(verified=True)])
        p=Policy(enabled=True,voices=[voice(verified=True)],stt_verified=True,
            price_reference='Account tariff reference',price_expires_at=service.now()-timedelta(seconds=1))
        # Expired stored policies can be read/disabled, but never produce audio.
        with patch.object(service,'get_settings',return_value=SimpleNamespace(news_voice_enabled=True)),patch.object(service,'configured',return_value=True):
            with self.assertRaises(HTTPException) as caught:service.enabled(p)
            self.assertEqual('voice_price_expired',caught.exception.detail)
        with self.assertRaises(ValidationError):voice(model_id='eleven_v4',transport='http')

    def test_snapshot_requires_explicit_text_retention_and_valid_distinct_ranges(self):
        aid=uuid.uuid4();base={'idempotency_key':uuid.uuid4().hex,'title':'Snapshot','retain_conversation':True}
        for selections in [[{'asset_id':aid,'start_seconds':1}],[{'asset_id':aid,'start_seconds':2,'end_seconds':1}],[{'asset_id':aid}]*2]:
            with self.assertRaises(ValidationError):Save(**base,selections=selections)
        with self.assertRaises(ValidationError):Save(**{**base,'retain_conversation':False},selections=[{'asset_id':aid}])
        with self.assertRaises(ValidationError):Bookmark(version=0,seconds=0,label='  ')
        with self.assertRaises(ValidationError):Playback(played_seconds=1,played_ranges=[(0,float('nan'))])

    def test_provider_expression_tags_and_hidden_citations_are_not_spoken(self):
        self.assertEqual('Published words Source',providers.spoken_text('**Published** words [report-1] [laughs] [Source](https://a.invalid) https://private.invalid'))
        self.assertEqual([],providers.alignment({'characters':['a'],'character_start_times_seconds':[float('nan')],'character_end_times_seconds':[1]}))

    def test_wrong_origin_is_rejected(self):
        cfg=Settings(environment='production',domain='reader.invalid')
        with patch.object(gateway,'get_settings',return_value=cfg):
            self.assertTrue(gateway.origin_allowed(SimpleNamespace(headers={'origin':'https://reader.invalid'})))
            for origin in ['','http://reader.invalid','https://evil.invalid']:
                self.assertFalse(gateway.origin_allowed(SimpleNamespace(headers={'origin':origin})))

    def test_invalid_voice_payload_is_never_echoed(self):
        client=TestClient(app)
        response=client.post('/user/api/conversations/'+str(uuid.uuid4())+'/audio-saves',
            json={'title':'PRIVATE_VOICE_CANARY','scope':'bad','unexpected':'secret'})
        self.assertNotIn('PRIVATE_VOICE_CANARY',response.text)
        self.assertNotIn('secret',response.text)


class VoiceStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name);self.key=root/'keyring.json';self.rawkey=base64.b64encode(b'a'*32).decode()
        self.key.write_text(json.dumps({'active':'v1','keys':{'v1':self.rawkey}}));self.key.chmod(0o600)
        self.cfg=SimpleNamespace(news_voice_storage_path=str(root/'voice'),news_voice_keyring_file=str(self.key))
        self.store=storage.Store(self.cfg)
        self.a=SimpleNamespace(id=uuid.uuid4(),user_id=uuid.uuid4(),assistant_id=uuid.uuid4())
        self.data=storage.wav(b'\x01\x02'*16000)
        self.a.object_key,self.a.sha256=self.store.write(self.a,self.data);self.a.byte_count=len(self.data)
    def tearDown(self):self.temp.cleanup()

    def test_real_wav_encrypted_at_rest_and_downloadable_without_resynthesis(self):
        self.assertEqual(self.data,self.store.read(self.a))
        encrypted=self.store.path(self.a.object_key).read_bytes()
        self.assertNotIn(self.data,encrypted)
        self.assertEqual(b'\x01\x02'*16000,storage.pcm(self.data))
        self.assertEqual(0o600,self.store.path(self.a.object_key).stat().st_mode&0o777)

    def test_ciphertext_cannot_be_transferred_to_another_user_project_or_asset(self):
        for field in ['user_id','assistant_id','id']:
            other=SimpleNamespace(**{**vars(self.a),field:uuid.uuid4()})
            with self.assertRaises(InvalidTag):self.store.read(other)

    def test_key_rotation_reads_old_files_and_tampering_fails(self):
        self.key.write_text(json.dumps({'active':'v2','keys':{'v1':self.rawkey,'v2':base64.b64encode(b'b'*32).decode()}}))
        self.assertEqual(self.data,storage.Store(self.cfg).read(self.a))
        path=self.store.path(self.a.object_key);damaged=bytearray(path.read_bytes());damaged[-1]^=1;path.write_bytes(damaged)
        with self.assertRaises(InvalidTag):self.store.read(self.a)

    def test_storage_paths_keys_and_truncated_pcm_are_fail_closed(self):
        with self.assertRaises(ValueError):self.store.path('../private')
        self.key.chmod(0o644)
        with self.assertRaises(ValueError):storage.Store(self.cfg)
        with self.assertRaises(ValueError):storage.wav(b'odd')
        with self.assertRaises(ValueError):storage.pcm(self.data[:-2])


class VoiceWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_pcm_stream_fixed_host_and_no_retry_or_redirect(self):
        requests=[];chunks=[];pcm=b'\x00\x10'*500
        class Wire(httpx.AsyncByteStream):
            async def __aiter__(self):yield pcm[:777];yield pcm[777:]
        def respond(request):
            requests.append(request);return httpx.Response(200,stream=Wire())
        client=httpx.AsyncClient
        def factory(**kwargs):
            self.assertFalse(kwargs['follow_redirects']);self.assertFalse(kwargs['trust_env'])
            return client(**kwargs,transport=httpx.MockTransport(respond))
        async def chunk(value):chunks.append(value)
        with patch.object(providers,'key',return_value='TEST_ONLY'),patch.object(providers.httpx,'AsyncClient',side_effect=factory):
            raw,timing=await providers.http_tts('Published text',voice(),'fa',True,on_chunk=chunk)
        self.assertEqual(pcm,raw);self.assertEqual(raw,b''.join(chunks));self.assertFalse(timing);self.assertEqual(1,len(requests))
        req=requests[0];self.assertEqual('api.elevenlabs.io',req.url.host)
        self.assertEqual('/v1/text-to-speech/testvoice001/stream',req.url.path)
        self.assertEqual('pcm_16000',req.url.params['output_format']);self.assertEqual('false',req.url.params['enable_logging'])
        self.assertEqual('fa',json.loads(req.content)['language_code'])

    async def test_timing_transport_and_provider_errors_are_sanitized(self):
        client=httpx.AsyncClient
        def factory(**kwargs):return client(**kwargs,transport=httpx.MockTransport(lambda r:httpx.Response(429,text='PRIVATE_REMOTE_BODY_TEST_ONLY')))
        with patch.object(providers,'key',return_value='TEST_ONLY'),patch.object(providers.httpx,'AsyncClient',side_effect=factory):
            with self.assertRaises(providers.VoiceError) as exc:await providers.http_tts('text',voice(timing=True),'fa')
        self.assertEqual('voice_provider_rejected',str(exc.exception))

    async def test_scribe_uses_pcm_manual_commit_and_keyterms_with_server_header(self):
        captured=[]
        @asynccontextmanager
        async def ws(url,**kwargs):captured.append((url,kwargs));yield object()
        with patch.object(providers,'key',return_value='TEST_ONLY'),patch.object(providers,'connect',side_effect=ws):
            async with providers.scribe('fa',False,['Bee','پروژه'],True):pass
        url,options=captured[0];self.assertEqual('api.elevenlabs.io',urlsplit(url).hostname)
        query=parse_qs(urlsplit(url).query);self.assertEqual(['manual'],query['commit_strategy']);self.assertEqual(['Bee','پروژه'],query['keyterms'])
        self.assertEqual(['pcm_16000'],query['audio_format']);self.assertIsNone(options['proxy'])
        frame=json.loads(providers.audio_chunk(b'\x00\x01',True));self.assertEqual('input_audio_chunk',frame['message_type'])
        self.assertEqual(b'\x00\x01',base64.b64decode(frame['audio_base_64']));self.assertTrue(frame['commit'])

    async def test_dialogue_wire_requires_final_message_before_marking_audio_complete(self):
        pcm=b'\x01\x02'*100;text='Published words '*30
        for complete in (True,False):
            sent=[];captured=[];chunks=[]
            class Socket:
                async def send(self,raw):sent.append(json.loads(raw))
                async def messages(self):
                    yield json.dumps({'audio':base64.b64encode(pcm).decode()})
                    yield json.dumps({'is_final_audio_for_turn':True})
                    if complete:yield json.dumps({'is_final':True})
                def __aiter__(self):return self.messages()
            @asynccontextmanager
            async def ws(url,**kwargs):captured.append((url,kwargs));yield Socket()
            async def chunk(raw):chunks.append(raw)
            with patch.object(providers,'key',return_value='TEST_ONLY'),patch.object(providers,'connect',side_effect=ws):
                if complete:
                    raw,timing=await providers.ttd_tts(text,voice(transport='ttd',model_id='eleven_v3_conversational'),'fa',True,on_chunk=chunk)
                    self.assertEqual(pcm,raw);self.assertEqual(raw,b''.join(chunks));self.assertEqual([],timing)
                else:
                    with self.assertRaises(providers.VoiceError) as exc:
                        await providers.ttd_tts(text,voice(transport='ttd',model_id='eleven_v3_conversational'),'fa')
                    self.assertEqual('voice_provider_incomplete',exc.exception.code)
            url,options=captured[0];query=parse_qs(urlsplit(url).query)
            self.assertEqual('/v1/text-to-dialogue/stream-input',urlsplit(url).path)
            self.assertEqual(['pcm_16000'],query['output_format']);self.assertEqual(['eleven_v3_conversational'],query['model_id'])
            self.assertEqual({'xi-api-key':'TEST_ONLY'},options['additional_headers']);self.assertIsNone(options['proxy'])
            self.assertEqual({'voices':['testvoice001']},sent[0]);self.assertEqual([{'flush':True},{'close_socket':True}],sent[-2:])
            self.assertEqual(text,''.join(part['text'] for event in sent if 'inputs' in event for part in event['inputs']))

    async def test_unauthorized_socket_never_finalizes_or_refunds_another_session(self):
        ws=SimpleNamespace(headers={'origin':'http://local','host':'local'},cookies={},close=AsyncMock(),accept=AsyncMock())
        with patch.object(gateway,'origin_allowed',return_value=True),patch.object(service,'live_session',side_effect=HTTPException(404)),patch.object(service,'finish_session',new_callable=AsyncMock) as finish:
            await gateway.run(ws,uuid.uuid4());finish.assert_not_awaited();ws.accept.assert_not_awaited()

    async def test_preview_is_bounded_and_disposable(self):
        aid=uuid.uuid4();preview.start(aid)
        await preview.append(aid,b'\x00\x01'*12000)
        self.assertEqual(24000,preview.buffers[aid].size);self.assertTrue(all(len(c)<=16000 for c in preview.buffers[aid].chunks))
        preview.finish(aid);preview.remove(aid);self.assertNotIn(aid,preview.buffers)
