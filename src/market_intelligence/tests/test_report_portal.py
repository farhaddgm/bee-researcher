import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.config import get_settings
from app.google_auth import (
    safe_redirect,
    GoogleAuthError,
    start_flow,
    flow_portal,
    read_flow,
)
from app.portals import portal_spec
from app.report_portal import crypto
from app.report_portal.contracts import Draft
from app.report_portal.provider import PrivateClient


class PrivateReports(unittest.TestCase):
    def setUp(self):
        self.settings = get_settings().model_copy(
            update={"report_encryption_secret": SecretStr("a" * 48)}
        )

    def test_encryption_and_tenant_aad(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        with patch.object(crypto, "get_settings", return_value=self.settings):
            sealed = crypto.encrypt(a, "version", {"text": "private-marker"})
            self.assertNotIn("private-marker", sealed)
            self.assertEqual(
                crypto.decrypt(a, "version", sealed)["text"], "private-marker"
            )
            for biz, scope, data in [
                (b, "version", sealed),
                (a, "job", sealed),
                (a, "version", sealed[:-4] + "xxxx"),
            ]:
                with self.assertRaises(HTTPException):
                    crypto.decrypt(biz, scope, data)

    def test_rotation(self):
        a = uuid.uuid4()
        with patch.object(crypto, "get_settings", return_value=self.settings):
            sealed = crypto.encrypt(a, "v", {"text": "rotation"})
        rotated = self.settings.model_copy(
            update={
                "report_encryption_secret": SecretStr("b" * 48),
                "report_previous_encryption_secrets": SecretStr(json.dumps(["a" * 48])),
            }
        )
        with patch.object(crypto, "get_settings", return_value=rotated):
            self.assertEqual(crypto.decrypt(a, "v", sealed), {"text": "rotation"})

    def test_missing_key_fails_closed(self):
        with patch.object(
            crypto,
            "get_settings",
            return_value=self.settings.model_copy(
                update={"report_encryption_secret": None}
            ),
        ):
            with self.assertRaises(HTTPException):
                crypto.encrypt(uuid.uuid4(), "v", {})

    def test_report_redirect_is_not_admin_fallback(self):
        self.assertEqual(safe_redirect("report", "/admin"), "/report")
        self.assertEqual(safe_redirect("report", "https://evil.test"), "/report")
        with self.assertRaises(GoogleAuthError):
            safe_redirect("unknown", None)
        self.assertNotEqual(portal_spec("report").session, portal_spec("user").session)

    def test_signed_oauth_flow_carries_report_not_admin(self):
        cfg = self.settings.model_copy(
            update={
                "google_client_id": "synthetic.apps.googleusercontent.com",
                "google_client_secret": SecretStr("synthetic"),
                "google_redirect_uri": "https://synthetic.invalid/auth/google/callback",
                "csrf_signing_secret": SecretStr(
                    "synthetic-signing-material-for-report-only"
                ),
            }
        )
        url, cookie = start_flow(cfg, "report", "/report")
        self.assertIn("code_challenge=", url)
        self.assertEqual(flow_portal(read_flow(cfg, cookie)), "report")

    def test_strict_bounded_input(self):
        data = dict(
            business_id=uuid.uuid4(),
            assistant_id=uuid.uuid4(),
            title="Valid title",
            text="Full report " * 20,
            reporter="User",
            tags=["software"],
        )
        self.assertEqual(Draft(**data).classification, "internal")
        for patch_data in [
            {"text": "short"},
            {"tags": ["x" * 61]},
            {"author_id": str(uuid.uuid4())},
            {"event_date": "2026-02-31"},
            {"language": "xx"},
        ]:
            with self.assertRaises(ValidationError):
                Draft(**{**data, **patch_data})

    def test_private_package_has_no_public_pipeline_import(self):
        for file in (Path(__file__).parent.parent / "app/report_portal").glob("*.py"):
            self.assertNotIn("from app.pipeline_service import", file.read_text())
            self.assertNotIn("from app.telegram_delivery import", file.read_text())


class Provider(unittest.IsolatedAsyncioTestCase):
    async def test_worker_error_is_content_free_and_does_not_escape(self):
        import asyncio
        from app.report_portal.service import _resilient_loop

        stop = asyncio.Event()

        async def broken(stop):
            stop.set()
            raise RuntimeError("PRIVATE-LOG-MARKER")

        with self.assertLogs("app.report_portal.service", level="WARNING") as logs:
            await _resilient_loop(broken, stop)
        self.assertNotIn("PRIVATE-LOG-MARKER", " ".join(logs.output))

    async def test_no_storage_no_tools_no_retry(self):
        calls = []

        async def guard():
            pass

        def transport(request):
            calls.append(json.loads(request.content))
            return httpx.Response(503, json={"error": {"message": "PRIVATE RESPONSE"}})

        cfg = get_settings().model_copy(
            update={
                "openai_api_key": SecretStr("synthetic"),
                "external_analysis_approved": True,
            }
        )
        c = PrivateClient(cfg, guard=guard, transport=httpx.MockTransport(transport))
        with self.assertRaises(Exception) as failure:
            await c._post("/responses", {"store": False})
        self.assertNotIn("PRIVATE RESPONSE", str(failure.exception))
        self.assertEqual(len(calls), 1)
        self.assertFalse(c.usage_complete)
        with self.assertRaises(Exception):
            await c._post("/responses", {"store": True})
        with self.assertRaises(Exception):
            await c._post(
                "/responses", {"store": False, "tools": [{"type": "web_search"}]}
            )
        self.assertEqual(len(calls), 1)
