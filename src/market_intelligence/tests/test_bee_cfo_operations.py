import unittest
from datetime import datetime, timezone

from app.bee_cfo.operations import (
    build_capacity_budget,
    build_coverage_gaps,
    build_confidence_budget,
    build_open_checks,
    build_price_source_health,
    build_report_diff,
    build_replay_payload,
    assess_evidence_quality,
    classify_alert_maturity,
    evaluate_telegram_uat,
)
from app.bee_cfo.delivery import render_report_diff_message


class BeeCFOOperationsTest(unittest.TestCase):
    def test_confidence_budget_is_decomposed_and_explains_missing_inputs(self):
        result = build_confidence_budget(
            coverage={"score": 0.35},
            model_agreement={"status": "disagreement"},
            media_pulse={"coverage_volume": 2, "explicit_opinion_count": 1},
            forecast={"status": "limited"},
            source_health={"score": 0.5},
            evidence_count=2,
            source_count=1,
        )
        self.assertIn("coverage", result["missing"])
        self.assertIn("model_agreement", result["missing"])
        self.assertLess(result["overall"], 0.75)

    def test_untrusted_nested_report_values_fail_closed_without_crashing(self):
        quality = assess_evidence_quality({
            "coverage_score": {"score": object(), "status": "complete", "missing": "not-a-list"},
            "analysis_evidence_count": object(),
            "media_perspectives": {"not": "a list"},
            "price_forecast": "not-a-mapping",
            "evidence_pack": [],
        })
        self.assertEqual("held", quality["status"])
        self.assertFalse(quality["checks"]["coverage_sufficient"])
        self.assertEqual([], quality["coverage"]["missing"])
        budget = build_confidence_budget(
            coverage={"score": object()},
            model_agreement={},
            media_pulse={"explicit_opinion_count": object(), "coverage_volume": "nan"},
            forecast={},
        )
        self.assertTrue(0 <= budget["overall"] <= 1)
        self.assertEqual([], build_open_checks(
            current_state={"coverage_score": [], "model_agreement": []},
            report_as_of="2026-08-23T12:00:00+00:00",
            live_uat_required=False,
        ))
        diff = build_report_diff(
            {"evidence_cards": "not-a-list"},
            {"evidence_cards": {"not": "a list"}},
        )
        self.assertEqual("unchanged", diff["status"])

    def test_alert_maturity_requires_independent_corroboration(self):
        candidate = {"kind": "price_change_pct", "threshold": 2}
        self.assertEqual("candidate", classify_alert_maturity(candidate=candidate, independent_sources=1, source_quality=0.8)["status"])
        corroborated = classify_alert_maturity(candidate=candidate, independent_sources=2, source_quality=0.8)
        self.assertEqual("corroborated", corroborated["status"])
        self.assertTrue(corroborated["can_publish"])
        self.assertEqual("suppressed", classify_alert_maturity(candidate=candidate, independent_sources=2, source_quality=0.8, stale=True)["status"])

    def test_open_checks_and_capacity_are_actionable_and_bounded(self):
        checks = build_open_checks(
            current_state={
                "coverage_score": {"missing": ["quote", "benchmark"]},
                "media_conflicts": [{"source_key": "A"}],
                "model_agreement": {"status": "disagreement"},
                "price_forecast_status": "limited",
            },
            report_as_of="2026-08-23T12:00:00+00:00",
        )
        keys = {item["check_key"] for item in checks}
        self.assertIn("coverage:quote", keys)
        self.assertIn("media:internal_conflict", keys)
        self.assertIn("delivery:live_uat", keys)
        capacity = build_capacity_budget(source_count=41, evidence_count=4, media_forecast_count=2, price_source_count=1)
        self.assertEqual("blocked", capacity["status"])
        self.assertIn("sources", capacity["exceeded"])

    def test_coverage_gaps_disclose_diversity_without_claiming_market_effect(self):
        gaps = build_coverage_gaps(
            {"missing": ["benchmark"]},
            evidence=[{"source_key": "A", "source_authority": "news", "title": "خبر فارسی", "text": "روند طلا"}],
        )
        keys = {item["key"] for item in gaps}
        self.assertIn("benchmark", keys)
        self.assertIn("independent_sources", keys)
        self.assertIn("english_coverage", keys)
        self.assertIn("official_coverage", keys)
        self.assertNotIn("news_coverage", keys)

    def test_diff_is_source_aware_and_does_not_rerun_model(self):
        before = {"confidence_budget": {"overall": 0.5}, "evidence_cards": [{"evidence_id": "a"}]}
        after = {"confidence_budget": {"overall": 0.7}, "evidence_cards": [{"evidence_id": "a"}, {"evidence_id": "b"}]}
        result = build_report_diff(before, after)
        self.assertEqual("changed", result["status"])
        self.assertIn("confidence_budget", {item["field"] for item in result["changed_fields"]})
        self.assertEqual(["b"], result["new_evidence_ids"])
        self.assertTrue(result["no_model_rerun"])

    def test_replay_rejects_future_reports(self):
        reports = [
            {"id": "future", "as_of": "2026-08-24T12:00:00+00:00"},
            {"id": "past", "as_of": "2026-08-23T12:00:00+00:00"},
        ]
        result = build_replay_payload(reports, datetime(2026, 8, 23, 18, tzinfo=timezone.utc))
        self.assertEqual("past", result["selected_report"]["id"])
        self.assertTrue(result["no_lookahead"])
        self.assertEqual(1, result["excluded_future_count"])

    def test_price_health_and_telegram_uat(self):
        health = build_price_source_health(attempted_sources=["primary", "backup"], selected_source="backup", errors=["primary failed"])
        self.assertEqual("failover", health["status"])
        self.assertTrue(health["failover_used"])
        uat = evaluate_telegram_uat(
            price_delivery={"status": "sent", "message_ids": [31]},
            report_delivery={"status": "sent", "message_ids": [33], "media_message_ids": [32]},
        )
        self.assertEqual("passed", uat["status"])
        self.assertEqual("price → media outlook", uat["ordering"])

    def test_diff_renderer_is_bounded_and_linked(self):
        message = render_report_diff_message(
            diff={
                "changed_fields": [{"field": "coverage_score"}],
                "new_evidence_ids": ["e1"],
                "new_evidence": [{"source_name": "منبع معتبر", "source_url": "https://example.com/e1"}],
            },
            watch_name="طلای ۱۸ عیار",
        )
        self.assertLessEqual(len(message), 1200)
        self.assertIn("منبع معتبر", message)
        self.assertIn("forecast جدید", message)


if __name__ == "__main__":
    unittest.main()
