import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.product_status import observed_provider_state  # noqa: E402


class ProductReliabilityTest(unittest.TestCase):
    def job(self, status, error=None, age=0):
        return SimpleNamespace(status=status, error_message=error, created_at=datetime.now(timezone.utc)-timedelta(minutes=age), finished_at=None)

    def test_configured_key_is_not_reported_as_healthy(self):
        result = observed_provider_state(configured=True, latest=None, cooling={})
        self.assertEqual("not_checked", result["state"])

    def test_missing_approval_overrides_previous_success(self):
        self.assertEqual("not_configured", observed_provider_state(configured=False, latest=self.job("succeeded"), cooling={})["state"])

    def test_quota_failure_has_safe_actionable_code(self):
        result = observed_provider_state(configured=True, latest=self.job("failed", "provider_quota_exhausted"), cooling={})
        self.assertEqual(("blocked", "provider_quota_exhausted"), (result["state"], result["code"]))

    def test_unknown_error_is_redacted(self):
        result = observed_provider_state(configured=True, latest=self.job("failed", "secret token and article content"), cooling={})
        self.assertNotIn("secret", str(result))
        self.assertEqual("provider_request_failed", result["code"])

    def test_success_is_labelled_as_observation_not_live_guarantee(self):
        self.assertEqual("last_attempt_succeeded", observed_provider_state(configured=True, latest=self.job("succeeded"), cooling={})["state"])

    def test_crashed_job_does_not_spin_forever(self):
        self.assertEqual("not_checked", observed_provider_state(configured=True, latest=self.job("running", age=11), cooling={})["state"])

    def test_active_attempt_and_cooldown(self):
        self.assertEqual("processing", observed_provider_state(configured=True, latest=self.job("running"), cooling={})["state"])
        result = observed_provider_state(configured=True, latest=self.job("succeeded"), cooling={"state":"cooldown","code":"provider_authentication_failed","retry_after_seconds":20})
        self.assertEqual("blocked", result["state"])

    def test_status_scope_and_owner_budget_visibility(self):
        aid=uuid.uuid4()
        with patch("app.main.require_workspace_scope",new=AsyncMock()) as scope, patch("app.main.current_admin",new=AsyncMock(return_value=SimpleNamespace(role="viewer", email="viewer@example.org"))), patch("app.product_status.operations_status",new=AsyncMock(return_value={"budgets":{"secret":"fixture"},"budget_day_start":"fixture","state":"awaiting_analysis"})):
            response=TestClient(app).get(f"/operations/status?assistant_id={aid}")
        self.assertEqual(200,response.status_code)
        self.assertNotIn("budgets",response.json())
        scope.assert_awaited_once_with(None,aid)

    def test_denied_scope_cannot_read_ai_status(self):
        with patch("app.main.require_workspace_scope",new=AsyncMock(side_effect=HTTPException(403,"scope denied"))), patch("app.product_status.operations_status",new=AsyncMock()) as service:
            response=TestClient(app).get(f"/operations/status?assistant_id={uuid.uuid4()}")
        self.assertEqual(403,response.status_code)
        service.assert_not_awaited()

    def test_triage_validation_and_pagination_contract(self):
        aid=uuid.uuid4()
        with patch("app.main.require_workspace_scope",new=AsyncMock()),patch("app.main.list_relevance_assessments",new=AsyncMock(return_value={"articles":[],"total":0})) as service:
            response=TestClient(app).get(f"/publications/relevance-assessments?assistant_id={aid}&limit=25&offset=25&state=pending&query=Gemini")
            self.assertEqual(200,response.status_code)
            service.assert_awaited_once_with(assistant_id=aid,limit=25,offset=25,state="pending",query="Gemini")
            self.assertEqual(422,TestClient(app).get(f"/publications/relevance-assessments?assistant_id={aid}&state=published").status_code)
            self.assertEqual(422,TestClient(app).get(f"/publications/relevance-assessments?assistant_id={aid}&offset=501").status_code)


if __name__ == "__main__":
    unittest.main()
