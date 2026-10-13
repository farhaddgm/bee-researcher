"""Encrypted write-only credentials, owner authorization and bounded catalogs."""
import base64
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.main import app
from app.news_voice import api, credentials, providers, service
from app.news_voice.schemas import ConnectionCheck, CredentialUpdate, Policy, Voice

KEY = 'synthetic-elevenlabs-key-never-real'


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.keyring = root / 'ring.json'
        self.keyring.write_text(json.dumps({'active':'v1','keys':{'v1':base64.b64encode(b'a'*32).decode()}}))
        self.keyring.chmod(0o600)
        self.cfg = Settings(_env_file=None,news_voice_keyring_file=str(self.keyring),
            news_voice_storage_path=str(root/'voice'),elevenlabs_api_key=SecretStr('synthetic-old-server-key'))
        self.store = credentials.Credentials(self.cfg)

    def tearDown(self):
        self.temp.cleanup()

    def test_key_is_encrypted_private_and_metadata_is_write_only(self):
        value = self.store.update(KEY,'server')
        self.assertTrue(value['configured'])
        self.assertNotIn(KEY,json.dumps(value))
        self.assertNotIn(KEY.encode(),self.store.path.read_bytes())
        self.assertEqual(0o600,self.store.path.stat().st_mode & 0o777)
        self.assertEqual(0o700,self.store.root.stat().st_mode & 0o777)
        self.assertEqual(KEY,self.store.read()['key'])

    def test_all_workers_read_rotation_without_restart_and_delete_blocks_server_fallback(self):
        with patch.object(providers,'get_settings',return_value=self.cfg):
            self.assertEqual('synthetic-old-server-key',providers.key())
            first = self.store.update(KEY,'server')
            self.assertEqual(KEY,providers.key())
            second = self.store.update(KEY+'-rotated',first['revision'])
            self.assertEqual(KEY+'-rotated',providers.key())
            self.store.update('',second['revision'])
            with self.assertRaises(providers.VoiceError):providers.key()

    def test_stale_owner_form_cannot_overwrite_latest_key(self):
        self.store.update(KEY,'server')
        with self.assertRaises(credentials.CredentialError) as caught:self.store.update(KEY+'-new','server')
        self.assertEqual('revision_conflict',caught.exception.code)
        self.assertEqual(KEY,self.store.read()['key'])

    def test_keyring_rotation_retains_old_key_and_tampering_is_fail_closed(self):
        self.store.update(KEY,'server')
        self.keyring.write_text(json.dumps({'active':'v2','keys':{'v1':base64.b64encode(b'a'*32).decode(),'v2':base64.b64encode(b'b'*32).decode()}}))
        self.assertEqual(KEY,credentials.Credentials(self.cfg).read()['key'])
        blob=bytearray(self.store.path.read_bytes());blob[-1]^=1;self.store.path.write_bytes(blob)
        with patch.object(providers,'get_settings',return_value=self.cfg):
            with self.assertRaises(providers.VoiceError):providers.key()

    def test_public_permissions_symlinks_and_torn_files_never_fall_back(self):
        self.store.update(KEY,'server');self.store.path.chmod(0o644)
        with self.assertRaises(credentials.CredentialError):self.store.read()
        self.store.path.unlink();self.store.path.symlink_to(self.keyring)
        with patch.object(providers,'get_settings',return_value=self.cfg):
            with self.assertRaises(providers.VoiceError):providers.key()
        self.store.path.unlink();self.store.path.write_bytes(b'BRK1');self.store.path.chmod(0o600)
        with self.assertRaises(credentials.CredentialError):self.store.read()

    def test_atomic_failure_preserves_current_key(self):
        first=self.store.update(KEY,'server')
        with patch.object(credentials.os,'replace',side_effect=OSError('synthetic storage failure')):
            with self.assertRaises(OSError):self.store.update(KEY+'-new',first['revision'])
        self.assertEqual(KEY,self.store.read()['key'])
        self.assertEqual([],list(self.store.root.glob('*.pending')))

    def test_status_has_no_secret_suffix_and_missing_storage_is_explained(self):
        with patch.object(credentials,'get_settings',return_value=self.cfg),patch.object(providers,'get_settings',return_value=self.cfg):
            self.assertEqual('server',credentials.status()['source'])
            self.store.update(KEY,'server')
            state=credentials.status();self.assertEqual('owner',state['source'])
            self.assertNotIn(KEY,json.dumps(state));self.assertNotIn('api_key',state)
        with patch.object(credentials,'get_settings',return_value=Settings(_env_file=None)):
            self.assertFalse(credentials.status()['editable'])

    def test_rotated_key_requires_new_policy_approval_and_binding_is_not_public(self):
        p=Policy(enabled=True,stt_verified=True,voices=[Voice(voice_id='testvoice001',label='Synthetic',languages=['en'],verified=True,usd_per_1000_chars='.1')],
                 price_reference='Synthetic account price',price_expires_at=service.now()+timedelta(days=1))
        saved=self.store.update(KEY,'server');self.cfg.news_voice_enabled=True
        with patch.object(service,'get_settings',return_value=self.cfg),patch.object(service,'configured',return_value=True),patch.object(credentials,'get_settings',return_value=self.cfg):
            with self.assertRaises(HTTPException) as caught:service.enabled(p)
            self.assertEqual('voice_unverified',caught.exception.detail)
            p._credential_revision=saved['revision'];service.enabled(p)
            self.assertNotIn('_credential_revision',p.model_dump())
            self.store.update(KEY+'-new',saved['revision'])
            with self.assertRaises(HTTPException):service.enabled(p)


