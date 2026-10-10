import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import google_auth, login_history, main
from app.report_portal import auth as report_auth


def database(session):
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


class LoginHistoryStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_unlisted_google_email_is_saved_without_account_or_log_exposure(self):
        session = MagicMock(commit=AsyncMock())
        with patch.object(login_history, "SessionLocal", database(session)), patch.object(login_history, "LOGGER") as logger:
            await login_history.record_login_attempt(method="google", portal="admin", successful=False,
                email="Unlisted.Account+work@gmail.com", reason="not_allowed")
        event = session.add.call_args.args[0]
        self.assertEqual(event.action, "auth.login")
        self.assertEqual(event.severity, "info")
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.details["email"], "unlisted.account+work@gmail.com")
        self.assertEqual(event.details["outcome"], "failure")
        self.assertEqual(event.details["reason"], "not_allowed")
        session.commit.assert_awaited_once()
        logger.assert_not_called()
        self.assertFalse(logger.method_calls)

    async def test_legacy_username_uses_account_email_snapshot(self):
        user = SimpleNamespace(id=uuid.uuid4(), email="account@gmail.com")
        session = MagicMock(scalar=AsyncMock(return_value=user), commit=AsyncMock())
        with patch.object(login_history, "SessionLocal", database(session)):
            await login_history.record_login_attempt(method="password", portal="user", successful=True, username="old-user")
        event = session.add.call_args.args[0]
        self.assertEqual(event.actor_id, user.id)
        self.assertEqual(event.details["email"], user.email)
        self.assertEqual(event.details["portal"], "user")
        self.assertEqual(event.details["outcome"], "success")

    async def test_unknown_password_email_is_saved(self):
        session = MagicMock(scalar=AsyncMock(return_value=None), commit=AsyncMock())
        with patch.object(login_history, "SessionLocal", database(session)):
            await login_history.record_login_attempt(method="password", portal="admin", successful=False,
                username="missing@gmail.com", reason="invalid_credentials")
        self.assertEqual(session.add.call_args.args[0].details["email"], "missing@gmail.com")

    async def test_database_failure_never_logs_identity_or_exception(self):
        session = MagicMock(commit=AsyncMock(side_effect=RuntimeError("private@gmail.com")))
        with patch.object(login_history, "SessionLocal", database(session)), patch.object(login_history, "LOGGER") as logger:
            await login_history.record_login_attempt(method="google", portal="admin", successful=False, email="private@gmail.com")
        self.assertNotIn("private", str(logger.method_calls))
        logger.error.assert_called_once()

    async def test_page_is_limited_to_ten_with_stable_newest_first_order(self):
        now = datetime.now(timezone.utc)
        row = dict(id="login:fixture", created_at=now, email="one@gmail.com", username=None,
            method="google", portal="admin", outcome="success", reason=None)
        session = MagicMock(scalar=AsyncMock(return_value=23), execute=AsyncMock(return_value=MagicMock()))
        session.execute.return_value.mappings.return_value.all.return_value = [row]
        with patch("app.admin._require_owner"), patch.object(login_history, "SessionLocal", database(session)):
            result = await login_history.list_login_history(SimpleNamespace(), page=2)
        statement = session.execute.call_args.args[0]
        self.assertEqual(statement._limit_clause.value, 10)
        self.assertEqual(statement._offset_clause.value, 10)
        self.assertIn("created_at DESC", str(statement))
        self.assertIn("id DESC", str(statement))
        self.assertEqual((result["page"], result["page_size"], result["total"], result["pages"]), (2, 10, 23, 3))
        self.assertEqual(result["attempts"][0]["created_at"], now.isoformat())


