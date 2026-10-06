"""Regression tests for the access-control, delivery and scheduler fixes."""

import base64
import json
import os
import time
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_SCHEDULER_ENABLED", "false")
os.environ.setdefault("MARKET_INTELLIGENCE_TELEGRAM_POLLING_ENABLED", "false")

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import google_auth
from app.admin import (
    GoogleAccessGrant,
    PrivacySettingsUpdate,
    SourceCreate,
    SourceUpdate,
    ensure_can_manage_account,
    is_owner,
    list_topics,
    merge_workspace_config,
    record_admin_feedback,
    update_business_knowledge,
    BusinessKnowledgeUpdate,
)
from app.config import Settings
from app.fetchers import FetchFailure, SourceFetcher, SourceSpec, validate_connector_binding
from app.main import app
from app.retention import MIN_RETENTION_DAYS, effective_retention_days
from app.runtime import (
    _bootstrap_due,
    _bootstrap_failed,
    _BOOTSTRAP_BACKOFF,
    current_schedule_slots,
    missed_schedule_slots,
)

OWNER_EMAIL = "farhad.dgm@gmail.com"


def settings(**updates) -> Settings:
    base = Settings(postgres_db="t", postgres_user="t", postgres_password="secret", redis_password="secret", _env_file=None)
    return base.model_copy(update=updates) if updates else base


def account(role="viewer", email=None, username=None):
    return SimpleNamespace(id=uuid.uuid4(), username=username or role, role=role, email=email, preferences={}, active=True, login_method="password")


async def allow(_url: str) -> None:
    return None


class OwnershipTest(unittest.TestCase):
    def test_owner_is_identified_only_by_email(self):
        self.assertTrue(is_owner(account("admin", email=OWNER_EMAIL)))
        # Gmail normalisation: dots, +tags and case do not matter.
        self.assertTrue(is_owner(account("viewer", email="Farhad.D.G.M+x@googlemail.com")))
        # Neither the legacy username nor a stored "owner" role is enough.
        self.assertFalse(is_owner(account("admin", username="admin")))
        self.assertFalse(is_owner(account("owner", username="admin")))
        self.assertFalse(is_owner(account("admin", email="someone@gmail.com")))

    def test_owner_email_cannot_be_granted_to_another_account(self):
        with patch("app.admin.SessionLocal") as sessions:
            with self.assertRaises(HTTPException) as ctx:
                import asyncio
                asyncio.run(__import__("app.admin", fromlist=["grant_google_access"]).grant_google_access(
                    GoogleAccessGrant(email="farhad.dgm@gmail.com"), account("admin", email=OWNER_EMAIL)
                ))
            self.assertEqual(422, ctx.exception.status_code)
            sessions.assert_not_called()

    def test_only_owner_manages_gmail_allowlist(self):
        import asyncio
        from app.admin import list_google_access
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(list_google_access(account("admin")))
        self.assertEqual(403, ctx.exception.status_code)


class AccountHierarchyTest(unittest.TestCase):
    def test_lower_role_cannot_manage_peer_or_superior(self):
        project_admin = account("assistant_admin")
        for target in (account("admin"), account("assistant_admin"), account("admin", email=OWNER_EMAIL)):
            with self.assertRaises(HTTPException) as ctx:
                ensure_can_manage_account(project_admin, target)
            self.assertEqual(403, ctx.exception.status_code)
        ensure_can_manage_account(project_admin, account("editor"))
        ensure_can_manage_account(account("admin"), account("assistant_admin"))
        ensure_can_manage_account(account("admin", email=OWNER_EMAIL), account("admin"))

    def test_self_management_is_allowed(self):
        me = account("editor")
        ensure_can_manage_account(me, me)


