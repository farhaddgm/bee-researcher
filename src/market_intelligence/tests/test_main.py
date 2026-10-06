import asyncio
import os
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import SecretStr


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import (  # noqa: E402
    _ClientErrorRateLimiter,
    _redact_http_detail,
    _reader_assistant_is_accessible,
    _safe_telemetry_token,
    _csp_report_items,
    app,
    settings,
)
from app.admin import (  # noqa: E402
    AssistantCloneRequest,
    AssistantRequest,
    AssistantUpdate,
    CatalogDraftRequest,
    DEFAULT_ASSISTANT_ID,
    SourceCreate,
    SourceUpdate,
    TopicCreate,
    _telegram_config,
    _local_source_draft,
    _local_source_suggestions,
    _verify_source_draft,
    assistant_readiness,
    draft_source,
    update_assistant,
)
from app.fetchers import FetchFailure  # noqa: E402
from app.security_controls import csrf_token_matches, new_csrf_token  # noqa: E402


class MainTest(unittest.TestCase):
    def test_reader_assistant_access_check_fails_closed_on_malformed_workspace_data(self):
        assistant_id = uuid.uuid4()
        self.assertTrue(
            _reader_assistant_is_accessible(
                {"assistants": [{"id": str(assistant_id)}]}, assistant_id
            )
        )
        self.assertFalse(_reader_assistant_is_accessible({"assistants": [None]}, assistant_id))
        self.assertFalse(_reader_assistant_is_accessible({"assistants": "not-a-list"}, assistant_id))

    def test_legacy_assistant_readiness_uses_effective_inherited_destinations(self):
        assistant_id = DEFAULT_ASSISTANT_ID
        workspace = SimpleNamespace(
            id=assistant_id,
            status="active",
            deleted_at=None,
            business_name="",
            config={"runtime": {"max_items_per_run": 7, "analysis_model": "test-model", "schedule_slots": []}},
        )

        class ScalarResult:
            def __init__(self, value):
                self.value = value

            def scalar_one(self):
                return self.value

        class FakeAsyncSession:
            async def get(self, _model, _assistant_id):
                return workspace

            async def execute(self, _statement):
                return ScalarResult(next(counts))

        class FakeSessionContext:
            async def __aenter__(self):
                return FakeAsyncSession()

            async def __aexit__(self, *_args):
                return None

        counts = iter((2, 1, 0))
        owner = SimpleNamespace(username="owner", email="owner@gmail.com", role="admin")
        telegram_settings = SimpleNamespace(
            owner_email="owner@gmail.com",
            telegram_bot_token=SecretStr("123456:server-secret"),
            telegram_channel_id="-100111",
            telegram_observer_channel_id="-100222",
        )

        async def fake_access(_assistant_id, _user):
            return workspace

        with (
            patch("app.admin._require_assistant_access", new=AsyncMock(side_effect=fake_access)),
            patch("app.admin.SessionLocal", return_value=FakeSessionContext()),
            patch("app.admin.get_settings", return_value=telegram_settings),
        ):
            readiness = asyncio.run(assistant_readiness(assistant_id, owner))
        self.assertTrue(readiness["ready"])
        self.assertTrue(readiness["checks"]["feedback_channel"])
        self.assertTrue(readiness["checks"]["observer_channel"])
        self.assertEqual([], readiness["missing"])


    def test_owner_can_update_workspace_without_admin_user_fields(self):
        assistant_id = uuid.uuid4()
        workspace = SimpleNamespace(
            id=assistant_id,
            slug="dotin",
            name="Dotin",
            status="active",
        )

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _model, _assistant_id, **_kwargs):
                return workspace

            async def commit(self):
                return None

        owner = SimpleNamespace(id=uuid.uuid4(), role="owner")
        with (
            patch("app.admin._require_project_admin", new=AsyncMock(return_value=workspace)),
            patch("app.admin.SessionLocal", return_value=FakeSession()),
            patch("app.admin._audit", new=AsyncMock()),
        ):
            result = asyncio.run(
                update_assistant(
                    assistant_id,
                    AssistantUpdate(name="Dotin updated"),
                    owner,
                )
            )

        self.assertEqual("Dotin updated", workspace.name)
        self.assertEqual(str(assistant_id), result["id"])

    def test_readiness_uses_effective_legacy_telegram_destinations(self):
        configured = SimpleNamespace(
            telegram_bot_token=SecretStr("123456:server-secret"),
            telegram_channel_id="-100111",
            telegram_observer_channel_id="-100222",
        )
        with patch("app.admin.get_settings", return_value=configured):
            inherited = _telegram_config({}, assistant_id=DEFAULT_ASSISTANT_ID)
            isolated = _telegram_config({}, assistant_id=uuid.uuid4())
            explicitly_cleared = _telegram_config(
                {"telegram": {"feedback_channel_id": None, "observer_channel_id": None}},
                assistant_id=DEFAULT_ASSISTANT_ID,
            )

        self.assertEqual("-100111", inherited["feedback_channel_id"])
        self.assertEqual("-100222", inherited["observer_channel_id"])
        self.assertIsNone(isolated["feedback_channel_id"])
        self.assertIsNone(isolated["observer_channel_id"])
        self.assertIsNone(explicitly_cleared["feedback_channel_id"])
        self.assertIsNone(explicitly_cleared["observer_channel_id"])
        self.assertTrue(inherited["token_configured"])
        self.assertNotIn("server-secret", repr(inherited))

    def test_http_error_details_redact_credentials_recursively(self):
        detail = _redact_http_detail({"message": "Bearer secret-token", "items": ["?api_key=hidden"]})
        self.assertEqual("Bearer [REDACTED]", detail["message"])
        self.assertEqual("?api_key=[REDACTED]", detail["items"][0])

    def test_browser_error_telemetry_is_rate_limited_and_context_is_safe(self):
        limiter = _ClientErrorRateLimiter(limit=2, window_seconds=10, max_clients=2)
        self.assertTrue(limiter.allow("opaque-session-a", now=1))
        self.assertTrue(limiter.allow("opaque-session-a", now=2))
        self.assertFalse(limiter.allow("opaque-session-a", now=3))
        self.assertTrue(limiter.allow("opaque-session-b", now=3))
        self.assertTrue(limiter.allow("opaque-session-a", now=12))
        self.assertEqual("sources", _safe_telemetry_token("sources", 80))
        self.assertEqual("unknown", _safe_telemetry_token("alice@example.com", 80))
        self.assertEqual("unknown", _safe_telemetry_token("view\nforged-log-entry", 80))

    def test_authenticated_client_error_endpoint_enforces_rate_limit(self):
        limiter = _ClientErrorRateLimiter(limit=1, window_seconds=300, max_clients=8)
        client = TestClient(app)
        session_token = "test-admin-browser-session"
        csrf_token = new_csrf_token(session_token, settings)
        client.cookies.set("research_bee_admin_session", session_token)
        client.cookies.set("research_bee_admin_csrf", csrf_token)
        headers = {"X-CSRF-Token": csrf_token}
        with (
            patch("app.main.current_admin", new=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))),
            patch("app.main._client_error_rate_limiter", limiter),
        ):
            accepted = client.post(
                "/admin/api/security/client-error",
                json={"kind": "window", "view": "overview"},
                headers=headers,
            )
            limited = client.post(
                "/admin/api/security/client-error",
                json={"kind": "window", "view": "overview"},
                headers=headers,
            )
        self.assertEqual(204, accepted.status_code)
        self.assertEqual(429, limited.status_code)
        self.assertEqual("60", limited.headers.get("retry-after"))

    def test_authenticated_client_error_rejects_oversized_body_at_telemetry_limit(self):
        session_token = "oversized-admin-browser-session"
        csrf_token = new_csrf_token(session_token, settings)
        client = TestClient(app)
        client.cookies.set("research_bee_admin_session", session_token)
        client.cookies.set("research_bee_admin_csrf", csrf_token)
        with (
            patch("app.main.current_admin", new=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))),
            patch("app.main._client_error_rate_limiter", _ClientErrorRateLimiter(limit=4)),
        ):
            response = client.post(
                "/admin/api/security/client-error",
                content=b"x" * 1_025,
                headers={"X-CSRF-Token": csrf_token, "content-type": "application/json"},
            )
        self.assertEqual(413, response.status_code)

    def test_csrf_token_is_signed_and_bound_to_session(self):
        session = "opaque-session"
        token = new_csrf_token(session, settings)
        self.assertTrue(csrf_token_matches(token, token, session, settings))
        self.assertFalse(csrf_token_matches(token, token, "different-session", settings))
        self.assertFalse(csrf_token_matches(token + "x", token, session, settings))

    def test_metadata_exposes_namespaces_but_not_secrets(self):
        with patch("app.main.current_admin", new=AsyncMock(return_value=SimpleNamespace(email="farhad.dgm@gmail.com", role="admin", username="admin"))):
            response = TestClient(app).get("/meta")
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("market_intelligence", body["database_schema"])
        self.assertEqual(settings.queue_namespace, body["queue_namespace"])
        self.assertEqual(["rss", "html", "json", "telegram_public", "telegram_private", "instagram_public", "instagram_private", "x_public", "x_private"], body["ingestion"]["adapters"])
        self.assertEqual(settings.version, body["version"])
        self.assertEqual(settings.build_revision, body["source_revision"])
        self.assertEqual(settings.image_digest, body["image_digest"])
        self.assertEqual(720, body["admin_session_idle_hours"])
        self.assertEqual(30, body["account_session_ttl_days"])
        self.assertEqual("02:00", body["user_session_cutoff_local"])
        self.assertEqual(3, body["freshness_window_days"])
        self.assertEqual(settings.pilot_mode, body["pipeline"]["pilot_mode"])
        self.assertEqual(settings.auto_publish, body["pipeline"]["auto_publish"])
        self.assertNotIn("postgres_password", body)
        self.assertNotIn("redis_password", body)
        self.assertEqual("disabled_until_meta_approval", body["whatsapp"]["status"])
        self.assertNotIn("access_token", body["whatsapp"])

    def test_health_reports_dependency_state(self):
        with (
            patch("app.main.check_database", new=AsyncMock(return_value=None)),
            patch("app.main.check_redis", new=AsyncMock(return_value=None)),
        ):
            response = TestClient(app).get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual("healthy", response.json()["status"])

    def test_health_is_degraded_when_a_dependency_fails(self):
        with (
            patch("app.main.check_database", new=AsyncMock(side_effect=RuntimeError("db"))),
            patch("app.main.check_redis", new=AsyncMock(return_value=None)),
        ):
            response = TestClient(app).get("/health")
        self.assertEqual(503, response.status_code)
        self.assertEqual("unhealthy", response.json()["dependencies"]["postgres"])

    def test_ready_includes_process_runtime_signals(self):
        # Readiness is stricter than liveness: a healthy database alone is not
        # enough while the scheduler has not started its heartbeat.
        with (
            patch("app.main.check_database", new=AsyncMock(return_value=None)),
            patch("app.main.check_redis", new=AsyncMock(return_value=None)),
            patch.object(settings, "scheduler_enabled", False),
            patch.object(settings, "telegram_polling_enabled", False),
        ):
            response = TestClient(app).get("/ready")
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("ready", body["status"])
        self.assertIn("runtime", body)
        self.assertEqual("healthy", body["runtime"]["scheduler"])

    def test_ready_returns_not_ready_for_stale_scheduler(self):
        with (
            patch("app.main.check_database", new=AsyncMock(return_value=None)),
            patch("app.main.check_redis", new=AsyncMock(return_value=None)),
            patch.object(settings, "scheduler_enabled", True),
            patch.object(settings, "telegram_polling_enabled", False),
        ):
            response = TestClient(app).get("/ready")
        self.assertEqual(503, response.status_code)
        self.assertEqual("not_ready", response.json()["status"])
        self.assertIn(response.json()["runtime"]["scheduler"], {"starting", "stopped"})

    def test_private_backoffice_is_not_indexable(self):
        client = TestClient(app)
        robots = client.get("/robots.txt")
        self.assertEqual(200, robots.status_code)
        self.assertIn("Disallow: /", robots.text)
        admin = client.get("/admin")
        self.assertIn("noindex,nofollow,noarchive,nosnippet", admin.text)
        self.assertRegex(admin.text, r'<script nonce="[^"]+" id="support-v3-stabilizer">')
        self.assertRegex(admin.text, r'<script nonce="[^"]+" id="admin-performance-guards">')
        self.assertRegex(admin.text, r'<style nonce="[^"]+" id="support-v3-style">')
        self.assertIn("noindex, nofollow, noarchive, nosnippet", admin.headers["x-robots-tag"])
        self.assertEqual("nosniff", admin.headers["x-content-type-options"])
        self.assertEqual("no-referrer", admin.headers["referrer-policy"])
        self.assertEqual("DENY", admin.headers["x-frame-options"])
        self.assertIn("frame-ancestors 'none'", admin.headers["content-security-policy"])
        self.assertNotIn("script-src 'self' 'unsafe-inline'", admin.headers["content-security-policy"])
        self.assertNotIn("script-src-attr", admin.headers["content-security-policy"])
        self.assertNotIn("style-src-attr", admin.headers["content-security-policy"])
        self.assertNotIn("unsafe-inline", admin.headers["content-security-policy"])
        self.assertIn("nonce-", admin.headers["content-security-policy"])
        self.assertIn("Content-Security-Policy-Report-Only", admin.headers)
        self.assertIn("report-uri /admin/api/security/csp-report", admin.headers["content-security-policy-report-only"])
        self.assertNotIn("script-src-attr", admin.headers["content-security-policy-report-only"])
        self.assertIn("camera=()", admin.headers["permissions-policy"])
        self.assertEqual("same-origin", admin.headers["cross-origin-opener-policy"])
        self.assertEqual("none", admin.headers["x-permitted-cross-domain-policies"])
        self.assertEqual("off", admin.headers["x-dns-prefetch-control"])
        self.assertEqual("?1", admin.headers["origin-agent-cluster"])

    def test_csp_strict_mode_removes_inline_attribute_exceptions(self):
        with patch.object(settings, "csp_strict", True):
            response = TestClient(app).get("/admin")
        policy = response.headers["content-security-policy"]
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("script-src-attr", policy)
        self.assertNotIn("style-src-attr", policy)

    def test_sensitive_metadata_and_mutations_require_authentication(self):
        client = TestClient(app)
        self.assertEqual(401, client.get("/meta").status_code)
        self.assertEqual(401, client.post("/relevance/rescore").status_code)
        self.assertEqual(401, client.post("/retention/run").status_code)
        self.assertEqual(401, client.post("/feedback", json={"analysis_id": str(uuid.uuid4()), "actor_key": "x", "value": "up"}).status_code)
        self.assertEqual(403, client.post("/admin/api/login", headers={"origin": "https://attacker.example"}, json={"username": "x", "password": "y"}).status_code)

    def test_csp_report_endpoint_is_bounded_and_redacts_report_fields(self):
        client = TestClient(app)
        response = client.post(
            "/admin/api/security/csp-report",
            json={"csp-report": {"blocked-uri": "https://example.test/?api_key=secret", "line-number": 7}},
        )
        self.assertEqual(204, response.status_code)
        self.assertEqual(204, client.post("/admin/api/security/csp-report").status_code)
        self.assertEqual(400, client.post("/admin/api/security/csp-report", content=b"not-json").status_code)
        self.assertEqual(413, client.post("/admin/api/security/csp-report", content=b"x" * 64_001).status_code)

    def test_csp_telemetry_discards_nonce_queries_fragments_and_user_paths(self):
        payload = {"csp-report": {
            "original-policy": "script-src 'nonce-private-nonce'",
            "document-uri": "https://user:private-pass@example.org/admin?query=private-search#private-fragment",
            "source-file": "https://example.org/user/private-user-id",
            "blocked-uri": "data:text/plain,private-content",
            "effective-directive": "style-src-attr", "line-number": 42,
        }}
        result = _csp_report_items(payload)
        self.assertEqual([{"document-uri": "https://example.org/admin", "source-file": "https://example.org/", "blocked-uri": "data", "effective-directive": "style-src-attr", "line-number": 42}], result)
        self.assertNotIn("private", str(result))

    def test_csp_modern_reporting_api_is_supported_without_collecting_samples(self):
        result = _csp_report_items([{"type": "csp-violation", "body": {
            "documentURL": "https://example.org/user?private=1",
            "effectiveDirective": "script-src-elem", "blockedURL": "inline",
            "lineNumber": 8, "sample": "private body", "originalPolicy": "nonce-private",
        }}])
        self.assertEqual("https://example.org/user", result[0]["document-uri"])
        self.assertEqual("script-src-elem", result[0]["effective-directive"])
        self.assertNotIn("private", str(result))

    def test_csp_report_endpoint_stays_public_with_an_admin_cookie(self):
        client = TestClient(app)
        # Browsers include the admin cookie on report-only POSTs. Telemetry is
        # intentionally unauthenticated and bounded, so CSRF must not turn it
        # into a noisy 403 response.
        client.cookies.set("research_bee_admin_session", "opaque-session")
        response = client.post(
            "/admin/api/security/csp-report",
            json={"csp-report": {"violated-directive": "script-src"}},
        )
        self.assertEqual(204, response.status_code)

    def test_oversized_request_is_rejected_before_body_parsing(self):
        client = TestClient(app)
        response = client.post(
            "/admin/api/login",
            content=b"x" * (settings.max_request_body_bytes + 1),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(413, response.status_code)

    def test_cross_origin_state_changes_are_rejected_across_control_plane(self):
        client = TestClient(app)
        response = client.post(
            "/pipeline/run",
            headers={"origin": "https://attacker.example"},
            json={"force_ingestion": False},
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("cross-origin request blocked", response.json()["detail"])

    def test_cookie_authenticated_mutations_require_double_submit_csrf_token(self):
        client = TestClient(app)
        client.cookies.set("research_bee_admin_session", "opaque-session")
        missing = client.post("/admin/api/logout")
        self.assertEqual(403, missing.status_code)
        self.assertEqual("csrf validation failed", missing.json()["detail"])
        operational_missing = client.post("/pipeline/run", json={"force_ingestion": False})
        self.assertEqual(403, operational_missing.status_code)
        self.assertEqual("csrf validation failed", operational_missing.json()["detail"])
        mismatched = client.post(
            "/admin/api/logout",
            headers={"X-CSRF-Token": "attacker-value"},
            cookies={"research_bee_admin_csrf": "server-value"},
        )
        self.assertEqual(403, mismatched.status_code)
        self.assertEqual("csrf validation failed", mismatched.json()["detail"])

    def test_root_redirects_to_admin_and_brand_assets_are_available(self):
        client = TestClient(app)
        root = client.get("/", follow_redirects=False)
        self.assertEqual(307, root.status_code)
        self.assertEqual("/admin", root.headers["location"])
        favicon = client.get("/favicon.ico")
        self.assertEqual(200, favicon.status_code)
        self.assertIn("image/svg+xml", favicon.headers["content-type"])
        self.assertIn(b"<svg", favicon.content)
        self.assertEqual(200, client.get("/assets/bee.svg").status_code)
        self.assertEqual(200, client.get("/assets/bee-researcher.svg").status_code)
        self.assertEqual(200, client.get("/assets/bee-researcher-grey.svg").status_code)
        self.assertEqual(404, client.get("/assets/not-allowed.svg").status_code)

    def test_admin_ui_has_sortable_tables_and_safe_bot_settings(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("table-sort", body)
        self.assertIn("اطلاعات ربات و کانال‌ها", body)
        self.assertIn("توکن ربات فقط از تنظیمات امن سرور", body)
        self.assertIn("research_bee_admin_csrf", body)
        self.assertIn("X-CSRF-Token", body)
        self.assertIn("safePreview", body)
        self.assertIn("public-social-sources", body)
        self.assertIn("افزودن منبع اجتماعی عمومی", body)

    def test_client_error_telemetry_does_not_embed_exception_text(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("/admin/api/security/client-error", body)
        self.assertIn("const body={kind,view}", body)
        self.assertNotIn("error&&error.message", body)
        self.assertNotIn("slice(0,240)", body)

    def test_admin_ui_uses_bee_researcher_brand_assets(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("Bee Researcher | Control center", body)
        self.assertIn("/assets/bee.svg", body)
        self.assertIn("/assets/bee-researcher-grey.svg", body)
        self.assertIn("/favicon.svg", body)

    def test_login_uses_friendly_inline_validation_messages(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="loginForm" novalidate', body)
        self.assertIn('id="loginSubmit" type="submit"', body)
        self.assertIn("bindLoginRecovery", body)
        self.assertIn("Signing in…", body)
        self.assertIn('id="loginUserError"', body)
        self.assertIn('id="loginPassError"', body)
        self.assertIn("نام کاربری را وارد کنین.", body)
        self.assertIn("رمز عبور را وارد کنین.", body)
        self.assertIn("function friendlyError(message)", body)
        self.assertIn("p!=='/admin/api/login'", body)
        self.assertIn("p==='/admin/api/login'?'invalid credentials'", body)
        self.assertIn("form.dataset.loginGuardWrapped='1'", body)
        self.assertIn("function reqWithTimeout(path,opts={},timeoutMs=15000)", body)
        self.assertIn("function fetchWithTimeout(url,options={},timeoutMs=20000)", body)
        self.assertIn("authentication bootstrap pending", body)
        self.assertIn("!state.currentUser&&p!=='/admin/api/login'&&p!=='/admin/api/me'", body)
        self.assertIn("lower.includes('abort')", body)

    def test_admin_ui_exposes_owner_account_theme_and_template_controls(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("/admin/api/account/preferences", body)
        self.assertIn("if(!state.currentUser)return;if(prefsLoaded)", body)
        self.assertIn("if(!state.assistantId||!state.currentUser)return", body)
        self.assertIn('data-view="account"', body)
        self.assertIn("data-template-max", body)
        self.assertIn("data-template-guidance", body)
        self.assertIn("data-template-emoji", body)

    def test_admin_ui_does_not_expose_removed_mfa_login_challenge(self):
        body = TestClient(app).get("/admin").text
        self.assertNotIn("/admin/api/mfa/", body)
        self.assertNotIn("Two-step verification", body)
        self.assertNotIn("mfaChallenge", body)
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        self.assertNotIn("/admin/api/mfa/verify", paths)

    def test_admin_ui_repairs_account_navigation_and_channel_card_order(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const owner=()=>Boolean(state.currentUser?.is_owner||state.currentUser?.role==='owner')", body)
        self.assertIn("setView('account')", body)
        self.assertIn("localizeSettingsNumbers", body)
        self.assertIn("schedule.insertBefore(channels,readiness)", body)
        self.assertIn("default:{fa:'آبی جذاب',en:'Attractive blue'", body)
        self.assertIn("blackyellow", body)
        self.assertIn("قرمز حرفه‌ای", body)
        self.assertNotIn("زنبور آبی", body)
        self.assertIn("heading.dataset.faText='زمان‌بندی'", body)

    def test_admin_ui_settings_localize_persian_digits_without_runtime_error(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("window.__researchBeeLocalizeSettingsNumbers", body)
        self.assertIn("setTimeout(()=>window.__researchBeeLocalizeSettingsNumbers?.(),0)", body)
        self.assertIn("Number(toLatinDigits($(id)?.value||''))", body)
        self.assertIn("مقادیر سقف‌ها باید عدد معتبر باشند", body)

    def test_admin_ui_removes_quality_and_trend_panel_from_news_list(self):
        body = TestClient(app).get("/admin").text
        self.assertNotIn("id=\"insightsPanel\"", body)
        self.assertIn("data-insight-translate", body)
        self.assertIn("official-fallback", body)
        self.assertIn("/insights?assistant_id=", body)
        self.assertIn("Not auto-approved — manual review", body)
        self.assertIn("This news was not approved automatically.", body)
        self.assertIn("MI-144: final cascade for the shared header layout", body)

    def test_template_editor_is_inline_on_channels_page(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("templateBuilderPanel", body)
        self.assertIn("window.openTemplateBuilder=async function", body)
        self.assertIn("const removeTemplateButton=()=>document.querySelectorAll('#templateBuilderBtn').forEach(button=>button.remove())", body)
        self.assertIn("templatePublishBtn", body)
        self.assertIn("applyTheme(storedTheme||'honey')", body)
        self.assertIn("html[data-theme=\"honey\"] .login-shell", body)
        self.assertIn("new MutationObserver(removeTemplateButton)", body)

    def test_admin_ui_uses_consistent_lucide_style_svg_icons(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("MI-068", body)
        self.assertIn("lucideIconPaths", body)
        self.assertIn('data-icon="layout-dashboard"', body)
        self.assertIn('data-icon="bell"', body)
        self.assertIn("'settings-2'", body)
        self.assertIn("applyLucideIcons()", body)

    def test_admin_ui_keeps_header_title_in_sync_with_active_menu(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("function updateHeaderTitle(name)", body)
        self.assertIn("title.dataset.faText=faLabels[name]", body)
        self.assertIn("updateHeaderTitle(name);closeSidebar()", body)

    def test_admin_ui_explains_disabled_account_and_server_idle_timeout(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("account_disabled", body)
        self.assertIn("حساب شما غیرفعال است. لطفاً با مدیر حساب‌ها ارتباط بگیرین.", body)
        self.assertIn("Your account is disabled. Please contact the account administrator.", body)

    def test_admin_ui_exposes_project_freshness_window(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="freshnessWindowDays"', body)
        self.assertIn("freshness_window_days", body)
        self.assertIn("پنجره تازگی خبر (روز)", body)
        self.assertIn("const cap=7", body)
        self.assertIn("News limit per run cannot exceed 7", body)
        self.assertIn("سقف انتشار در هر نوبت", body)
        self.assertIn("max_candidates:null", body)
        self.assertIn("سقف پردازش: حداکثر ۱۰۰۰ خبر جدید در روز برای هر پروژه.", body)

    def test_admin_ui_scopes_delete_action_to_authorized_project_cards(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("card.querySelector('.delete-assistant-btn'))return", body)
        self.assertIn("function canDeleteAssistant(item)", body)
        self.assertIn("Boolean(item?.can_delete)", body)
        self.assertIn("b.dataset.assistantId=item.id", body)
        self.assertIn("const item=state.assistants.find(x=>x.id===el.dataset.assistantId)", body)
        self.assertNotIn("if(!item||item.id==='00000000-0000-0000-0000-000000000001'", body)

    def test_admin_ui_clears_workspace_cards_before_authenticated_bootstrap(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("function clearUserScopedUi()", body)
        self.assertIn("clearUserScopedUi();", body)
        self.assertIn("$('app').classList.add('hidden')", body)
        self.assertIn("function showApp(user){clearUserScopedUi();", body)
        self.assertIn("در حال دریافت پروژه‌های مجاز…", body)

    def test_admin_ui_hides_shells_during_auth_bootstrap_and_uses_new_logo_first_paint(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("html.session-checking #login,html.session-checking #app", body)
        self.assertIn("document.documentElement.classList.add('session-checking')", body)
        self.assertIn("classList.remove('session-checking')", body)
        self.assertIn("const shellWatchdog=setTimeout(releaseShell,4000)", body)
        self.assertIn("cache:'no-store'", body)
        self.assertIn("/assets/bee-researcher-grey.svg", body)
        self.assertIn(".login-card .logo .logo-mark,.login-card .logo>span{display:none!important}", body)

    def test_admin_ui_has_bootstrap_recovery_when_a_script_or_session_check_stalls(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("window.__researchBeeReleaseBoot", body)
        self.assertIn("setTimeout(()=>{if(Date.now()-window.__researchBeeBootStartedAt>=1500)", body)
        self.assertIn("window.addEventListener('unhandledrejection'", body)
        self.assertIn("A failed /me or a synchronous shell error must always leave a usable login form", body)
        self.assertIn("if($('app')?.classList.contains('hidden'))$('login')?.classList.remove('hidden')", body)

    def test_admin_ui_deduplicates_overview_bootstrap_requests(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("window.__researchBeeOverviewAuthenticated", body)
        self.assertIn("paintInFlight=null,paintTimer=null", body)
        self.assertIn("if(paintInFlight)return paintInFlight", body)

    def test_admin_ui_waits_for_authorized_project_list_before_rendering_cards(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("projectListReady:false", body)
        self.assertIn("if(!state.projectListReady){$('assistantGrid').innerHTML", body)
        self.assertIn("try{assist=await req('/admin/api/assistants');state.projectListReady=true}", body)
        self.assertIn("state.projectListReady?(assist.assistants||[]):[]", body)
        self.assertIn("if(!state.projectListReady){if($('businessGrid'))", body)

    def test_admin_ui_waits_for_authorized_security_and_business_lists(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("securityListReady:false", body)
        self.assertIn("Loading authorized users…", body)
        self.assertIn("در حال دریافت کاربران مجاز…", body)
        self.assertIn("const baseRefreshBusinessUi=refreshBusinessUi", body)
        self.assertIn("Loading authorized businesses for this project…", body)
        self.assertIn("در حال بارگذاری بیزینس‌های مجاز این پروژه…", body)

    def test_admin_ui_clears_project_scoped_panels_without_project_access(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const projectScopedLoadAll=loadAll", body)
        self.assertIn("برای نمایش تنظیمات، یک پروژهٔ مجاز انتخاب کنین.", body)
        self.assertIn("برای نمایش کانال‌ها، یک پروژهٔ مجاز انتخاب کنین.", body)
        self.assertIn("if(!state.assistantId){root.innerHTML", body)

    def test_admin_ui_keeps_authenticated_user_in_header_after_background_loads(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("function paintCurrentUser()", body)
        self.assertIn("async function syncCurrentUser()", body)
        self.assertIn("loadAll().finally(()=>{paintCurrentUser();syncCurrentUser()})", body)

    def test_admin_ui_has_multi_workspace_user_management_and_session_controls(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("revokeOtherSessionsBtn", body)
        self.assertIn("/admin/api/users/'+id+'/manage", body)
        self.assertIn("assistant_ids", body)
        self.assertIn("ادمین کل", body)
        self.assertIn("مالک", body)

    def test_admin_ui_uses_shared_header_and_sidebar_account_menu(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("MI-132/133", body)
        self.assertIn("sidebarAccountTrigger", body)
        self.assertIn("assistant-header-reference", body)
        self.assertIn("body.assistant-header-reference .topbar .user-chip,", body)

    def test_admin_ui_does_not_flash_account_as_sidebar_navigation(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('data-account-action="account"', body)
        self.assertIn("const moveLegacyAccountNav", body)
        self.assertNotIn("nav.appendChild(button);button.addEventListener('click',()=>setView('account'))", body)

    def test_admin_ui_keeps_quick_setup_and_hides_sidebar_version_number(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="quickAssistantBtn"', body)
        self.assertLess(body.find('id="newAssistantBtn"'), body.find('id="quickAssistantBtn"'))
        self.assertIn("openQuickAssistantModal", body)
        self.assertIn("body.assistant-reference #view-assistants #quickAssistantBtn{display:inline-flex}", body)
        self.assertIn("body.assistant-reference #view-assistants .page-head>.actions>.btn,body.assistant-reference #view-assistants .page-head>.actions>.btn.small{width:100%;min-width:0", body)
        self.assertIn(".main .assistant-card .card-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))", body)
        self.assertIn(".main .card-actions:not(.table-actions){display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr))", body)
        self.assertIn("preferred=['newAssistantBtn','sandboxAssistantBtn','quickAssistantBtn']", body)
        self.assertIn('.sidebar-foot > span[data-label-fa="نسخه"],.sidebar-foot > #sidebarVersion{display:none!important}', body)
        self.assertIn('id="tgBotId"', body)

    def test_admin_ui_support_icon_landing_view_scope_and_button_hierarchy(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("'life-buoy':'<circle", body)
        self.assertIn("'settings':'<path", body)
        self.assertIn('data-view="assistants" data-label-fa="دستیارها" data-label-en="Assistants"', body)
        self.assertIn('<section id="view-assistants" class="view active">', body)
        self.assertIn("Assistants is the stable post-login landing page.", body)
        self.assertIn('data-account-action="support"', body)
        self.assertIn('data-icon="life-buoy"', body)
        self.assertIn("if(action==='support'){window.setView?.('support');return}", body)
        self.assertIn("const legacyMenu=document.getElementById('sidebarAccountMenu');if(legacyMenu)", body)
        self.assertIn('id="admin-support-scope"', body)
        self.assertIn("node.id='view-support';node.className='view'", body)
        self.assertIn("root.classList.add('view')", body)
        self.assertIn('.view:not(#view-support) [class*="support-" i]', body)
        self.assertIn('id="admin-button-pattern-v2"', body)
        self.assertIn('order:99!important', body)
        self.assertIn('window.__researchBeeNormalizeButtons=normalize', body)

    def test_admin_ui_support_final_surface_is_hidden_until_support_route_is_active(self):
        body = TestClient(app).get("/admin").text
        # The final Support skin must not override the shared view visibility
        # contract.  Without the active-only rule, the support workspace is
        # rendered at the bottom of every page as soon as the hardening pass
        # adds the support-final class.
        self.assertIn('#view-support.support-final{display:none!important;', body)
        self.assertIn('#view-support.support-final.active{display:block!important}', body)

    def test_admin_ui_login_and_sidebar_copy_are_compact_and_stable(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("version.textContent='v3.30.1'", body)
        self.assertIn("collectionScheduleGrid", body)
        self.assertIn("collection_max_items_per_run", body)
        self.assertIn("collectionOwnerBadge", body)
        self.assertIn("/admin/api/support/tickets", body)
        self.assertIn("view-support", body)
        self.assertNotIn('data-label-fa="مرکز مدیریت چنددستگاهی"', body)
        self.assertNotIn('<h1 id="loginTitle">', body)
        self.assertNotIn('<p id="loginSubtitle"', body)
        self.assertIn('data-language-select', body)
        self.assertIn('text-align:left;direction:ltr', body)
        self.assertIn('observer?.disconnect()', body)
        self.assertIn('const observeRoots=()=>observedRoots.forEach', body)
        self.assertNotIn("const content=document.querySelector('.content');if(content){const observer=new MutationObserver", body)

    def test_admin_ui_removes_skip_to_content_in_all_views(self):
        body = TestClient(app).get("/admin").text
        self.assertNotIn('class="skip-link"', body)
        self.assertNotIn("Skip to content", body)
        self.assertNotIn("admin-main-content", body)

    def test_admin_ui_bootstrap_uses_parallel_health_and_short_read_cache(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const metaPromise=safe('/meta'", body)
        self.assertIn('id="admin-performance-guards"', body)
        self.assertIn('__adminReadCache', body)
        self.assertIn('__adminPerformanceSingleFlight', body)

    def test_admin_ui_support_workspace_is_stable_and_requested_helper_copy_is_removed(self):
        body = TestClient(app).get("/admin").text
        self.assertNotIn("News processing and review are independent; at most 7 news items are published per run.", body)
        self.assertNotIn("Safe blocks only; HTML, CSS and secrets are not accepted.", body)
        self.assertNotIn("پردازش و بررسی خبرها مستقل است؛ در هر نوبت حداکثر ۷ خبر منتشر می‌شود.", body)
        self.assertNotIn("فقط بلوک‌های امن مجاز هستند؛ HTML، CSS آزاد و secret پذیرفته نمی‌شود.", body)
        self.assertIn('id="support-v3-style"', body)
        self.assertIn('data-support-search-clear', body)
        self.assertIn('support-loading-state', body)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))', body)
        self.assertIn("const selectors=['#view-settings #limitsCard'", body)

    def test_admin_ui_stabilizes_list_toolbars_and_content_template_copy(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="admin-layout-stability"', body)
        self.assertIn('#view-content .filter-bar,#view-sources .filter-bar,#view-topics .filter-bar', body)
        self.assertIn('copy.safe[en?', body)
        self.assertIn("safe:{fa:'قالب فقط از بلوک‌های مجاز استفاده می‌کند.'", body)

    def test_admin_ui_v325_quality_layer_is_present(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="adminUxCommandPalette"', body)
        self.assertIn("Ctrl/Cmd+K", body)
        self.assertIn("research_bee_sidebar_collapsed", body)
        self.assertIn("admin-ux-sticky-toolbar", body)
        self.assertIn("admin-ux-filter-chip", body)
        self.assertNotIn("admin-ux-density-toggle", body)
        self.assertNotIn("admin-ux-compact", body)
        self.assertNotIn("appearanceDensity", body)
        self.assertNotIn("تراکم رابط", body)
        self.assertIn("prefers-reduced-motion:reduce", body)
        self.assertIn("beforeunload", body)
        self.assertIn("__researchBeeAdminUxV325", body)

    def test_admin_ui_sidebar_collapse_preserves_view_and_does_not_navigate(self):
        body = TestClient(app).get("/admin").text
        # Collapse is a shell-layout action. It must not reuse the landing
        # route or allow the initial URL observer to run again on every class
        # mutation.
        self.assertIn("let initialViewApplied=false", body)
        self.assertIn("if(initialViewApplied||app.classList.contains('hidden')||!window.state?.currentUser)return false", body)
        self.assertIn("const setCollapsed=collapsed=>{const value=Boolean(collapsed),before=currentView()", body)
        self.assertIn("app.dataset.sidebarCollapsed=value?'true':'false'", body)
        self.assertIn("toggle.setAttribute('aria-expanded',String(!value))", body)
        self.assertIn("window.__researchBeeNormalizeButtons?.()", body)
        self.assertNotIn("if(document.querySelector('.view.active')?.id!=='view-assistants')setView('assistants')", body)
        self.assertIn(".shell.sidebar-collapsed .main,.shell.sidebar-collapsed .content", body)
        self.assertNotIn(".shell.sidebar-collapsed #view-assistants .card-actions{display:grid", body)

    def test_admin_ui_v327_loading_schedule_and_owner_labels(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("admin-ux-skeleton", body)
        self.assertIn("adminUxShimmer", body)
        self.assertIn("clearRefreshLabels", body)
        self.assertNotIn("node.id='adminUxRefreshMeta'", body)
        self.assertNotIn("new Intl.DateTimeFormat(lang()", body)
        self.assertIn("schedule-hour-toggle collection-hour-toggle", body)
        self.assertIn("schedule-day-toggle collection-day-toggle", body)
        self.assertIn("schedule-slot collection-schedule-slot", body)
        self.assertIn("max-height:none;overflow-x:auto", body)
        self.assertIn("ownerOnlyLabels", body)
        for label in ("Owners only", "Yalnızca sahip", "للمالك فقط", "Solo proprietario", "Solo propietario", "Nur Eigentümer", "Propriétaire uniquement"):
            self.assertIn(label, body)
        self.assertIn("#view-settings #limitsCard", body)
        self.assertIn("${esc(a[0])}</b><div class=\"muted\">${esc(a[1])}", body)

    def test_admin_ui_has_mi060_security_and_action_layout(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("project-access-panel", body)
        self.assertIn("project-access-box", body)
        self.assertIn("project-access-option input[type=checkbox]", body)
        self.assertIn("async function getAccessProjects", body)
        self.assertIn("a?.name||a?.business_name||a?.slug", body)
        self.assertIn("data-language-select", body)
        self.assertIn("userName", body)
        self.assertIn("margin-inline-start:auto", body)
        self.assertIn("Edit settings", body)

    def test_admin_ui_keeps_existing_business_cards_during_refresh(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("businessAssistantId", body)
        self.assertIn("hasLoadedCurrent", body)
        self.assertIn("if(!hasLoadedCurrent)$('businessGrid').innerHTML", body)

    def test_admin_ui_overview_prefers_loaded_source_rows_for_active_media(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("sourceRows=state.sources||[]", body)
        self.assertIn("sourceRows.filter(x=>x.enabled).length", body)
        self.assertIn("sourceRows.filter(x=>x.enabled&&x.health_status==='healthy').length", body)
        self.assertIn("refreshOverviewKpis", body)
        self.assertIn("const baseLoadAll3=loadAll", body)
        self.assertIn("Independent overview bootstrap", body)
        self.assertIn("__researchBeePaintOverview", body)
        self.assertIn("__researchBeeOverviewExpected", body)
        self.assertIn("MutationObserver", body)
        self.assertIn("translateRequestedOverviewCopy", body)
        self.assertIn("Active media", body)
        self.assertIn("Each business is independent of media", body)
        self.assertIn("Project bot and destination channels", body)
        self.assertIn("No run has been recorded yet.", body)
        self.assertIn("Readiness check", body)
        self.assertNotIn("Final overview paint", body)
        self.assertIn("format=value=>english?String(value):toFa(value)", body)
        self.assertIn("Do not probe authenticated endpoints while the login shell is visible", body)
        self.assertIn("window.__researchBeePaintOverview?.()", body)

    def test_admin_ui_translates_page_copy_and_normalizes_interface_digits(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("'دستیارها':'Assistants'", body)
        self.assertIn("'مرکز کار':'Workspace'", body)
        self.assertIn("Numeric rendering has one owner", body)
        self.assertIn("toFa=value=>String(value).replace", body)

    def test_admin_ui_uses_event_driven_digit_normalization_without_polling(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("window.__researchBeeNormalizeDigits", body)
        self.assertIn("const normalizeMarkedNumbers", body)
        self.assertIn("One final, synchronous digit pass", body)
        self.assertNotIn("const languageObserver=new MutationObserver", body)
        self.assertNotIn("languageObserver.observe(document.documentElement", body)
        self.assertNotIn("setInterval(normalize,500)", body)
        self.assertNotIn("setInterval(()=>{if(state.currentUser)applySharedHeader()},500)", body)
        self.assertNotIn("setInterval(renderAvatarControl,800)", body)

    def test_admin_ui_bootstrap_does_not_repaint_locale_labels_forever(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("Only retry", body)
        self.assertIn("dataset.overviewReady==='true'", body)
        self.assertIn("function displayDigits(value){return toFaDigits(value)}", body)

    def test_admin_ui_localization_observer_ignores_its_own_text_and_order_writes(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("Ignore text-only mutations", body)
        self.assertIn("node.nodeType===Node.ELEMENT_NODE", body)
        self.assertIn("if(ordered.every((button,index)=>button===buttons[index]))return", body)
        self.assertIn("root.dataset.metricsSignature===signature", body)

    def test_admin_ui_has_stable_sidebar_and_motion_reduction(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("position:sticky", body)
        self.assertIn("prefers-reduced-motion", body)
        self.assertIn("miViewIn", body)
        self.assertIn("checkAssistantReadiness", body)
        self.assertIn("#view-schedule .channel-grid", body)
        self.assertIn("channel-section-title", body)

    def test_admin_ui_has_workspace_delete_and_inline_password_action(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("deleteAssistantFromUi", body)
        self.assertIn("user-cell", body)
        self.assertIn("changeUserPassword", body)
        self.assertIn("deleteUser", body)
        self.assertIn("/admin/api/users/'+id", body)

    def test_admin_ui_exposes_owner_only_copy_to_draft_action(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("openCloneAssistantModal", body)
        self.assertIn("/clone", body)
        self.assertIn("کپی به پیش‌نویس", body)
        self.assertIn("Copy as draft", body)

    def test_admin_ui_has_mi040_navigation_and_layout_controls(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("channelSettingsCard", body)
        self.assertIn("aria-controls=\"sidebar\"", body)
        self.assertIn("لیست خبرها", body)
        self.assertIn("نمای کلی", body)
        self.assertIn("global-search input{padding-right:44px", body)
        self.assertIn("این دستیار هنوز آماده اجرا نیست", body)
        self.assertIn("بررسی آمادگی انجام نشد", body)

    def test_admin_ui_has_mi042_feedback_timeline_and_workspace_cleanup(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("openFeedbackTimeline", body)
        self.assertIn("نمودار خطی", body)
        self.assertIn("delete-source-btn", body)
        self.assertIn("delete-topic-btn", body)
        self.assertIn("#view-sources .table-actions,#view-topics .table-actions", body)
        self.assertNotIn('id="businessSummary"', body)

    def test_admin_ui_has_mi043_language_and_login_refresh(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('data-label-en="Business"', body)
        self.assertIn('id="languageSelect"', body)
        self.assertIn('id="loginLanguage"', body)
        self.assertIn("setLanguage", body)
        self.assertIn("login-submit", body)

    def test_admin_ui_has_mi044_startup_and_workspace_guards(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("setView('assistants')", body)
        self.assertIn("function toFaDigits", body)
        self.assertIn("state.assistants.some", body)
        self.assertIn("localStorage.setItem('research_bee_workspace'", body)
        self.assertIn('html[dir="ltr"] body', body)

    def test_admin_ui_has_mi044_selectable_language_dropdown_and_button_system(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('data-language-select', body)
        self.assertIn('<option value="en">English</option>', body)
        self.assertIn('<option value="fa">فارسی</option>', body)
        self.assertIn('<option value="tr">Türkçe</option>', body)
        self.assertIn('<option value="ar">العربية</option>', body)
        self.assertIn('<option value="es">Español</option>', body)
        self.assertIn('<option value="it">Italiano</option>', body)
        self.assertIn('<option value="de">Deutsch</option>', body)
        self.assertIn('supportedLanguages.fr', body)
        self.assertIn('Français', body)
        self.assertIn('const supportedLanguages={', body)
        self.assertIn("localeCopy[state.language]?.[fa]||en", body)
        self.assertIn('html[lang="ar"] #login input', body)
        self.assertIn("language-choice", body)
        self.assertIn("min-width:124px", body)

    def test_admin_ui_has_mi045_column_sorting_and_business_refresh(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("ensureSortHeaders", body)
        self.assertIn("data-sort-key", body)
        self.assertNotIn("moveSource(", body)
        self.assertNotIn("moveTopic(", body)
        self.assertIn("if(name==='businesses')refreshBusinessUi()", body)

    def test_admin_ui_has_mi046_resilient_news_and_full_copy_translation(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("safe('/publications?limit=80'", body)
        self.assertIn("ارسال آنی یک خبر", body)
        self.assertIn("translateStaticCopy", body)
        self.assertIn("copyMap", body)
        self.assertIn("by_actor", body)

    def test_admin_ui_uses_the_spreadsheet_ux_writing_catalog(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const uxWritingCatalog=", body)
        self.assertIn("function uxCopyKey(value)", body)
        self.assertIn("function normalizeUxText(value)", body)
        self.assertIn("uxWritingByNormalizedKey", body)
        self.assertIn("function translateTextNodes", body)
        self.assertIn("uxWritingCatalog[key]", body)
        self.assertIn("Leave blank to keep the current password", body)
        self.assertIn("Mot de passe", body)

    def test_admin_ui_localizes_loading_states_before_async_project_payload(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("Loading authorized projects…", body)
        self.assertIn("Loading authorized businesses…", body)
        self.assertIn("Loading authorized users…", body)
        self.assertIn("Loading authorized sessions…", body)
        self.assertIn("esc(translatedCopy('در حال دریافت پروژه‌های مجاز…'))", body)

    def test_admin_ui_does_not_reject_valid_arabic_copy_as_persian(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const persian=/[\\u067e\\u0686\\u0698\\u06af\\u06cc\\u06a9", body)
        self.assertNotIn("const persian=/[\\u0600-\\u06ff]/", body)

    def test_admin_ui_keeps_non_english_assistant_actions_localized_and_compact(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('"کپی به پیش‌نویس"', body)
        self.assertIn('"tr":"Taslağı kopyala"', body)
        self.assertIn('"tr":"Çalışma alanını aç"', body)
        self.assertIn('"de":"Arbeitsbereich öffnen"', body)
        self.assertIn("ui('کپی به پیش‌نویس')", body)
        self.assertIn("assistant-card .card-actions .btn", body)

    def test_admin_ui_keeps_locale_selected_without_persian_intermediate_copy(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const requested=supportedLanguages[lang]?lang:'en';", body)
        self.assertIn("const local=(fa,english)=>", body)
        self.assertIn('"tr":"Görüntüle"', body)
        self.assertIn('"it":"Incompleto"', body)

    def test_admin_ui_manual_publish_matches_primary_pipeline_action_size(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("manualPublishButton.className='btn primary'", body)

    def test_admin_ui_prevents_duplicate_manual_publish_and_stable_identifiers(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("state.manualPublishInProgress", body)
        self.assertIn("button.disabled=true", body)
        self.assertIn('data-latin="true">${esc(x.source_key||\'\')}</div>', body)
        self.assertIn('data-latin="true">${esc(x.topic_key)}</div>', body)
        self.assertNotIn("setInterval(()=>{if(state.language!=='en')localizeVisibleNumbers()},1500)", body)

    def test_admin_ui_groups_page_actions_in_the_header(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('<div class="actions"><button class="btn" id="sourceProbeBtn"', body)
        self.assertIn('type="button" class="btn primary" id="addSourceBtn" data-catalog-create="source">＋ افزودن رسانه</button>', body)
        self.assertIn('<div class="actions"><button class="btn primary" id="newBusinessBtn"', body)
        self.assertIn('<div class="actions"><button class="btn primary" id="feedbackReportBtn"', body)
        self.assertIn('id="addTopicBtn" data-catalog-create="topic">＋ افزودن موضوع</button>', body)
        self.assertNotIn('id="editTelegramBtn"', body)
        self.assertIn('type="button" data-edit-telegram>ویرایش اطلاعات</button>', body)
        self.assertIn('id="newUserBtn">＋ افزودن کاربر</button>', body)
        self.assertIn("const sourceActions=document.querySelector('#view-sources .page-head .actions')", body)
        self.assertIn('id="admin-ui-capability-cleanup-v1"', body)
        self.assertIn("const catalogHandlers={source:'openCreateSourceModal',topic:'openCreateTopicModal'}", body)
        self.assertIn("event.preventDefault();", body)

    def test_admin_ui_header_shows_username_without_role(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="userName"', body)
        self.assertNotIn('id="userRole"', body)
        self.assertIn("function roleLabel", body)

    def test_admin_ui_header_uses_authenticated_account_and_ignores_stale_bootstrap(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("let authTransition=0", body)
        self.assertIn("const current=await req('/admin/api/me')", body)
        self.assertIn("bootstrapTransition===authTransition", body)
        self.assertIn('id="userName">—</span>', body)

    def test_admin_ui_header_identity_is_sticky_after_repaints(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("Never replace a known identity with a transient empty response", body)
        self.assertIn("const userHeaderObserver=new MutationObserver", body)
        # Identity reconciliation is observer/event driven; a polling timer
        # caused needless repaints and the locale-number flicker seen in the
        # production shell.  Keep the regression guard explicit so the timer
        # cannot be reintroduced accidentally.
        self.assertNotIn("setInterval(()=>{if(!$('app')?.classList.contains('hidden'))", body)
        self.assertIn("target.setAttribute('aria-label','کاربر واردشده: '+username)", body)

    def test_admin_ui_language_switch_keeps_login_language_buttons_in_place(self):
        body = TestClient(app).get("/admin").text
        self.assertIn(".language-choice{display:inline-flex", body)
        self.assertIn("direction:ltr;unicode-bidi:isolate", body)
        self.assertIn('id="loginLanguage" class="language-choice"', body)
        self.assertIn('data-language-select', body)

    def test_admin_ui_keeps_language_switch_labels_bilingual(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("el.closest('[data-language-select]')", body)
        self.assertIn('data-language-select', body)

    def test_admin_ui_preserves_logout_icon_and_anchor_text_when_language_changes(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("MI-076: changing language must not replace the logout icon with plain text.", body)
        self.assertIn('id="logoutLabel"', body)
        self.assertIn("view-settings", body)
        self.assertIn("/admin/api/assistants/", body)
        self.assertIn("const icon=button?.querySelector('[data-icon]')?.outerHTML||''", body)
        self.assertIn("button.innerHTML=`${icon}<span id=\"logoutLabel\" class=\"btn-label\">${label}</span>`", body)

    def test_admin_ui_has_media_discovery_and_limit_notifications(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("Discover specialist media", body)
        self.assertIn("/admin/api/notifications", body)
        self.assertIn("Approve and complete", body)
        self.assertIn("id=\"saveLimitsBtn\"", body)

    def test_admin_ui_has_reliable_media_form_and_business_free_assistant_copy(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="media-workflow-v2"', body)
        self.assertIn("mediaDraftName", body)
        self.assertIn("mediaReviewHomepage", body)
        self.assertIn("fetcher.fetch(SourceSpec(", Path(__file__).resolve().parents[1].joinpath("app", "admin.py").read_text())
        self.assertIn("Business name (optional)", body)
        self.assertIn("const catalogHandlers={source:'openCreateSourceModal',topic:'openCreateTopicModal'}", body)
        self.assertIn("window.__researchBeeReconcileWorkspaceActions=run", body)
        self.assertIn("/admin/api/assistants/'+encodeURIComponent(state.assistantId)+'/sources", body)
        self.assertIn("window.openCreateSourceModal=openCreateSourceModal", body)
        self.assertIn("Publication language", body)
        self.assertIn("mediaManualReview", body)

    def test_source_discovery_schema_and_ui_require_a_verified_review_before_add(self):
        body = TestClient(app).get("/admin").text
        source = Path(__file__).resolve().parents[1].joinpath("app", "admin.py").read_text()
        self.assertIn('"match_status"', source)
        self.assertIn('"alternatives"', source)
        self.assertIn("async def _verify_source_draft", source)
        self.assertIn("connection and sample content were verified", body)
        self.assertIn("status!=='ready'", body)
        self.assertIn("mediaSuggestKeyword", body)
        self.assertIn("media-health-summary", body)

    def test_source_draft_returns_project_scoped_verification_and_alternatives(self):
        assistant_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4(), username="owner", role="owner")
        draft = {
            "name": "Reuters",
            "homepage_url": "https://www.reuters.com",
            "fetch_url": "https://www.reuters.com/feed/",
            "adapter": "rss",
            "priority": 3,
            "alternatives": ["Reuters Business"],
        }
        verification = {"status": "ready", "items_found": 4, "message": "readable"}
        with (
            patch("app.admin._require_assistant_access", new=AsyncMock()),
            patch("app.admin._assistant_media_context", new=AsyncMock(return_value={"existing_media": ["Reuters Markets"]})),
            patch("app.admin._catalog_draft", new=AsyncMock(return_value=draft)),
            patch("app.admin._verify_source_draft", new=AsyncMock(return_value=verification)),
        ):
            result = asyncio.run(draft_source(assistant_id, CatalogDraftRequest(name="Reuters"), user))
        self.assertEqual("source", result["kind"])
        self.assertEqual(verification, result["verification"])
        self.assertIn("Reuters Business", result["draft"]["alternatives"])

    def test_local_media_directory_keeps_add_and_suggest_working_without_openai(self):
        draft = _local_source_draft("راه پرداخت", "پرداخت و بانکداری")
        self.assertIsNotNone(draft)
        self.assertEqual("https://way2pay.ir/feed/", draft["fetch_url"])
        self.assertEqual("local_directory", draft["draft_source"])
        result = _local_source_suggestions("فین‌تک", "پرداخت")
        self.assertGreaterEqual(len(result["suggestions"]), 1)
        self.assertEqual([], result["alternatives"])

    def test_local_media_keyword_match_and_per_source_language_are_editable(self):
        draft = _local_source_draft("فین‌تک ایران", "پرداخت و بانکداری")
        self.assertIsNotNone(draft)
        self.assertEqual("local_keyword_match", draft["draft_source"])
        self.assertEqual("source", draft["output_language"])
        payload = SourceUpdate(language="en", output_language="de")
        self.assertEqual("en", payload.language)
        self.assertEqual("de", payload.output_language)

    def test_transient_media_probe_failure_keeps_draft_editable(self):
        draft = {
            "name": "Example Media",
            "homepage_url": "https://example.com/",
            "fetch_url": "https://example.com/feed/",
            "adapter": "rss",
            "match_status": "match",
        }
        with patch("app.admin.SourceFetcher.fetch", new=AsyncMock(side_effect=FetchFailure("source request failed"))):
            result = asyncio.run(_verify_source_draft(draft))
        self.assertEqual("needs_review", result["status"])
        self.assertTrue(result["editable"])

    def test_unknown_media_returns_actionable_alternatives_without_provider(self):
        draft = _local_source_draft("رسانه ناشناخته", "")
        self.assertIsNone(draft)
        result = _local_source_suggestions("کلیدواژه ناشناخته", "")
        self.assertEqual([], result["suggestions"])
        self.assertGreaterEqual(len(result["alternatives"]), 1)

    def test_authenticated_client_error_uses_dedicated_bounded_endpoint(self):
        session_token = "authenticated-client-error-session"
        csrf_token = new_csrf_token(session_token, settings)

        def authenticated_client():
            client = TestClient(app)
            client.cookies.set("research_bee_admin_session", session_token)
            client.cookies.set("research_bee_admin_csrf", csrf_token)
            return client

        headers = {"X-CSRF-Token": csrf_token}
        with patch("app.main.current_admin", new=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))):
            response = authenticated_client().post(
                "/admin/api/security/client-error",
                json={"kind": "window", "view": "sources"},
                headers=headers,
            )
        self.assertEqual(204, response.status_code)
        with patch("app.main.current_admin", new=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))):
            action_response = authenticated_client().post(
                "/admin/api/security/client-error",
                json={
                    "kind": "action",
                    "view": "topics",
                    "action": "catalog_topic",
                    "phase": "request",
                    "outcome": "error",
                    "route": "/admin/api/assistants/123/sources",
                    "status": 500,
                    "duration_ms": 321,
                },
                headers=headers,
            )
        self.assertEqual(204, action_response.status_code)
        body = TestClient(app).get("/admin").text
        self.assertIn("/admin/api/security/client-error", body)
        self.assertNotIn("/health?client_error=", body)

    def test_admin_ui_media_topic_actions_are_stable_during_first_paint(self):
        body = TestClient(app).get("/admin").text
        # The final action layer must recover an authorized workspace before
        # invoking add/probe/suggestion actions, and table callbacks must be
        # globally resolvable after the CSP attribute migration.
        self.assertIn("const actionHandlers={addPublicSocialSourceBtn:'openPublicSocialSourceModal',sourceSuggestionBtn:'openSourceSuggestionsModal',sourceProbeBtn:'probeSelectedSources'}", body)
        self.assertIn("const catalogHandlers={source:'openCreateSourceModal',topic:'openCreateTopicModal'}", body)
        self.assertIn("const ensureWorkspace=async()=>", body)
        self.assertIn("button.dataset.adminActionBound='1'", body)
        self.assertIn("button.addEventListener('click',event=>{", body)
        self.assertIn("button.onclick=null;", body)
        self.assertIn("const workspaceGateIds=new Set(", body)
        self.assertIn("const handleWorkspaceGate=event=>", body)
        self.assertIn("void ensureWorkspace().then(ready=>", body)
        self.assertIn("const replay=doc.getElementById(button.id);", body)
        self.assertIn("replay.dataset.workspaceReplay='1';", body)
        self.assertIn("const actionTrace=(action,phase,outcome,details={})=>", body)
        self.assertIn("window.__researchBeeTraceRequest=", body)
        self.assertIn("actionTrace(actionName,'timeout','error'", body)
        self.assertIn("reportOverviewClientError('action',{action:actionName,phase:phaseName,outcome:result", body)
        self.assertIn("const handleCatalogCreate=async event=>", body)
        self.assertIn("if(!(await ensureWorkspace()))", body)
        self.assertIn("origin?.closest?.('[data-catalog-create]')", body)
        self.assertIn("event.preventDefault();event.stopImmediatePropagation();", body)
        self.assertIn("doc.addEventListener('click',handleCatalogCreate,true)", body)
        self.assertIn("const run=()=>{normalizePageActions();prepareCatalogButtons();prepareActionButtons()}", body)
        self.assertIn("An action used to fail silently here", body)
        self.assertIn("try{reportOverviewClientError('window')}catch(_){}", body)
        self.assertIn("window.__researchBeeReconcileWorkspaceActions?.();", body)
        self.assertIn("window.openCreateTopicModal=openCreateTopicModal", body)
        self.assertIn("window.toggleSource=toggleSource;window.openSourceModal=openSourceModal", body)
        self.assertIn("window.toggleTopic=toggleTopic;window.openTopicModal=openTopicModal", body)
        self.assertIn("window.deleteSourceFromUi=deleteSourceFromUi;window.deleteTopicFromUi=deleteTopicFromUi", body)
        self.assertIn("The stable capture listener below is the only catalog-create path", body)

    def test_admin_final_normalizer_does_not_create_a_mutation_feedback_loop(self):
        body = TestClient(app).get("/admin").text
        # The final hardening layer observes the app tree.  It must not call
        # appendChild for an already-correct action order, otherwise its own
        # childList observer schedules a new normalization frame forever.
        self.assertIn("function reorderIfNeeded(group,ordered)", body)
        self.assertIn("current.every((node,index)=>node===ordered[index])", body)
        self.assertIn("reorderIfNeeded(assistantGroup,[...neutral,...primary])", body)
        self.assertIn("reorderIfNeeded(group,[...rest,...primary])", body)
        self.assertNotIn("[...neutral,...primary].forEach(node=>assistantGroup.appendChild(node))", body)
        self.assertNotIn("[...rest,...primary].forEach(node=>group.appendChild(node))", body)

    def test_local_vazirmatn_assets_are_served_without_relaxing_csp(self):
        response = TestClient(app).get("/assets/Vazirmatn-Regular.woff2")
        self.assertEqual(200, response.status_code)
        self.assertEqual("font/woff2", response.headers["content-type"])
        page = TestClient(app).get("/admin")
        self.assertIn('/assets/Vazirmatn-Regular.woff2', page.text)
        self.assertNotIn("cdn.jsdelivr.net/gh/rastikerdar", page.text)
        policy = page.headers["content-security-policy"]
        self.assertNotIn("fonts.googleapis.com", policy)
        self.assertNotIn("fonts.gstatic.com", policy)

    def test_business_free_assistant_request_and_source_urls_are_validated(self):
        assistant = AssistantRequest(slug="general-market", name="General market")
        self.assertEqual("", assistant.business_name)
        clone = AssistantCloneRequest(slug="general-market-copy", name="General market copy")
        self.assertEqual("", clone.business_name)
        source = SourceCreate(
            name="Example",
            homepage_url="https://example.com",
            fetch_url="https://example.com/feed.xml",
        )
        self.assertEqual("https://example.com", source.homepage_url)
        with self.assertRaises(ValueError):
            SourceCreate(
                name="Broken",
                homepage_url="not-a-url",
                fetch_url="https://example.com/feed.xml",
            )

    def test_admin_ui_reflects_project_scoped_rbac(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("Every role requires explicit project assignment", body)
        self.assertIn("[['newAssistantBtn',owner],['newUserBtn',projectAdmin],['healthProbeBtn',owner],['operations',owner]]", body)
        self.assertIn("['operations',owner]", body)
        self.assertIn("canViewOperations", body)
        self.assertIn("const assistant_ids=[...document.querySelectorAll('.user-project-choice:checked')].map(x=>x.value)", body)
        self.assertNotIn("targetRole==='admin'||targetRole==='owner'?[]", body)

    def test_admin_ui_ignores_stale_unauthorized_responses_after_login(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const transition=authTransition", body)
        self.assertIn("if(transition===authTransition)showLogin()", body)
        self.assertIn("function setUserHeader(user)", body)

    def test_admin_ui_has_mi047_weekly_schedule_and_reliable_sidebar(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="scheduleGrid"', body)
        self.assertIn('role="grid"', body)
        self.assertIn("ساعت انتشار در", body)
        self.assertIn("حداقل یک ساعت را انتخاب کنین", body)
        self.assertIn("Array.from({length:24}", body)
        self.assertIn("function scheduleDays()", body)
        self.assertIn("function collectScheduleSlots()", body)
        self.assertNotIn('id="scheduleTimes"', body)
        self.assertNotIn("$('scheduleTimes').value", body)
        self.assertIn("sidebarOverlay", body)
        self.assertIn("closeSidebar", body)
        self.assertIn("باز و بسته کردن منوی کناری", body)
        self.assertIn("ویرایش اطلاعات ربات و کانال‌ها", body)
        self.assertIn("bot_id", body)

    def test_admin_ui_has_mi048_user_flow_feedback_copy_and_workspace_guard(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("openNewUserModal", body)
        self.assertIn("ensureUserControls", body)
        self.assertIn("ویرایش و تغییر رمز", body)
        self.assertIn("euPasswordAgain", body)
        self.assertIn("Selected hours", body)
        self.assertIn("Line chart", body)
        self.assertIn("r.assistant_id", body)
        self.assertIn("پروفایل بیزینس این پروژه در دسترس نیست.", body)

    def test_admin_ui_has_mi049_project_access_channel_cards_and_mobile_controls(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("manageUserAccess", body)
        self.assertIn("/members/", body)
        self.assertIn("دسترسی پروژه", body)
        self.assertIn("ویرایش مشخصات ربات", body)
        self.assertIn("mobile-first workspace controls", body)

    def test_admin_ui_has_mi050_overview_data_fallback_and_load_state(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("overviewLoadState", body)
        self.assertIn("Some overview data could not be loaded", body)
        self.assertIn("kpiAnalyses", body)
        self.assertIn("modalSubmit", body)
        self.assertIn("$('modalSubmit').onclick=submit;translateStaticCopy()", body)

    def test_admin_ui_has_mi050_completed_feedback_channel_and_dashboard_views(self):
        response = TestClient(app).get("/admin")
        body = response.text
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertIn('id="feedbackActorRows"', body)
        self.assertIn("renderQualityReport", body)
        self.assertIn("feedback-timeline-btn", body)
        self.assertIn('id="channelSettingsCard"', body)
        self.assertIn('id="channelGrid"', body)
        self.assertIn("channel-table-card", body)
        self.assertIn("data-edit-telegram", body)
        self.assertIn("const channelEditButton=document.querySelector('#channelSettingsCard [data-edit-telegram]')", body)
        self.assertIn("bot_display_name", body)
        self.assertIn("Destination channels for this project", body)
        self.assertIn("m.published_today", body)
        self.assertIn("m.pending_previews", body)
        self.assertIn("req('/feedback/report?days=30&assistant_id='+encodeURIComponent(state.assistantId))", body)

    def test_admin_ui_boots_when_legacy_business_button_is_absent(self):
        """A removed legacy control must not abort all later UI initializers."""
        body = TestClient(app).get("/admin").text
        self.assertIn("$('editBusinessBtn')?.addEventListener", body)
        self.assertNotIn("$('editBusinessBtn').onclick=", body)

    def test_template_editor_does_not_expose_version_history_or_rollback(self):
        body = TestClient(app).get("/admin").text
        self.assertNotIn("templateHistory", body)
        self.assertNotIn("data-template-rollback", body)
        self.assertNotIn("/rollback/", body)

    def test_admin_ui_translates_placeholders_and_dynamic_copy(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("[placeholder],[title],[aria-label]", body)
        self.assertIn("reverseCopyMap", body)
        self.assertIn("function roleLabel", body)
        self.assertIn("'ورود به فضای کار':'Open workspace'", body)
        self.assertIn("'ویرایش ربات و کانال‌ها':'Edit bot and channels'", body)

    def test_admin_ui_strips_html_tags_from_overview_publication_titles(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const title=cleanPublicationText(x.message_text||'بدون عنوان').slice(0,48)", body)
        self.assertIn("esc(title)", body)
        self.assertIn("function cleanPublicationText(value)", body)

    def test_news_queue_uses_stable_columns_and_news_source(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('data-publication-column="3">منبع خبر', body)
        self.assertIn('News source', body)
        self.assertIn('class="publication-news-cell"', body)
        self.assertIn("fmtDate(x.article_published_at||x.created_at)", body)
        self.assertIn('colspan="6"', body)
        # Legacy enhancements must be cleanup-only; they must not append
        # workflow/evidence cells to the review queue.
        self.assertNotIn("th.dataset.featureHead", body)
        self.assertNotIn("evidence.innerHTML", body)
        self.assertNotIn("workflow=document.createElement('td')", body)

    def test_admin_ui_mounts_content_template_in_dedicated_content_view(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('data-view="template-content"', body)
        self.assertIn('data-label-en="Content"', body)
        self.assertIn('id="view-template-content"', body)
        self.assertIn('id="templateContentMount"', body)
        self.assertIn("const mount=document.getElementById('templateContentMount')", body)
        self.assertIn("data-template-page-title", body)
        self.assertIn("'template-content':'محتوا'", body)
        self.assertNotIn("b.dataset.labelFa='قالب محتوا'", body)

    def test_admin_ui_converts_field_helpers_to_localized_info_tooltips(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const attach=(labelNode,help)=>", body)
        self.assertIn("help.dataset.infoSource||help.textContent", body)
        self.assertIn("aria-describedby", body)
        self.assertIn("dailyProcessingCapHelp", body)
        self.assertIn("className='info-tip'", body)
        self.assertIn("className='info-tip-popup'", body)
        self.assertIn(".info-tip:hover .info-tip-popup,.info-tip:focus .info-tip-popup", body)

    def test_admin_ui_moves_page_guidance_into_localized_title_info_tips(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const pageInfoSources=", body)
        self.assertIn("'view-businesses':'برای هر دستیار چند پروفایل کسب‌وکار بسازید و یکی را برای تحلیل فعال کنید.'", body)
        self.assertIn("function enhancePageHeadInfo()", body)
        self.assertIn("description.classList.add('page-head-description')", body)
        self.assertIn("button.className='info-tip page-info-tip'", body)
        self.assertIn("button.setAttribute('aria-describedby',bubble.id)", body)
        self.assertIn("enhancePageHeadInfo();", body)

    def test_admin_ui_commits_info_and_locale_before_first_paint(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("window.__researchBeeEnhancePageHeadInfo?.();window.__researchBeeLocalizeAll?.();setView('assistants')", body)
        self.assertIn("let observerQueued=false", body)
        self.assertIn("queueMicrotask(()=>", body)
        self.assertIn("let settleQueued=false", body)
        self.assertIn("select option{background-color:var(--panel);color:var(--ink)}", body)
        self.assertIn("select,.workspace-select,.filter-bar select,.form-grid select,.field select,.language-select{transition:none!important", body)

    def test_support_ticket_categories_are_localized_and_cards_are_balanced(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("const categories=[['account_access','حساب و دسترسی','Account & access']", body)
        self.assertIn("localeLabel(x[1],x[2])", body)
        self.assertIn("window.__researchBeeUpgradeSupportTicket=upgrade", body)
        self.assertIn("b.dataset.labelFa='پشتیبانی';b.dataset.labelEn='Support'", body)
        self.assertIn("const copy=()=>{const t=(fa,en)=>localeLabel(fa,en)", body)
        self.assertIn("normal={fa:'عادی',en:'Normal',tr:'Normal'", body)
        self.assertIn("#view-support .two-col{grid-template-columns:repeat(2,minmax(0,1fr))", body)
        self.assertIn("#view-support [data-support-form]{display:grid;gap:16px}", body)
        self.assertIn("const text={", body)
        self.assertIn("root.classList.add('support-redesign')", body)
        self.assertIn("classList.add('support-layout')", body)
        self.assertIn("data-support-filter", body)
        self.assertIn("support-priority-options", body)
        self.assertIn("support-ticket-item", body)
        self.assertIn("#view-support .support-layout{grid-template-columns:", body)
        self.assertIn("Response priority", body)
        self.assertIn("support-compose-hint", body)
        self.assertIn("support-filter", body)
        self.assertIn("data-submitted-title", body)
        self.assertIn("data-owner-save", body)
        self.assertIn("state.supportAllTickets=data.all_tickets", body)
        self.assertIn("ticket.category==='other'?(ticket.subject||categoryLabel('other')):categoryLabel(ticket.category)", body)

    def test_support_ticket_threaded_owner_and_requester_workflow_is_present(self):
        body = TestClient(app).get("/admin").text
        self.assertIn('id="support-ticket-v4-style"', body)
        self.assertIn('id="support-ticket-v4"', body)
        self.assertIn("/admin/api/support/tickets/'+encodeURIComponent(ticket.id)+'/messages", body)
        self.assertIn("support-v4-ticket", body)
        self.assertIn("support-v4-dialog", body)
        self.assertIn("closedNote", body)
        self.assertIn("در صف پاسخ", body)
        self.assertIn("تیکت بسته شده و امکان ویرایش یا افزودن پیام ندارد.", body)
        self.assertIn("answered:'پاسخ داده شد'", body)
        self.assertIn("if(ticket.status==='closed'){foot.innerHTML", body)
        # Cards are rendered after the initial shell bind.  The stable root
        # must delegate ticket/retry clicks so an owner can open a ticket and
        # submit a reply after every refresh (and after a locale re-render).
        self.assertIn("const rootFirst=r.dataset.supportV4Bound!=='1'", body)
        self.assertIn("event.target.closest('[data-support-v4-ticket]')", body)
        self.assertIn("const owner=model.canManage,messages=ticket.messages||[]", body)

    def test_support_ticket_list_forwards_server_side_triage_filters(self):
        user = SimpleNamespace(id=uuid.uuid4(), username="owner", email="farhad.dgm@gmail.com", role="admin")
        expected = {"tickets": [], "my_tickets": [], "all_tickets": [], "can_manage": True}
        with (
            patch("app.main.current_admin", new=AsyncMock(return_value=user)),
            patch("app.main.list_support_tickets", new=AsyncMock(return_value=expected)) as list_tickets,
        ):
            response = TestClient(app).get(
                "/admin/api/support/tickets?status=in_progress&priority=high&search=login&limit=25"
            )
        self.assertEqual(200, response.status_code)
        list_tickets.assert_awaited_once_with(
            user, status="in_progress", priority="high", search="login", limit=25
        )
        self.assertEqual(expected, response.json())

    def test_last_ten_audit_closes_workspace_dashboard_and_schedule_gaps(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("assist=await req('/admin/api/assistants');state.projectListReady=true", body)
        self.assertIn("sources:[],publications:[]", body)
        self.assertIn("m.active_sources", body)
        self.assertIn("m.analyses_today", body)
        self.assertIn("state.health?.status==='healthy'", body)
        self.assertIn("Select at least one publishing hour", body)
        self.assertIn("delete-source-btn", body)
        self.assertIn("delete-topic-btn", body)
        self.assertIn("publishing hours selected across", body)

    def test_researcher_ui_keeps_default_workspace_selection_stable(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("x.slug==='default'", body)
        self.assertIn("Keep the last selected workspace as a preference", body)

    def test_workspace_data_requires_an_authenticated_session(self):
        assistant_id = "00000000-0000-0000-0000-000000000001"
        client = TestClient(app)
        self.assertEqual(401, client.get(f"/metrics?assistant_id={assistant_id}").status_code)
        self.assertEqual(401, client.get(f"/sources?assistant_id={assistant_id}").status_code)
        self.assertEqual(401, client.get(f"/publications?assistant_id={assistant_id}").status_code)

    def test_source_registry_endpoint(self):
        rows = [{"source_key": "S-002", "health_status": "healthy"}]
        with (
            patch("app.main.current_admin", new=AsyncMock(return_value=SimpleNamespace(email="farhad.dgm@gmail.com", role="admin", username="admin"))),
            patch("app.main.list_sources", new=AsyncMock(return_value=rows)),
        ):
            response = TestClient(app).get("/sources")
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()["count"])

    def test_admin_create_source_endpoint_is_wired_to_scoped_service(self):
        assistant_id = uuid.uuid4()
        created = {"id": str(uuid.uuid4()), "source_key": "S-003", "enabled": True}
        user = SimpleNamespace(email="farhad.dgm@gmail.com", role="admin", username="owner")
        payload = {
            "name": "Example feed",
            "homepage_url": "https://example.com",
            "fetch_url": "https://example.com/feed.xml",
            "adapter": "rss",
            "priority": 3,
        }
        with (
            patch("app.main.current_admin", new=AsyncMock(return_value=user)),
            patch("app.main.create_source", new=AsyncMock(return_value=created)) as create,
        ):
            response = TestClient(app).post(
                f"/admin/api/assistants/{assistant_id}/sources", json=payload
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(created, response.json())
        create.assert_awaited_once()
        self.assertEqual(assistant_id, create.await_args.args[0])
        self.assertEqual(payload["name"], create.await_args.args[1].name)
        self.assertEqual(user, create.await_args.args[2])

    def test_admin_create_topic_endpoint_is_wired_to_scoped_service(self):
        assistant_id = uuid.uuid4()
        created = {"id": str(uuid.uuid4()), "topic_key": "T-003", "enabled": True}
        user = SimpleNamespace(email="farhad.dgm@gmail.com", role="admin", username="owner")
        payload = {"name": "Digital payments", "definition": "Payment infrastructure", "importance": 4, "threshold": 0.45}
        with (
            patch("app.main.current_admin", new=AsyncMock(return_value=user)),
            patch("app.main.create_topic", new=AsyncMock(return_value=created)) as create,
        ):
            response = TestClient(app).post(
                f"/admin/api/assistants/{assistant_id}/topics", json=payload
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(created, response.json())
        create.assert_awaited_once()
        self.assertEqual(assistant_id, create.await_args.args[0])
        self.assertIsInstance(create.await_args.args[1], TopicCreate)
        self.assertEqual(payload["name"], create.await_args.args[1].name)
        self.assertEqual(user, create.await_args.args[2])

    def test_source_health_probe_checks_selected_workspace_sources(self):
        assistant_id = uuid.uuid4()
        result = {"status": "completed", "source_count": 2, "healthy": 2, "failed": 0}
        with (
            patch("app.main.require_workspace_scope", new=AsyncMock()) as scope,
            patch("app.main.run_source_health_probe", new=AsyncMock(return_value=result)) as probe,
        ):
            response = TestClient(app).post(f"/sources/health-probe?assistant_id={assistant_id}")
        self.assertEqual(200, response.status_code)
        self.assertEqual(result, response.json())
        scope.assert_awaited_once_with(None, assistant_id, write=True)
        probe.assert_awaited_once_with(assistant_id=assistant_id, force=True)

    def test_admin_source_probe_is_scoped_and_never_publishes(self):
        assistant_id = uuid.uuid4()
        source_id = uuid.uuid4()
        result = {
            "status": "completed", "source_id": str(source_id),
            "posts_found": 10, "texts_extractable": 9, "related": 2,
            "near_threshold": 1, "top_results": [], "no_publish": True,
        }
        with (
            patch("app.main.require_workspace_scope", new=AsyncMock()) as scope,
            patch("app.main.run_source_probe", new=AsyncMock(return_value=result)) as probe,
        ):
            response = TestClient(app).post(
                f"/admin/api/assistants/{assistant_id}/sources/{source_id}/probe"
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(result, response.json())
        scope.assert_awaited_once_with(None, assistant_id, write=True)
        probe.assert_awaited_once_with(source_id, assistant_id=assistant_id, limit=20)

    def test_admin_ui_health_probe_is_workspace_scoped_and_refreshes_rows(self):
        body = TestClient(app).get("/admin").text
        self.assertIn("async function probeSelectedSources()", body)
        self.assertIn("/sources/health-probe?assistant_id='+encodeURIComponent(state.assistantId)", body)
        self.assertIn("await loadAll();const count=Number(result.source_count??0)", body)

    def test_manual_ingestion_endpoint(self):
        result = {"status": "completed", "source_count": 1}
        with patch("app.main.require_workspace_scope", new=AsyncMock()) as scope, patch("app.main.run_ingestion", new=AsyncMock(return_value=result)) as run:
            response = TestClient(app).post(
                "/ingestion/run",
                json={"source_keys": ["S-002"], "force": True},
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual("completed", response.json()["status"])
        scope.assert_awaited_once_with(None, None, write=True)
        run.assert_awaited_once_with(["S-002"], force=True)

    def test_refresh_previews_endpoint_never_publishes(self):
        result = {"candidates": 3, "refreshed": 3}
        with patch("app.main.current_admin", new=AsyncMock(return_value=SimpleNamespace(email="farhad.dgm@gmail.com", role="admin", username="admin"))), patch(
            "app.main.refresh_publication_previews",
            new=AsyncMock(return_value=result),
        ) as refresh:
            response = TestClient(app).post(
                "/publications/refresh-previews",
                params={"limit": 3},
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(result, response.json())
        refresh.assert_awaited_once_with(limit=3)


if __name__ == "__main__":
    unittest.main()