class CredentialPayloadTests(unittest.TestCase):
    def test_secret_repr_validation_and_delete_are_safe(self):
        payload=CredentialUpdate(action='set',api_key=KEY,expected_revision='server')
        self.assertNotIn(KEY,repr(payload))
        for value in ['short','with spaces in secret','nonascii-秘密-1234567890']:
            with self.assertRaises(ValidationError):CredentialUpdate(action='set',api_key=value,expected_revision='server')
        with self.assertRaises(ValidationError):CredentialUpdate(action='delete',api_key=KEY,expected_revision='server')
        with self.assertRaises(ValidationError):CredentialUpdate(action='set',api_key=KEY,expected_revision='server',endpoint='https://evil.invalid')
        client=TestClient(app)
        for path in ['/admin/api/news-voice/credential','/admin/api/news-voice/connection-check']:
            response=client.request('PUT' if path.endswith('credential') else 'POST',path,json={'api_key':'PRIVATE_SECRET_CANARY','action':'wrong'})
            self.assertNotIn('PRIVATE_SECRET_CANARY',response.text)


class OwnerSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_guard_precedes_storage_or_provider_access(self):
        payload=CredentialUpdate(action='set',api_key=KEY,expected_revision='server')
        with patch.object(api,'owner',side_effect=HTTPException(403,'owner_required')),patch.object(credentials,'Credentials') as store,patch.object(providers,'catalog',new_callable=AsyncMock) as catalog:
            for operation in [api.put_credential(payload),api.connection_check(ConnectionCheck()),api.get_policy()]:
                with self.assertRaises(HTTPException) as caught:await operation
                self.assertEqual(403,caught.exception.status_code)
            store.assert_not_called();catalog.assert_not_awaited()

    async def test_credential_rotation_audits_only_action_and_not_key(self):
        store=SimpleNamespace(update=lambda key,revision:{'configured':True,'source':'owner','revision':'v1','editable':True})
        owner=SimpleNamespace(id=uuid.uuid4())
        with patch.object(api,'owner',new=AsyncMock(return_value=owner)),patch.object(credentials,'Credentials',return_value=store),patch.object(api.admin,'_audit',new_callable=AsyncMock) as audit:
            result=await api.put_credential(CredentialUpdate(action='set',api_key=KEY,expected_revision='server'))
        self.assertNotIn(KEY,json.dumps(result));self.assertEqual({'action':'set'},audit.await_args.kwargs['details'])

    async def test_conflict_is_not_a_generic_success(self):
        store=SimpleNamespace(update=lambda *args:(_ for _ in ()).throw(credentials.CredentialError('revision_conflict')))
        with patch.object(api,'owner',new=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))),patch.object(credentials,'Credentials',return_value=store):
            with self.assertRaises(HTTPException) as caught:await api.put_credential(CredentialUpdate(action='delete',expected_revision='server'))
        self.assertEqual(409,caught.exception.status_code)

    async def test_stale_policy_cannot_approve_a_rotated_provider_key(self):
        p=Policy(enabled=True,stt_verified=True,voices=[Voice(voice_id='testvoice001',label='Synthetic',languages=['en'],verified=True,usd_per_1000_chars='.1')],
                 price_reference='Synthetic account price',price_expires_at=service.now()+timedelta(days=1))
        with patch.object(api,'owner',new=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))),patch.object(service,'configured',return_value=True),patch.object(credentials,'status',return_value={'source':'owner','revision':'new'}),patch.object(api,'SessionLocal') as database:
            with self.assertRaises(HTTPException) as caught:await api.put_policy(p,expected_credential_revision='old')
            self.assertEqual(409,caught.exception.status_code);database.assert_not_called()


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_fixed_hosts_bounded_catalog_no_audio_or_redirect(self):
        seen=[];client=httpx.AsyncClient
        def respond(request):
            seen.append(request)
            data=[{'model_id':'eleven_v3','name':'Model','can_do_text_to_speech':True},{'model_id':'unknown','name':'Unsupported','can_do_text_to_speech':True}] if request.url.path=='/v1/models' else {'voices':[{'voice_id':'testvoice001','name':'Safe voice'}],'has_more':True,'next_page_token':'next'}
            return httpx.Response(200,json=data)
        def factory(**kwargs):
            self.assertFalse(kwargs['follow_redirects']);self.assertFalse(kwargs['trust_env'])
            return client(**kwargs,transport=httpx.MockTransport(respond))
        with patch.object(providers.httpx,'AsyncClient',side_effect=factory):value=await providers.catalog(KEY,'صدا','page')
        self.assertEqual(2,len(seen));self.assertTrue(all(r.method=='GET' and r.url.host=='api.elevenlabs.io' for r in seen))
        self.assertEqual('page',seen[1].url.params['next_page_token']);self.assertEqual('صدا',seen[1].url.params['search'])
        self.assertNotIn(KEY,json.dumps(value));self.assertFalse(value['audio_tested'])
        self.assertEqual(['eleven_v3'],[m['id'] for m in value['models']])

    async def test_provider_errors_do_not_expose_headers_or_remote_body(self):
        client=httpx.AsyncClient
        for code,expected in [(401,'voice_key_invalid'),(403,'voice_permissions_missing'),(429,'voice_rate_limited'),(302,'voice_provider_failed')]:
            def factory(**kwargs):return client(**kwargs,transport=httpx.MockTransport(lambda r:httpx.Response(code,text='PRIVATE_REMOTE_SECRET_CANARY')))
            with patch.object(providers.httpx,'AsyncClient',side_effect=factory):
                with self.assertRaises(providers.VoiceError) as caught:await providers.catalog(KEY)
            self.assertEqual(expected,str(caught.exception))

    async def test_malformed_or_oversized_provider_json_is_rejected(self):
        client=httpx.AsyncClient
        for content in [b'not-json',b'x'*1_000_001,b'{}']:
            def factory(**kwargs):return client(**kwargs,transport=httpx.MockTransport(lambda r:httpx.Response(200,content=content)))
            with patch.object(providers.httpx,'AsyncClient',side_effect=factory):
                with self.assertRaises(providers.VoiceError):await providers.catalog(KEY)


