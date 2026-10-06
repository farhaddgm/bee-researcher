import asyncio
import ast
import os
import re
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from pydantic import SecretStr

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.config import Settings
from app.contenter import (ContenterClient, ContenterError, _user, cache_visible, connection_status,
                            export_hash, normalize_export, safe_origin, SECTION_KEYS, LinkRequest, set_link)


def settings(**extra):
    return Settings(postgres_db="test", postgres_user="test", postgres_password="test-password",
        redis_password="test-password", admin_bootstrap_password="safe-non-default-test-password",
        contenter_api_url="https://contenter.example/api", contenter_web_url="https://contenter.example",
        contenter_token=SecretStr("test-secret-" + "r" * 40), **extra)


def fixture(**extra):
    return {"schemaVersion": 1, "exportedAt": "2026-10-06T10:00:00Z",
        "business": {"id": "biz1", "name": "Example", "status": "ACTIVE", "gaps": ["Needs review"]},
        "sections": [{"key": key, "content": "Example profile" if key == "OVERVIEW" else "", "reviewedAt": None} for key in SECTION_KEYS],
        "facts": [], "terms": [], "notes": [], "references": [], "assets": [], **extra}


class ContenterContractTests(unittest.TestCase):
    def test_normalizes_profile_and_excludes_secrets_people_and_files(self):
        raw = fixture(password="do-not-store", createdById="person-id")
        raw["business"]["apiKey"] = "do-not-store"
        raw["sections"][0]["updatedById"] = "person-id"
        raw["assets"] = [{"title": "A", "storageKey": "secret/file", "analysis": {"summary": "Good", "apiKey": "do-not-store"}}]
        cleaned = normalize_export(raw, "biz1")
        self.assertEqual("Example profile", cleaned["sections"][0]["content"])
        self.assertEqual("Good", cleaned["assets"][0]["analysis"]["summary"])
        self.assertNotIn("do-not-store", str(cleaned))
        self.assertNotIn("person-id", str(cleaned))
        self.assertNotIn("storageKey", str(cleaned))

    def test_hash_is_stable_for_export_time_and_unknown_keys_but_changes_with_content(self):
        a = normalize_export(fixture(), "biz1")
        b = normalize_export(fixture(exportedAt="later", secret="ignore"), "biz1")
        self.assertEqual(export_hash(a), export_hash(b))
        b["sections"][0]["content"] = "changed"
        self.assertNotEqual(export_hash(a), export_hash(b))

    def test_identity_schema_and_incomplete_response_fail_closed(self):
        for value in [fixture(schemaVersion=2), fixture(schemaVersion=True), fixture(sections={}), fixture(sections=[]), fixture(facts=None),
                      fixture(sections=fixture()["sections"] + [fixture()["sections"][0]]),
                      fixture(business={"id":"other","name":"X","status":"ACTIVE"}),
                      fixture(business={"id":"biz1","name":"","status":"ACTIVE"})]:
            with self.assertRaises(ContenterError): normalize_export(value, "biz1")

    def test_configuration_is_secret_free_and_disabled_by_default(self):
        self.assertTrue(connection_status(settings())["configured"])
        self.assertFalse(connection_status(settings())["ai_usage_enabled"])
        self.assertNotIn("test-secret", str(connection_status(settings())))
        s = settings(); s.contenter_token = None
        self.assertFalse(connection_status(s)["configured"])
        with self.assertRaises(ContenterError): ContenterClient(s)

    def test_pinned_origins_refuse_credentials_queries_fragments_and_insecure_transport(self):
        for url in ["http://example.com", "https://u:p@example.com", "https://example.com/?token=x", "https://example.com/#x", "https://example.com/another"]:
            with self.assertRaises(ContenterError): safe_origin(url)
        self.assertEqual("https://example.com/api", safe_origin("https://example.com/api", api=True))

    def test_cached_profile_is_hidden_after_revoke_missing_archive_or_expiry(self):
        now = datetime.now(timezone.utc)
        link = SimpleNamespace(state="healthy", last_success_at=now)
        self.assertTrue(cache_visible(link, settings(), now=now))
        link.state = "stale"; self.assertTrue(cache_visible(link, settings(), now=now))
        for state in ["access_revoked", "unavailable", "archived"]:
            link.state=state; self.assertFalse(cache_visible(link, settings(), now=now))
        link.state="healthy";link.last_success_at=now-timedelta(days=2)
        self.assertFalse(cache_visible(link, settings(), now=now))

    def test_linking_never_implicitly_activates_research_context(self):
        app_dir = Path(__file__).resolve().parents[1] / "app"
        text=(app_dir/"contenter.py").read_text()
        self.assertNotIn('config["active_business_id"]', text)
        self.assertNotIn("BusinessProfile(", text)
        self.assertNotIn("OpenAIClient", text)
        self.assertNotIn("ProjectResearchContext(", text)

    def test_eight_locale_catalogs_have_complete_aligned_fields(self):
        text = (Path(__file__).resolve().parents[1]/"app"/"admin_contenter.js").read_text()
        catalogs = re.findall(r"^    ([a-z]{2}): (\[.*\]),?$", text, re.MULTILINE)
        for language in ["fa","en","tr","ar","es","it","de","fr"]:
            lengths = [len(ast.literal_eval(value)) for key, value in catalogs if key == language]
            self.assertEqual([39, 15], lengths, language)
        self.assertNotIn("onclick=", text)


class ContenterHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_researcher_routes_and_bearer_headers_are_used(self):
        calls=[]
        def handle(request):
            calls.append(request)
            return httpx.Response(200,json=fixture())
        result=await ContenterClient(settings(),transport=httpx.MockTransport(handle)).export("biz1")
        self.assertEqual("biz1",result["business"]["id"])
        self.assertEqual("/api/integrations/researcher/businesses/biz1/export",calls[0].url.path)
        self.assertTrue(calls[0].headers["authorization"].startswith("Bearer test-secret"))
        self.assertNotIn("test-secret",str(calls[0].url))

    async def test_status_failures_and_redirects_do_not_leak_upstream_body(self):
        for status,code in [(401,"access_revoked"),(403,"access_revoked"),(404,"unavailable"),(500,"upstream_error"),(302,"upstream_error")]:
            transport=httpx.MockTransport(lambda request:httpx.Response(status,text="secret-auth-cookie",headers={"Location":"https://evil.example"}))
            with self.assertRaises(ContenterError) as error: await ContenterClient(settings(),transport=transport).get("/ping")
            self.assertEqual(code,error.exception.code)
            self.assertNotIn("secret-auth-cookie",str(error.exception))

    async def test_oversized_or_invalid_json_is_rejected(self):
        for body,code in [(b"x"*6_000_001,"response_too_large"),(b"broken","invalid_response"),(b"[]","invalid_response")]:
            with self.assertRaises(ContenterError) as error:
                await ContenterClient(settings(),transport=httpx.MockTransport(lambda request:httpx.Response(200,content=body))).get("/ping")
            self.assertEqual(code,error.exception.code)

    async def test_timeout_is_sanitized(self):
        def handle(request): raise httpx.ReadTimeout("secret details",request=request)
        with self.assertRaises(ContenterError) as error:
            await ContenterClient(settings(),transport=httpx.MockTransport(handle)).get("/ping")
        self.assertEqual("unreachable",error.exception.code)

    async def test_nonowner_cannot_read_global_configuration(self):
        with patch("app.contenter.current_admin",new=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))), patch("app.contenter.is_owner",return_value=False):
            with self.assertRaises(HTTPException) as error: await _user("session")
            self.assertEqual(403,error.exception.status_code)

    async def test_scoped_operations_enforce_the_existing_workspace_write_boundary(self):
        actor=SimpleNamespace(id=uuid.uuid4()); assistant=uuid.uuid4()
        with patch("app.contenter.current_admin",new=AsyncMock(return_value=actor)), patch("app.contenter._require_assistant_access",new=AsyncMock(return_value=SimpleNamespace(deleted_at=None))) as access:
            self.assertEqual(actor,await _user("session",assistant,write=True))
            access.assert_awaited_once_with(assistant,actor,write=True)
        with patch("app.contenter.current_admin",new=AsyncMock(return_value=actor)), patch("app.contenter._require_assistant_access",new=AsyncMock(side_effect=HTTPException(403,"denied"))):
            with self.assertRaises(HTTPException): await _user("session",assistant,write=True)

    async def test_revoked_write_access_during_remote_io_prevents_link_storage(self):
        actor = SimpleNamespace(id=uuid.uuid4())
        with patch("app.contenter._user", new=AsyncMock(side_effect=[actor, HTTPException(403, "revoked")])) as access, \
             patch("app.contenter.get_settings", return_value=settings()), \
             patch("app.contenter.ContenterClient.export", new=AsyncMock(return_value=normalize_export(fixture(), "biz1"))), \
             patch("app.contenter.SessionLocal") as sessions:
            with self.assertRaises(HTTPException) as error:
                await set_link(uuid.uuid4(), LinkRequest(business_id="biz1"), "session")
            self.assertEqual(403, error.exception.status_code)
            self.assertEqual(2, access.await_count)
            sessions.assert_not_called()


if __name__ == "__main__": unittest.main()