class LoginHistoryRouteTests(unittest.TestCase):
    def test_only_owner_can_read_report_and_pages_are_validated(self):
        client = TestClient(main.app)
        self.assertEqual(401, client.get("/admin/api/owner/login-history").status_code)
        non_owner = SimpleNamespace(id=uuid.uuid4(), role="admin", email="nonowner@gmail.com", username="nonowner")
        with patch.object(main, "current_admin", AsyncMock(return_value=non_owner)), patch.object(login_history, "SessionLocal") as db:
            self.assertEqual(403, client.get("/admin/api/owner/login-history").status_code)
            db.assert_not_called()
            self.assertEqual(422, client.get("/admin/api/owner/login-history?page=0").status_code)

    def callback(self, *, identity=None, denial=None, portal="admin", flow_error=None):
        recorder = AsyncMock()
        user = SimpleNamespace(id=uuid.uuid4())
        with patch.object(google_auth, "read_flow", side_effect=flow_error, return_value={"portal": portal}), \
             patch.object(google_auth, "finish_flow", AsyncMock(return_value=identity)), \
             patch.object(main, "login_ip_attempts_exceeded", AsyncMock(return_value=False)), \
             patch.object(main, "record_ip_login_failure", AsyncMock()), \
             patch.object(main, "login_with_google", AsyncMock(side_effect=denial, return_value=("synthetic-session", user))), \
             patch.object(main, "record_login_attempt", recorder), \
             patch("app.accounts.admin._audit", AsyncMock()):
            response = TestClient(main.app).get("/auth/google/callback?code=fixture&state=fixture&email=forged@gmail.com", follow_redirects=False)
        recorder.assert_awaited_once()
        return response, recorder.await_args.kwargs

    def test_google_allowlist_denial_records_verified_email_without_session(self):
        identity = google_auth.GoogleIdentity(sub="fixture", email="unlisted@gmail.com", email_verified=True)
        response, event = self.callback(identity=identity, denial=google_auth.GoogleAuthError("not_allowed"))
        self.assertEqual(302, response.status_code)
        self.assertEqual("/admin?login_error=not_allowed", response.headers["location"])
        self.assertNotIn("research_bee_admin_session", response.headers.get("set-cookie", ""))
        self.assertEqual(event, dict(method="google", portal="admin", successful=False, email="unlisted@gmail.com", reason="not_allowed"))

    def test_google_success_records_portal_and_account(self):
        identity = google_auth.GoogleIdentity(sub="fixture", email="allowed@gmail.com", email_verified=True)
        response, event = self.callback(identity=identity, portal="user")
        self.assertEqual("/user", response.headers["location"])
        self.assertEqual(event["email"], identity.email)
        self.assertTrue(event["successful"])
        self.assertEqual("user", event["portal"])
        self.assertIsInstance(event["actor_id"], uuid.UUID)

    def test_google_report_success_uses_independent_cookie_and_history_scope(self):
        identity = google_auth.GoogleIdentity(sub="fixture", email="allowed@gmail.com", email_verified=True)
        response, event = self.callback(identity=identity, portal="report")
        self.assertEqual("/report", response.headers["location"])
        self.assertIn("research_bee_report_session", response.headers.get("set-cookie", ""))
        self.assertNotIn("research_bee_admin_session", response.headers.get("set-cookie", ""))
        self.assertEqual("report", event["portal"])
        self.assertTrue(event["successful"])

    def test_invalid_flow_never_accepts_email_from_query(self):
        response, event = self.callback(flow_error=google_auth.GoogleAuthError("expired"))
        self.assertEqual("/admin?login_error=expired", response.headers["location"])
        self.assertIsNone(event["email"])
        self.assertFalse(event["successful"])

    def test_password_success_failure_denial_and_rate_limit_are_recorded(self):
        for portal in ("admin", "user", "report"):
            for status, denial, limited, reason in (
                (200, None, False, None),
                (401, HTTPException(401, "invalid credentials"), False, "invalid_credentials"),
                (403, HTTPException(403, "account_disabled"), False, "inactive"),
                (403, HTTPException(403, "user portal access denied"), False, "not_allowed"),
                (429, None, True, "rate_limited"),
            ):
                with self.subTest(portal=portal, status=status, reason=reason):
                    recorder = AsyncMock()
                    with patch.object(main, "canonical_login_identity", AsyncMock(return_value="account:fixture")), \
                         patch.object(main, "login_attempts_exceeded", AsyncMock(return_value=limited)), \
                         patch.object(main, "record_security_event", AsyncMock()), \
                         patch.object(main, "record_login_failure", AsyncMock()), \
                         patch.object(main, "clear_login_failures", AsyncMock()), \
                         patch.object(main, "record_login_attempt", recorder), \
                         patch.object(report_auth if portal == "report" else main,
                             "login" if portal == "report" else "admin_login" if portal == "admin" else "reader_login",
                             AsyncMock(side_effect=denial, return_value={"id": "fixture"})):
                        response = TestClient(main.app).post(f"/{portal}/api/login", json={"email": "fixture@gmail.com", "password": "synthetic-password"})
                    self.assertEqual(status, response.status_code)
                    recorder.assert_awaited_once()
                    details = recorder.await_args.kwargs
                    self.assertEqual(portal, details["portal"])
                    self.assertEqual("fixture@gmail.com", details["username"])
                    self.assertEqual(status == 200, details["successful"])
                    self.assertEqual(reason, details.get("reason"))