class WorkspaceConfigTest(unittest.TestCase):
    def test_patch_cannot_overwrite_protected_configuration(self):
        current = {
            "limits": {"max_sources": 10},
            "runtime": {"collection_enabled": True},
            "telegram": {"feedback_channel_id": "-1001234567"},
            "share_links": [{"id": "1"}],
        }
        merged, ignored = merge_workspace_config(current, {
            "limits": {"max_sources": 100},
            "runtime": {"collection_enabled": False},
            "telegram": {"feedback_channel_id": "-1009999999"},
            "sandbox": {"enabled": False},
            "product": "bee_cfo",
            "shortcut_mission": "Track payments",
        })
        self.assertEqual(current["limits"], merged["limits"])
        self.assertEqual(current["runtime"], merged["runtime"])
        self.assertEqual(current["telegram"], merged["telegram"])
        self.assertNotIn("sandbox", merged)
        self.assertNotIn("product", merged)
        self.assertEqual("Track payments", merged["shortcut_mission"])
        self.assertEqual({"limits", "runtime", "telegram", "sandbox", "product"}, ignored)

    def test_unchanged_round_trip_reports_nothing_ignored(self):
        current = {"runtime": {"a": 1}, "telegram": {}}
        _merged, ignored = merge_workspace_config(current, dict(current))
        self.assertEqual(set(), ignored)


class _FakeSession:
    def __init__(self, item):
        self.item = item
        self.committed = False

    async def get(self, *_args, **_kwargs):
        return self.item

    async def commit(self):
        self.committed = True


def _fake_sessionmaker(item):
    session = _FakeSession(item)

    @asynccontextmanager
    async def factory():
        yield session

    return factory, session


class BusinessKnowledgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_saving_knowledge_keeps_telegram_channels_and_share_links(self):
        workspace = SimpleNamespace(config={
            "telegram": {"feedback_channel_id": "-1001234567", "observer_channel_id": "-1007654321"},
            "share_links": [{"id": "1", "token_hash": "abc"}],
        })
        factory, _session = _fake_sessionmaker(workspace)
        with patch("app.admin.SessionLocal", factory), patch("app.admin._require_project_admin", new=AsyncMock(return_value=workspace)), patch("app.admin._audit", new=AsyncMock()):
            await update_business_knowledge(uuid.uuid4(), BusinessKnowledgeUpdate(facts=["fact"]), account("admin"))
        self.assertEqual("-1001234567", workspace.config["telegram"]["feedback_channel_id"])
        self.assertEqual("-1007654321", workspace.config["telegram"]["observer_channel_id"])
        self.assertEqual("abc", workspace.config["share_links"][0]["token_hash"])
        self.assertEqual(["fact"], workspace.config["business_knowledge"]["facts"])


class TopicScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_unscoped_topic_listing_is_owner_only(self):
        with self.assertRaises(HTTPException) as ctx:
            await list_topics(account("viewer"), assistant_id=None)
        self.assertEqual(403, ctx.exception.status_code)


