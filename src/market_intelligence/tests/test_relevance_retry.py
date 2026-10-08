import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.ai_relevance import RelevanceAssessmentError, classify_articles
from app.openai_client import AIProviderError
from app.pipeline_service import _classify_relevance_batch


class RelevanceRetryTest(unittest.IsolatedAsyncioTestCase):
    async def run_batch(self, *, failures, remaining=10, reservations=None):
        client = AsyncMock()
        settings = SimpleNamespace(analysis_model="fixture-model")
        reserve = AsyncMock(side_effect=reservations or [uuid.uuid4(), uuid.uuid4()])
        finish = AsyncMock()
        classify = AsyncMock(side_effect=failures)
        with patch("app.pipeline_service._reserve_relevance_budget", reserve), \
             patch("app.pipeline_service._finish_job", finish), \
             patch("app.pipeline_service.classify_articles", classify):
            result = await _classify_relevance_batch(
                settings, client, assistant_id=uuid.uuid4(), inputs=[], topics=[], business={},
                mission="", input_chars=123, remaining_requests=remaining,
            )
        return result, reserve, finish, classify

    async def test_invalid_response_is_retried_once_and_both_attempts_are_accounted(self):
        valid = {("article", "topic"): (0.8, "validated metadata")}
        result, reserve, finish, classify = await self.run_batch(failures=[
            RelevanceAssessmentError("relevance_evidence_invalid"), valid,
        ])
        self.assertEqual((valid, "succeeded", 2), result)
        self.assertEqual(2, reserve.await_count)
        self.assertEqual(2, classify.await_count)
        self.assertEqual(["failed", "succeeded"], [call.kwargs["status"] for call in finish.await_args_list])
        self.assertEqual([1, 2], [call.kwargs["result"]["classification_attempt"] for call in finish.await_args_list])

    async def test_repeated_invalid_response_fails_closed_after_two_calls(self):
        result, _, finish, classify = await self.run_batch(failures=[
            RelevanceAssessmentError("relevance_score_invalid"),
            RelevanceAssessmentError("relevance_score_invalid"),
        ])
        self.assertEqual(({}, "provider_failed:relevance_score_invalid", 2), result)
        self.assertEqual(2, classify.await_count)
        self.assertTrue(all(call.kwargs["status"] == "failed" for call in finish.await_args_list))

    async def test_provider_quota_failure_is_not_retried(self):
        result, reserve, _, classify = await self.run_batch(failures=[AIProviderError("provider_quota_exhausted")])
        self.assertEqual(({}, "provider_failed:provider_quota_exhausted", 1), result)
        self.assertEqual(1, reserve.await_count)
        self.assertEqual(1, classify.await_count)

    async def test_run_limit_and_daily_budget_bound_repair(self):
        invalid = RelevanceAssessmentError("relevance_coverage_incomplete")
        result, _, _, classify = await self.run_batch(failures=[invalid], remaining=1)
        self.assertEqual(1, result[2])
        self.assertEqual(1, classify.await_count)
        result, _, _, classify = await self.run_batch(failures=[invalid], reservations=[uuid.uuid4(), None])
        self.assertEqual(({}, "budget_deferred", 1), result)
        self.assertEqual(1, classify.await_count)

    async def test_no_budget_means_no_provider_call(self):
        result, reserve, finish, classify = await self.run_batch(failures=[], remaining=0)
        self.assertEqual(({}, "budget_deferred", 0), result)
        reserve.assert_not_awaited()
        finish.assert_not_awaited()
        classify.assert_not_awaited()

    async def test_schema_binds_ids_and_complete_coverage_and_rejects_malformed_results(self):
        client = AsyncMock()
        args = {"articles": [{"id": "a1", "title": "AI model", "text": "Actual facts"}],
                "topics": [{"topic_key": "AI"}], "business": {}, "mission": ""}
        for response in ([], {"scores": {}}, {"scores": ["not an object"]}):
            client.draft_json.return_value = response
            with self.assertRaises(RelevanceAssessmentError):
                await classify_articles(client, **args)
        schema = client.draft_json.call_args.kwargs["schema"]["properties"]["scores"]
        self.assertEqual(1, schema["minItems"])
        self.assertEqual(1, schema["maxItems"])
        self.assertEqual(["a1"], schema["items"]["properties"]["article_id"]["enum"])
        self.assertEqual(["AI"], schema["items"]["properties"]["topic_key"]["enum"])
