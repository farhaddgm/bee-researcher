import json
import re
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import accounts, google_auth
from app.auth_deployment import check_account_deployment
from app.admin import LoginRequest, _account_session_lifetime
from app.main import app, settings


class AccountContracts(unittest.TestCase):
    def test_production_gate_runs_before_any_migration(self):
        from pydantic import SecretStr
        production = settings.model_copy(update={"environment": "production", "domain": "researcher.example",
            "google_client_id": None, "google_client_secret": None, "google_redirect_uri": None})
        with self.assertRaises(ValueError):
            check_account_deployment(production)
        configured = production.model_copy(update={"google_client_id": "fixture.apps.googleusercontent.com",
            "google_client_secret": SecretStr("synthetic"), "google_redirect_uri": "https://researcher.example/auth/google/callback"})
        check_account_deployment(configured)
        for value in ("http://researcher.example/auth/google/callback", "https://contenter.example/auth/google/callback", "https://researcher.example/wrong"):
            with self.assertRaises(ValueError):
                check_account_deployment(configured.model_copy(update={"google_redirect_uri": value}))
        check_account_deployment(production.model_copy(update={"environment": "test"}))

    def test_password_identifier_accepts_email_and_legacy_username(self):
        self.assertEqual("a@gmail.com", LoginRequest(email="a@gmail.com", password="password").username)
        self.assertEqual("old-user", LoginRequest(username="old-user", password="password").username)

    def test_methods_are_consistent(self):
        base = {"email": "Some.Body+work@googlemail.com", "display_name": "Name"}
        self.assertEqual("somebody@gmail.com", accounts.AccountCreate(**base).email)
        for values in ({"login_method": "both"}, {"password": "a-password"},
                       {"email": "name@company.com"}, {"display_name": "   "}):
            with self.assertRaises(ValidationError):
                accounts.AccountCreate(**{**base, **values})
        self.assertEqual("password", accounts.AccountCreate(**base, login_method="password", password="password").login_method)

    def test_thirty_day_lifetime_is_bounded(self):
        self.assertEqual(30, _account_session_lifetime().days)
        with patch("app.admin.get_settings", return_value=type("S", (), {"account_session_ttl_days": 99})()):
            self.assertEqual(30, _account_session_lifetime().days)

    def test_auth_mode_is_server_rendered_for_both_portals(self):
        with TestClient(app) as client:
            for portal in ("admin", "user"):
                body = client.get("/" + portal).text
                self.assertIn('data-login-mode="google"', body)
                self.assertIn('body[data-login-mode="google"] #loginForm{display:none!important}', body)
                self.assertNotIn('id="google-login-layer"', body)
                self.assertNotIn('id="google-access-layer"', body)
                self.assertEqual(1, body.count('id="account-access-controller"'))
                self.assertIn('data-login-mode="password"', client.get('/' + portal + '/login-up').text)
                self.assertIn('noindex', client.get('/' + portal + '/login-up').headers['x-robots-tag'])

    def test_shared_catalog_covers_every_language(self):
        js = Path(__file__).parents[1].joinpath('app/auth_portal.js').read_text()
        rows = re.findall(r'^\s+\w+:\[(.*?)\],?$', js, re.M)
        self.assertGreater(len(rows), 50)
        for row in rows:
            values = re.findall(r"'((?:\\.|[^'])*)'", row)
            self.assertEqual(8, len(values), row)
            self.assertTrue(all(values))

    def test_redirects_cannot_switch_host_or_portal(self):
        for path in ('//evil.com', 'https://evil.com', '/user', '/admin/api/users', '/admin\\evil', '/admin\n'):
            self.assertEqual('/admin', google_auth.safe_redirect('admin', path))
        self.assertEqual('/admin?view=sources', google_auth.safe_redirect('admin', '/admin?view=sources'))
        self.assertEqual('/user/settings', google_auth.safe_redirect('user', '/user/settings'))


class GoogleSignatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = settings.model_copy(update={"google_client_id": "account-fixture.apps.googleusercontent.com"})
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwk['kid'] = 'account-fixture'
        google_auth._JWKS_CACHE.update(keys=[], until=0.0)
        self.claims = {'iss': 'https://accounts.google.com', 'aud': self.config.google_client_id,
            'iat': int(time.time()), 'exp': int(time.time()) + 300, 'sub': 'fixture',
            'email': 'fixture@gmail.com', 'email_verified': True, 'nonce': 'fixture-nonce'}
        self.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'keys': [self.jwk]}))

    async def test_valid_signature_is_accepted(self):
        token = jwt.encode(self.claims, self.key, algorithm='RS256', headers={'kid': self.jwk['kid']})
        decoded = await google_auth.verify_id_token(self.config, token, transport=self.transport)
        self.assertEqual('fixture', decoded['sub'])

    async def test_unsigned_wrong_key_expired_and_wrong_audience_are_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tokens = [jwt.encode(self.claims, '', algorithm='none', headers={'kid': self.jwk['kid']}),
            jwt.encode(self.claims, other, algorithm='RS256', headers={'kid': self.jwk['kid']}),
            jwt.encode({**self.claims, 'exp': int(time.time()) - 300}, self.key, algorithm='RS256', headers={'kid': self.jwk['kid']}),
            jwt.encode({**self.claims, 'aud': 'other'}, self.key, algorithm='RS256', headers={'kid': self.jwk['kid']})]
        for token in tokens:
            with self.assertRaises(google_auth.GoogleAuthError):
                await google_auth.verify_id_token(self.config, token, transport=self.transport)

    async def test_key_endpoint_failure_fails_closed(self):
        token = jwt.encode(self.claims, self.key, algorithm='RS256', headers={'kid': self.jwk['kid']})
        with self.assertRaises(google_auth.GoogleAuthError):
            await google_auth.verify_id_token(self.config, token, transport=httpx.MockTransport(lambda r: httpx.Response(503)))

    def test_nonce_and_unverified_email_cannot_be_bypassed(self):
        with self.assertRaises(google_auth.GoogleAuthError):
            google_auth.identity_from_claims(self.config, {**self.claims, 'nonce': 'different'}, 'fixture-nonce')
        identity = google_auth.identity_from_claims(self.config, {**self.claims, 'email_verified': 1}, 'fixture-nonce')
        self.assertFalse(identity.email_verified)