class FeedbackActorTest(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_cannot_impersonate_another_actor(self):
        with self.assertRaises(HTTPException) as ctx:
            await record_admin_feedback(uuid.uuid4(), value="up", note=None, actor_key="farhaadnoroozi", user=account("editor", username="editor"))
        self.assertEqual(403, ctx.exception.status_code)


class RouteTest(unittest.TestCase):
    def test_revoke_other_sessions_route_is_reachable(self):
        # 401 means the literal route ran (no session); 422 was the old bug.
        self.assertEqual(401, TestClient(app).delete("/admin/api/sessions/others").status_code)

    def test_reader_login_shares_the_brute_force_budget(self):
        with patch("app.main.login_attempts_exceeded", new=AsyncMock(return_value=True)), patch("app.main.reader_login", new=AsyncMock()) as login:
            response = TestClient(app).post("/user/api/login", json={"username": "someone", "password": "long-enough-password"})
        self.assertEqual(429, response.status_code)
        login.assert_not_awaited()

    def test_non_owner_cannot_publish_through_the_pipeline(self):
        editor = account("editor")
        with patch("app.main.current_admin", new=AsyncMock(return_value=editor)), patch("app.main.require_workspace_scope", new=AsyncMock()), patch("app.main.run_pipeline", new=AsyncMock(return_value={"status": "completed"})) as run:
            client = TestClient(app)
            self.assertEqual(403, client.post("/pipeline/run", json={"publish": True}).status_code)
            self.assertEqual(403, client.post("/pipeline/manual-publish", json={}).status_code)
            self.assertEqual(200, client.post("/pipeline/run", json={"publish": None}).status_code)
        # A non-owner run never publishes, not even through auto-publish.
        self.assertIs(False, run.await_args.kwargs["publish"])

    def test_owner_manual_publish_sends_exactly_one_item(self):
        owner = account("admin", email=OWNER_EMAIL)
        with patch("app.main.current_admin", new=AsyncMock(return_value=owner)), patch("app.main.require_workspace_scope", new=AsyncMock()), patch("app.main.run_pipeline", new=AsyncMock(return_value={"status": "completed"})) as run:
            self.assertEqual(200, TestClient(app).post("/pipeline/manual-publish", json={}).status_code)
        self.assertEqual(1, run.await_args.kwargs["publish_limit"])
        self.assertTrue(run.await_args.kwargs["publish"])

    def test_owner_with_admin_stored_role_can_edit_topics(self):
        owner = account("admin", email=OWNER_EMAIL)
        with patch("app.main.current_admin", new=AsyncMock(return_value=owner)), patch("app.main.update_topic", new=AsyncMock(return_value={"id": "x"})):
            self.assertEqual(200, TestClient(app).patch(f"/admin/api/topics/{uuid.uuid4()}", json={"enabled": False}).status_code)

    def test_providers_endpoint_reports_google_configuration(self):
        self.assertEqual({"google": False}, TestClient(app).get("/auth/providers").json())

    def test_google_start_moves_to_the_callback_host_first(self):
        from app import main as main_module

        configured = main_module.settings.model_copy(update={"google_redirect_uri": "https://researcher.example.com/auth/google/callback"})
        with patch.object(main_module, "settings", configured):
            response = TestClient(app, base_url="http://legacy.example.com").get("/auth/google/start?portal=user", follow_redirects=False)
        self.assertEqual(302, response.status_code)
        self.assertEqual("https://researcher.example.com/auth/google/start?portal=user", response.headers["location"])

    def test_hidden_password_page_enables_password_mode(self):
        body = TestClient(app).get("/admin/login-up").text
        self.assertIn('data-login-mode="password"', body)
        self.assertIn("googleLoginBtn", TestClient(app).get("/admin").text)


class ConnectorCredentialTest(unittest.IsolatedAsyncioTestCase):
    def test_credential_is_bound_to_adapter_and_provider_host(self):
        cfg = settings()
        validate_connector_binding("x_public", "MARKET_INTELLIGENCE_X_SOURCE_BEARER_TOKEN", "https://api.x.com/2/users/by/username/a", cfg)
        for adapter, ref, url in (
            ("x_public", "X_SOURCE_BEARER_TOKEN", "https://attacker.example/collect"),
            ("x_public", "INSTAGRAM_SOURCE_ACCESS_TOKEN", "https://api.x.com/2/users/by/username/a"),
            ("x_public", "X_SOURCE_BEARER_TOKEN", "http://api.x.com/2/users/by/username/a"),
            ("rss", "X_SOURCE_BEARER_TOKEN", "https://example.com/feed"),
        ):
            with self.assertRaises(ValueError):
                validate_connector_binding(adapter, ref, url, cfg)
        # An owner-approved gateway host is accepted explicitly.
        validate_connector_binding("x_public", "X_SOURCE_BEARER_TOKEN", "https://gw.example.com/x", settings(connector_gateway_hosts="gw.example.com"))

    async def test_redirect_never_carries_the_credential_to_another_host(self):
        seen: list[tuple[str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.url.host, request.headers.get("authorization")))
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(302, headers={"location": "https://attacker.example/steal"})

        fetcher = SourceFetcher(settings(x_source_bearer_token="server-token"), transport=httpx.MockTransport(handler), resolver=allow)
        with self.assertRaises(FetchFailure):
            await fetcher.fetch(SourceSpec(
                source_key="S-X", name="X", homepage_url="https://x.com/a",
                fetch_url="https://api.x.com/2/users/by/username/a", adapter="x_public",
                credential_ref="X_SOURCE_BEARER_TOKEN", max_retries=0,
            ))
        self.assertNotIn("attacker.example", [host for host, _ in seen])

    def test_source_models_validate_urls_and_bindings(self):
        with self.assertRaises(ValidationError):
            SourceUpdate(fetch_url="http://127.0.0.1/admin")
        with self.assertRaises(ValidationError):
            SourceCreate(name="X", homepage_url="https://x.com/a", fetch_url="https://attacker.example/a", adapter="x_public", credential_ref="X_SOURCE_BEARER_TOKEN")


class RetentionTest(unittest.TestCase):
    def test_default_and_explicit_retention(self):
        self.assertEqual((settings().normalized_retention_days, "deployment_default"), effective_retention_days({}))
        self.assertEqual((90, "workspace"), effective_retention_days({"privacy": {"retention_days": 90}}))
        # Legacy stored values below the safety floor are clamped.
        self.assertEqual((MIN_RETENTION_DAYS, "workspace"), effective_retention_days({"privacy": {"retention_days": 1}}))

    def test_retention_floor_is_enforced_by_the_api(self):
        with self.assertRaises(ValidationError):
            PrivacySettingsUpdate(retention_days=7)
        self.assertEqual(30, PrivacySettingsUpdate(retention_days=30).retention_days)


class SchedulerTest(unittest.TestCase):
    slots = ((0, "10:00"),)  # Monday 10:00
    monday = datetime(2026, 9, 28, tzinfo=timezone.utc)

    def at(self, hour, minute):
        return self.monday.replace(hour=hour, minute=minute)

    def test_slot_stays_due_during_the_grace_window(self):
        due = current_schedule_slots(self.at(10, 5), timezone_name="UTC", schedule_slots=self.slots, grace_minutes=10)
        self.assertEqual([self.at(10, 0)], due)
        self.assertEqual([], current_schedule_slots(self.at(10, 5), timezone_name="UTC", schedule_slots=self.slots))
        self.assertEqual([], current_schedule_slots(self.at(10, 10), timezone_name="UTC", schedule_slots=self.slots, grace_minutes=10))

    def test_missed_slots_are_reported_after_the_grace_window(self):
        self.assertEqual([self.at(10, 0)], missed_schedule_slots(self.at(10, 30), timezone_name="UTC", schedule_slots=self.slots, grace_minutes=10, recovery_hours=8))
        self.assertEqual([], missed_schedule_slots(self.at(10, 5), timezone_name="UTC", schedule_slots=self.slots, grace_minutes=10, recovery_hours=8))

    def test_bootstrap_failures_back_off(self):
        key = uuid.uuid4()
        now = self.at(10, 0)
        self.assertTrue(_bootstrap_due(key, now))
        _bootstrap_failed(key, now)
        self.assertFalse(_bootstrap_due(key, now + timedelta(minutes=1)))
        self.assertTrue(_bootstrap_due(key, now + timedelta(minutes=5)))
        _bootstrap_failed(key, now)
        self.assertFalse(_bootstrap_due(key, now + timedelta(minutes=9)))
        _BOOTSTRAP_BACKOFF.pop(str(key), None)


class SchedulerIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_failing_workspace_does_not_stop_the_others(self):
        from app import runtime

        first, second = uuid.uuid4(), uuid.uuid4()

        class Result:
            def all(self):
                return [(first, "active", {}), (second, "active", {})]

        class Session:
            async def execute(self, _statement):
                return Result()

        @asynccontextmanager
        async def factory():
            yield Session()

        seen: list[object] = []

        async def tick(_settings, _now, _times, entry, _results):
            seen.append(entry[0])
            if entry[0] == first:
                raise RuntimeError("broken workspace")

        with (
            patch.object(runtime, "SessionLocal", factory),
            patch.object(runtime, "scheduler_schedule_times", new=AsyncMock(return_value=(("10:00",), False))),
            patch.object(runtime, "scheduler_schedule_config", new=AsyncMock(return_value=(((0, "10:00"),), False))),
            patch.object(runtime, "_tick_assistant", side_effect=tick),
            patch.object(runtime, "_claim_job", new=AsyncMock(return_value=(None, "succeeded"))),
        ):
            result = await runtime.scheduler_tick(settings(), now=datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc))
        self.assertEqual([first, second], seen)
        self.assertEqual("failed", result["pipeline_results"][0]["status"])


