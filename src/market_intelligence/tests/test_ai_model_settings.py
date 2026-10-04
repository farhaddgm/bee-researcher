import json
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.admin import AssistantRuntimeSettingsUpdate, get_assistant_runtime_settings, update_assistant_runtime_settings  # noqa: E402
from app.ai_models import SUPPORTED_ANALYSIS_MODELS  # noqa: E402
from app.config import Settings  # noqa: E402
from app.openai_client import OpenAIClient  # noqa: E402
from app.pipeline_service import settings_for_assistant  # noqa: E402


def settings(**overrides):
    return Settings(postgres_db="assistant_test", postgres_user="assistant_test", postgres_password="test-password", redis_password="test-password", _env_file=None, **overrides)


class AIModelSettingsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.id = uuid.uuid4()
        self.workspace = SimpleNamespace(id=self.id, config={"runtime": {"analysis_model": "gpt-5.6-sol", "schedule_slots": [{"weekday": 1, "time": "14:00"}]}})
        self.session = AsyncMock()
        self.session.get.return_value = self.workspace
        self.context = AsyncMock()
        self.context.__aenter__.return_value = self.session
        self.user = SimpleNamespace(id=uuid.uuid4(), role="admin", username="admin", email="admin@example.org")

    async def test_catalog_is_returned_without_overwriting_current_model(self):
        with patch("app.admin.SessionLocal", return_value=self.context), patch("app.admin._require_assistant_access", new=AsyncMock()):
            result = await get_assistant_runtime_settings(self.id, self.user)
        self.assertEqual("gpt-5.6-sol", result["analysis_model"])
        self.assertEqual(SUPPORTED_ANALYSIS_MODELS, {x["id"] for x in result["analysis_model_options"]})
        self.session.commit.assert_not_awaited()

    async def test_model_save_is_scoped_and_publication_save_does_not_reset_it(self):
        access = AsyncMock()
        with patch("app.admin.SessionLocal", return_value=self.context), patch("app.admin._require_assistant_access", new=access), patch("app.admin._audit", new=AsyncMock()):
            for model in ("gpt-6.1-sol", "gpt-6-luna"):
                result = await update_assistant_runtime_settings(self.id, AssistantRuntimeSettingsUpdate(analysis_model=model), self.user)
                self.assertEqual(model, result["analysis_model"])
                self.assertEqual([{"weekday": 1, "time": "14:00"}], result["schedule_slots"])
            result = await update_assistant_runtime_settings(self.id, AssistantRuntimeSettingsUpdate(max_items_per_run=3), self.user)
            self.assertEqual("gpt-6-luna", result["analysis_model"])
        self.assertTrue(any(call.kwargs.get("write") for call in access.await_args_list))
        self.assertTrue(all(call.args[0] == self.id for call in access.await_args_list))

    async def test_selected_model_reaches_runtime_without_mutating_global_defaults(self):
        base = settings()
        with patch("app.pipeline_service.SessionLocal", return_value=self.context):
            for model in ("gpt-6.1-sol", "gpt-6-luna"):
                self.workspace.config["runtime"]["analysis_model"] = model
                effective = await settings_for_assistant(base, self.id)
                self.assertEqual(model, effective.analysis_model)
                self.assertEqual("gpt-5.6-luna", base.analysis_model)

    async def test_new_models_keep_strict_responses_contract(self):
        result = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}]}
        for model in ("gpt-6.1-sol", "gpt-6-luna"):
            client = OpenAIClient(settings(analysis_model=model))
            with patch.object(client, "_post", new=AsyncMock(return_value=result)) as post:
                draft = await client.draft_json(system_prompt="Return JSON", user_payload={"text": "test"}, schema_name="test", schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False})
            path, payload = post.await_args.args
            self.assertEqual("/responses", path)
            self.assertEqual(model, payload["model"])
            self.assertFalse(payload["store"])
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertFalse({"temperature", "top_p", "logprobs"} & payload.keys())
            self.assertEqual({"ok": True}, draft)
            self.assertIn('"text": "test"', payload["input"][1]["content"])
            json.dumps(payload)  # Must remain JSON serializable.

    def test_cost_estimates_use_new_model_rates_and_keep_legacy_configuration(self):
        for model, expected in (("gpt-6.1-sol", 12.0), ("gpt-6-luna", 0.6), ("gpt-5.6-luna", 1.4)):
            self.assertAlmostEqual(expected, OpenAIClient(settings(analysis_model=model))._estimated_token_cost(1_000_000, 1_000_000))
