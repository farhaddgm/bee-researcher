"""Incremental speech, immediate erasure, recovery and dated rates."""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from pydantic import ValidationError
from app.news_voice import backup, incremental, preview, pricing, providers, service
from app.news_voice.schemas import Policy, Voice


class PrefixTests(unittest.TestCase):
    def test_every_token_boundary_preserves_canonical_spoken_text(self):
        for text in ['First sentence. Second [report-1] sentence.',
            '**نخستین جمله.** جمله دوم [report-2].',
            'First. [Source](https://a.invalid/path) second. [laughs] Last sentence.',
            'URL https://example.invalid/a.b next.\nFinal line.']:
            cursor = incremental.Prefix(5000)
            chunks = [cursor.advance(text[:i]) for i in range(len(text)+1)]
            chunks.append(cursor.advance(text, final=True))
            self.assertEqual(providers.spoken_text(text), ''.join(chunks))
            self.assertNotIn('http', ''.join(chunks))

    def test_incomplete_tags_limit_and_changed_prefix_fail_closed(self):
        cursor = incremental.Prefix(100)
        self.assertEqual('', cursor.advance('[laughs. '))
        self.assertEqual('First.', cursor.advance('First. Next'))
        with self.assertRaises(providers.VoiceError): cursor.advance('Changed. Next')
        with self.assertRaises(providers.VoiceError): incremental.Prefix(2).advance('Long.', True)

    def test_standard_rates_exclude_expired_promotion_and_round_keyterms_up(self):
        self.assertEqual(Decimal('0.0065'), pricing.STT_PER_MINUTE)
        self.assertGreaterEqual(pricing.STT_PER_MINUTE * pricing.KEYTERMS_MULTIPLIER, Decimal('0.47') / 60)
        self.assertEqual(Decimal('.08'), pricing.TTS_PER_1000['eleven_v4'])
        self.assertEqual(Decimal('.04'), pricing.TTS_PER_1000['eleven_v4_turbo'])
        self.assertFalse(pricing.snapshot()['expired_promotions_included'])

    def test_zero_retention_requires_account_evidence_and_budget_is_bounded(self):
        voice=Voice(voice_id='syntheticvoice001',label='Synthetic',languages=['fa'],verified=True,usd_per_1000_chars='.08')
        value=dict(enabled=True,stt_verified=True,voices=[voice],price_reference=pricing.SOURCE,
            price_expires_at=service.now()+timedelta(days=1),require_zero_retention=True)
        p=Policy(**value)
        with patch.object(service,'configured',return_value=True),patch.object(service,'get_settings',return_value=SimpleNamespace(news_voice_enabled=True)),patch('app.news_voice.credentials.managed',return_value=None):
            with self.assertRaises(HTTPException) as caught:service.enabled(p)
            self.assertEqual('voice_retention_unavailable',caught.exception.detail)
        self.assertTrue(Policy(**value,zero_retention_verified=True,retention_reference='Synthetic account evidence').enabled)
        with self.assertRaises(ValidationError): Policy(daily_budget_usd=1,user_daily_budget_usd=2)


class IncrementalTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_arrives_while_llm_is_still_generating(self):
        final=asyncio.Event();first=asyncio.Event();chunks=[]
        voice=Voice(voice_id='syntheticvoice001',label='Synthetic',languages=['en'],usd_per_1000_chars='.08')
        async def parts():
            yield 'First sentence.'
            await final.wait()
            yield ' Final sentence.'
        async def tts(text,voice,language,zero_retention=False,on_chunk=None):
            pcm=b'\x00\x10'*100
            await on_chunk(pcm)
            return pcm,[{'text':text,'start':0,'end':.00625}]
        async def chunk(pcm):chunks.append(pcm);first.set()
        with patch.object(providers,'http_tts',tts):
            task=asyncio.create_task(incremental.synthesize(parts(),voice,'en',on_chunk=chunk))
            await asyncio.wait_for(first.wait(),1)
            self.assertFalse(task.done());self.assertFalse(final.is_set())
            final.set();pcm,timing=await task
        self.assertEqual(b''.join(chunks),pcm)
        self.assertEqual('First sentence. Final sentence.',''.join(c['text'] for c in timing))
        self.assertEqual(.00625,timing[1]['start'])

    async def test_no_provider_charge_before_any_committed_text(self):
        async def empty():
            if False:yield ''
        voice=Voice(voice_id='syntheticvoice001',label='Synthetic',languages=['en'],usd_per_1000_chars='.08')
        contacted=[]
        with patch.object(providers,'http_tts',AsyncMock()) as upstream:
            with self.assertRaises(providers.VoiceError):
                await incremental.synthesize(empty(),voice,'en',on_contact=lambda:contacted.append(True))
            upstream.assert_not_awaited()
        self.assertFalse(contacted)

    async def test_deleted_parent_clears_preview_before_returning(self):
        aid=uuid.uuid4()
        voice=Voice(voice_id='syntheticvoice001',label='Synthetic',languages=['fa'],usd_per_1000_chars='.08')
        row=SimpleNamespace(metadata_json={'_voice':voice.model_dump(mode='json'),'_deadline':(service.now()+timedelta(seconds=5)).isoformat(),
            'spoken_text':'Synthetic.','language':'fa','_zero_retention':False})
        session=SimpleNamespace(get=AsyncMock(return_value=None))
        @asynccontextmanager
        async def database():yield session
        async def tts(*args,on_chunk=None):
            await on_chunk(b'\x00\x10'*100);return b'\x00\x10'*100,[]
        with patch.object(service,'producer_live',side_effect=[row,HTTPException(410,'voice_audio_cancelled')]), \
                patch.object(service,'SessionLocal',database),patch.object(service,'lock',AsyncMock()),patch.object(providers,'http_tts',tts):
            await service.generate(aid)
        self.assertNotIn(aid,preview.buffers)

    async def test_settlement_failure_and_cancel_clear_preview(self):
        for error in (RuntimeError('synthetic database unavailable'), asyncio.CancelledError()):
            aid=uuid.uuid4()
            async def operation(_):
                preview.start(aid);await preview.append(aid,b'\x00\x10'*100)
                raise error
            with patch.object(service,'_generate',operation):
                with self.assertRaises(type(error)):await service.generate(aid)
            self.assertNotIn(aid,preview.buffers)


class BackupTests(unittest.TestCase):
    def test_independent_key_authenticated_restore_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);keyring=root/'keyring.json';recovery=root/'recovery.key'
            keyring.write_text(json.dumps({'active':'v1','keys':{'v1':base64.b64encode(b'a'*32).decode()}}));keyring.chmod(0o600)
            recovery.write_bytes(b'b'*32);recovery.chmod(0o600)
            settings=SimpleNamespace(news_voice_storage_path=str(root/'state'),news_voice_keyring_file=str(keyring))
            dump=root/'database.dump';dump.write_bytes(b'SYNTHETIC_DATABASE');dump.chmod(0o600)
            with patch.object(backup,'get_settings',return_value=settings):
                result=backup.create(root/'backup.aead',recovery,dump)
            self.assertTrue(result['independent_recovery_key'])
            encrypted=(root/'backup.aead').read_bytes()
            self.assertNotIn(b'SYNTHETIC_DATABASE',encrypted);self.assertNotIn(keyring.read_bytes(),encrypted)
            restored=backup.restore(root/'backup.aead',recovery,root/'restored')
            self.assertTrue(restored['wav_roundtrip_verified'])
            self.assertEqual(dump.read_bytes(),(root/'restored/database.dump').read_bytes())
            damaged=bytearray(encrypted);damaged[-1]^=1;(root/'backup.aead').write_bytes(damaged)
            with self.assertRaises(InvalidTag):backup.restore(root/'backup.aead',recovery,root/'rejected')
            self.assertFalse((root/'rejected').exists())
            recovery.write_bytes(b'a'*32)
            with patch.object(backup,'get_settings',return_value=settings):
                with self.assertRaises(ValueError):backup.create(root/'bad-backup.aead',recovery)