class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_metadata_cannot_claim_zero_retention_or_expose_invoices(self):
        client=httpx.AsyncClient;seen=[]
        def respond(request):
            seen.append(request)
            return httpx.Response(200,json={'tier':'enterprise','status':'active',
                'open_invoices':[{'private':'PRIVATE_INVOICE_CANARY'}],'workspace_id':'PRIVATE_WORKSPACE_CANARY'})
        def factory(**kwargs):
            self.assertFalse(kwargs['follow_redirects']);self.assertFalse(kwargs['trust_env'])
            return client(**kwargs,transport=httpx.MockTransport(respond))
        with patch.object(providers,'key',return_value=KEY),patch.object(providers.httpx,'AsyncClient',side_effect=factory):
            result=await providers.subscription()
        self.assertEqual('enterprise',result['tier']);self.assertTrue(result['zero_retention_candidate'])
        self.assertFalse(result['zero_retention_verified']);self.assertFalse(result['audio_tested'])
        self.assertNotIn('PRIVATE_',json.dumps(result));self.assertNotIn(KEY,json.dumps(result))
        self.assertEqual('https://api.elevenlabs.io/v1/user/subscription',str(seen[0].url))
        self.assertEqual('GET',seen[0].method)

    async def test_missing_permission_and_unknown_metadata_stay_private(self):
        client=httpx.AsyncClient
        for response in [httpx.Response(403,text='PRIVATE_REMOTE_CANARY'),
            httpx.Response(200,json={'tier':'PRIVATE_SECRET_CANARY','status':'PRIVATE_SECRET_CANARY'})]:
            def factory(**kwargs):return client(**kwargs,transport=httpx.MockTransport(lambda _:response))
            with patch.object(providers,'key',return_value=KEY),patch.object(providers.httpx,'AsyncClient',side_effect=factory):
                if response.status_code==403:
                    with self.assertRaises(providers.VoiceError) as caught:await providers.subscription()
                    self.assertEqual('voice_permissions_missing',caught.exception.code)
                else:
                    result=await providers.subscription();self.assertEqual('custom',result['tier'])
                    self.assertEqual('unknown',result['subscription_status']);self.assertNotIn('PRIVATE_',json.dumps(result))
