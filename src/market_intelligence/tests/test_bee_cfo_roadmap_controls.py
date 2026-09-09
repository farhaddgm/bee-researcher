import os
import unittest
from datetime import datetime, timezone


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.bee_cfo.evidence import build_evidence_pack  # noqa: E402
from app.bee_cfo.operations import assess_evidence_quality, build_capacity_budget, build_replay_payload  # noqa: E402
from app.bee_cfo.quote_control import (  # noqa: E402
    build_provider_fixture,
    build_provider_signature,
    evaluate_provider_response,
    validate_provider_fixture,
)
from app.main import app  # noqa: E402


class BeeCFORoadmapControlsTest(unittest.TestCase):
    def setUp(self):
        self.as_of = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def _pack(self):
        return build_evidence_pack(
            [{
                "title": "Gold outlook", "text": "A citable gold outlook.", "source_key": "MEDIA-1",
                "source_name": "Trusted media", "source_url": "https://example.com/gold",
                "source_authority": "news", "published_at": self.as_of, "discovered_at": self.as_of,
                "extraction_status": "complete", "quality_score": 0.9, "provenance": {"content_hash": "sample"},
            }],
            report_as_of=self.as_of, model_revision="model-1", renderer_revision="render-1",
            output_contract_revision="contract-1", source_policy_revision="policy-1",
        )

    def test_provider_fixture_quarantines_only_schema_drift(self):
        signature = build_provider_signature(
            adapter="json", payload={"data": [{"price": 100, "label": "gold"}]},
            parser={"path": ["data", 0, "price"], "source_unit": "ریال"}, parser_key="gold_18k",
        )
        fixture = build_provider_fixture(signature)
        self.assertEqual(fixture, validate_provider_fixture(fixture))
        self.assertTrue(evaluate_provider_response(fixture, signature, enforced=True)["delivery_permitted"])
        drifted = build_provider_signature(
            adapter="json", payload={"result": {"price": 100}},
            parser={"path": ["data", 0, "price"], "source_unit": "ریال"}, parser_key="gold_18k",
        )
        result = evaluate_provider_response(fixture, drifted, enforced=True)
        self.assertEqual("provider_drift", result["status"])
        self.assertTrue(result["quarantined"])
        self.assertFalse(result["delivery_permitted"])

    def test_evidence_gate_holds_missing_evidence_and_discloses_no_call(self):
        held = assess_evidence_quality({"coverage_score": {"score": 0.2, "status": "insufficient", "missing": ["quote"]}})
        self.assertFalse(held["publication_permitted"])
        state = {
            "evidence_pack": self._pack(), "analysis_evidence_count": 1,
            "coverage_score": {"score": 0.55, "status": "partial", "missing": ["benchmark"]},
            "price_forecast": {"status": "no_call", "reason": "history is insufficient"},
            "media_perspectives": [{"source_url": "https://example.com/gold"}],
        }
        gate = assess_evidence_quality(state)
        self.assertTrue(gate["publication_permitted"])
        self.assertTrue(any(item["component"] == "benchmark" for item in gate["no_call_reasons"]))

    def test_replay_manifest_is_point_in_time_and_secret_free(self):
        report = {
            "id": "past", "as_of": "2026-08-25T10:00:00+00:00", "model": "fallback",
            "output_contract_revision": "contract-1", "current_state": {"evidence_pack": self._pack()},
        }
        future = {"id": "future", "as_of": "2026-08-26T10:00:00+00:00", "current_state": {}}
        replay = build_replay_payload([future, report], self.as_of.replace(hour=12))
        self.assertEqual("past", replay["selected_report"]["id"])
        self.assertTrue(replay["no_lookahead"])
        self.assertFalse(replay["replay_manifest"]["raw_bodies_included"])
        self.assertFalse(replay["replay_manifest"]["secret_values_included"])
        self.assertTrue(replay["replay_manifest"]["replay_hash"])

    def test_capacity_budget_stops_model_cascade_before_a_report(self):
        budget = build_capacity_budget(source_count=1, evidence_count=201, media_forecast_count=0, price_source_count=0)
        self.assertEqual("blocked", budget["status"])
        self.assertTrue(budget["degraded_mode"])

    def test_roadmap_control_route_is_registered(self):
        paths = set(app.openapi()["paths"])
        self.assertIn("/bee-cfo/reports/{report_id}/quality-gate", paths)


if __name__ == "__main__":
    unittest.main()