class PublishClaimTest(unittest.IsolatedAsyncioTestCase):
    async def test_publication_being_sent_is_never_sent_twice(self):
        from app import pipeline_service

        now = datetime.now(timezone.utc)
        publication = SimpleNamespace(status="publishing", audit={"publishing_started_at": now.isoformat()}, updated_at=now)
        factory, _session = _fake_sessionmaker(publication)
        with patch.object(pipeline_service, "SessionLocal", factory), patch.object(pipeline_service, "TelegramClient") as telegram:
            with self.assertRaises(RuntimeError):
                await pipeline_service.publish_publication(uuid.uuid4())
            with self.assertRaises(RuntimeError):
                # Even the owner cannot retry a fresh claim.
                await pipeline_service.publish_publication(uuid.uuid4(), allow_stale_claim=True)
        telegram.assert_not_called()

    async def test_archived_publication_cannot_be_sent(self):
        from app import pipeline_service

        publication = SimpleNamespace(status="archived", audit={}, updated_at=datetime.now(timezone.utc))
        factory, _session = _fake_sessionmaker(publication)
        with patch.object(pipeline_service, "SessionLocal", factory):
            with self.assertRaises(RuntimeError):
                await pipeline_service.publish_publication(uuid.uuid4())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class GoogleSignInTest(unittest.IsolatedAsyncioTestCase):
    def configured(self) -> Settings:
        return settings(google_client_id="client.apps.googleusercontent.com", google_client_secret="secret-value", google_redirect_uri="https://example.com/auth/google/callback")

    def test_gmail_normalization(self):
        self.assertEqual("farhaddgm@gmail.com", google_auth.normalize_email("Farhad.DGM+work@googlemail.com"))
        self.assertEqual("a.b@example.com", google_auth.normalize_email("A.B@Example.com"))
        self.assertFalse(google_auth.is_gmail("owner@example.com"))

    def test_flow_cookie_is_signed_and_expires(self):
        cfg = self.configured()
        url, cookie = google_auth.start_flow(cfg, "user")
        self.assertIn("code_challenge_method=S256", url)
        flow = google_auth.read_flow(cfg, cookie)
        self.assertEqual("user", google_auth.flow_portal(flow))
        payload, signature = cookie.split(".", 1)
        tampered = _b64(json.dumps({**flow, "portal": "admin"}).encode()) + "." + signature
        for bad in (tampered, "", None, cookie + "x"):
            with self.assertRaises(google_auth.GoogleAuthError):
                google_auth.read_flow(cfg, bad)

    def test_not_configured(self):
        with self.assertRaises(google_auth.GoogleAuthError) as ctx:
            google_auth.start_flow(settings(), "admin")
        self.assertEqual("not_configured", ctx.exception.code)

    async def test_token_exchange_checks_state_and_claims(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        cfg = self.configured()
        _url, cookie = google_auth.start_flow(cfg, "admin")
        flow = google_auth.read_flow(cfg, cookie)
        claims = {"iss": "https://accounts.google.com", "aud": cfg.google_client_id, "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": flow["nonce"], "sub": "123", "email": "Person@gmail.com", "email_verified": True}
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        public["kid"] = "security-fixes-fixture"
        id_token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": public["kid"]})
        google_auth._JWKS_CACHE.update(keys=[], until=0.0)

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == google_auth.JWKS_URL:
                return httpx.Response(200, json={"keys": [public]})
            self.assertIn(b"code_verifier=", request.content)
            return httpx.Response(200, json={"id_token": id_token})

        identity = await google_auth.finish_flow(cfg, code="abc", state=flow["state"], error=None, flow=flow, transport=httpx.MockTransport(handler))
        self.assertEqual("person@gmail.com", identity.email)
        with self.assertRaises(google_auth.GoogleAuthError):
            await google_auth.finish_flow(cfg, code="abc", state="wrong", error=None, flow=flow, transport=httpx.MockTransport(handler))
        with self.assertRaises(google_auth.GoogleAuthError):
            google_auth.identity_from_claims(cfg, {**claims, "nonce": "other"}, flow["nonce"])
        with self.assertRaises(google_auth.GoogleAuthError):
            google_auth.identity_from_claims(cfg, {**claims, "aud": "someone-else"}, flow["nonce"])

    async def test_unlisted_gmail_is_rejected(self):
        from app import admin

        class Result:
            def scalar_one_or_none(self):
                return None

        class Session:
            async def execute(self, _statement):
                return Result()

        @asynccontextmanager
        async def factory():
            yield Session()

        identity = google_auth.GoogleIdentity(sub="1", email="stranger@gmail.com", email_verified=True)
        with patch.object(admin, "SessionLocal", factory):
            with self.assertRaises(google_auth.GoogleAuthError) as ctx:
                await admin.login_with_google(identity, portal="admin")
        self.assertEqual("not_allowed", ctx.exception.code)
        with self.assertRaises(google_auth.GoogleAuthError) as ctx:
            await admin.login_with_google(google_auth.GoogleIdentity(sub="1", email="x@example.com", email_verified=True), portal="admin")
        self.assertEqual("not_gmail", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
