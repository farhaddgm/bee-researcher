import os
import unittest
from datetime import datetime, timedelta, timezone


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.bee_cfo.delivery import render_why_changed_message  # noqa: E402
from app.bee_cfo.governance import (  # noqa: E402
    MARKET_PACKS,
    assess_pilot_run,
    build_verified_pilot_checks,
    evaluate_attention_budget,
    normalize_attention_policy,
    normalize_privacy_boundary,
    pilot_observation_eligibility,
    source_decision_allows_delivery,
    summarize_pilot_runs,
    validate_source_decision,
)
from app.main import app  # noqa: E402


class BeeCFOGovernanceTest(unittest.TestCase):
    def test_pilot_requires_all_customer_facing_controls(self):
        checks = {
            "report_available": True,
            "price_valid": True,
            "citations_valid": True,
            "horizons_valid": True,
            "conflict_preserved": True,
            "no_call_valid": True,
            "message_length_valid": True,
            "output_valid": True,
            "no_personal_advice": True,
            "no_duplicate_delivery": True,
        }
        self.assertTrue(assess_pilot_run(checks)["valid"])
        failed = assess_pilot_run({**checks, "price_valid": False})
        self.assertFalse(failed["valid"])
        self.assertTrue(failed["critical"])

    def test_pilot_summary_requires_a_real_sample_and_zero_critical_failures(self):
        now = datetime(2026, 8, 25, tzinfo=timezone.utc)
        runs = [{"occurred_at": now - timedelta(hours=i), "valid": True, "critical": False} for i in range(30)]
        result = summarize_pilot_runs(runs, now=now)
        self.assertTrue(result["eligible_for_completion"])
        self.assertFalse(summarize_pilot_runs(runs[:-1], now=now)["eligible_for_completion"])

    def test_pilot_observations_cannot_be_inflated_by_immediate_retries(self):
        now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
        blocked = pilot_observation_eligibility(latest_observed_at=now - timedelta(hours=3, minutes=59), now=now)
        self.assertFalse(blocked["eligible"])
        self.assertEqual("minimum_observation_interval", blocked["reason"])
        self.assertEqual("2026-08-25T12:01:00+00:00", blocked["next_eligible_at"])
        allowed = pilot_observation_eligibility(latest_observed_at=now - timedelta(hours=4), now=now)
        self.assertTrue(allowed["eligible"])

    def test_verified_pilot_checks_use_typed_receipts_not_operator_field_names(self):
        checks = build_verified_pilot_checks(
            report={
                "media_forecasts": [{"horizon_key": "48h"}],
                "current_state": {"media_consensus": {"conflict_count": 0, "buckets": []}},
            },
            price_snapshot={
                "source_url": "https://example.com/quote",
                "price_source_health": {"selected_source": "SRC-GOLD"},
            },
            quality_gate={
                "checks": {
                    "citable_evidence_present": True,
                    "media_links_valid": True,
                    "no_call_reasons_disclosed": True,
                }
            },
            canary_preview={
                "status": "passed",
                "outbound_message_sent": False,
                "checks": {
                    "messages_present": True,
                    "message_limits": True,
                    "no_personal_investment_advice": True,
                },
            },
            shadow_run={"outbound_message_sent": False, "run": {"status": "passed"}},
        )
        self.assertTrue(assess_pilot_run({"report_available": True, **checks})["valid"])

    def test_source_decision_never_activates_a_reference(self):
        source = validate_source_decision({
            "indicator_key": "USD_FREE", "source_key": "SRC-TGJU-USD", "owner": "owner",
            "permission_basis": "owner-approved public reference", "source_url": "https://example.com/quote",
            "quote_unit": "تومان", "timezone": "Asia/Tehran", "fallback": "none",
            "status": "approved", "uat_status": "passed",
        })
        self.assertFalse(source["activation_permitted"])
        with self.assertRaises(ValueError):
            validate_source_decision({**source, "source_url": "http://example.com"})

    def test_only_approved_passed_unexpired_source_decisions_allow_delivery(self):
        decision = validate_source_decision({
            "indicator_key": "GOLD_18K", "source_key": "SRC-GOLD", "owner": "owner",
            "permission_basis": "owner-approved public reference", "source_url": "https://example.com/quote",
            "quote_unit": "تومان", "timezone": "Asia/Tehran", "fallback": "none",
            "status": "approved", "uat_status": "passed", "expires_at": "2026-09-01T00:00:00+00:00",
        })
        now = datetime(2026, 8, 25, tzinfo=timezone.utc)
        self.assertTrue(source_decision_allows_delivery("approved", decision, indicator_key="GOLD_18K", source_key="SRC-GOLD", now=now))
        self.assertFalse(source_decision_allows_delivery("approved", {**decision, "uat_status": "pending"}, indicator_key="GOLD_18K", source_key="SRC-GOLD", now=now))
        self.assertFalse(source_decision_allows_delivery("approved", {**decision, "expires_at": "2026-08-24T00:00:00+00:00"}, indicator_key="GOLD_18K", source_key="SRC-GOLD", now=now))

    def test_attention_budget_suppresses_duplicates_and_quiet_hours(self):
        policy = normalize_attention_policy({"quiet_hours": {"start": "23:00", "end": "07:00", "timezone": "Asia/Tehran"}})
        candidate = {"dedup_key": "gold:quote", "severity": "important"}
        duplicate = evaluate_attention_budget(candidate, policy=policy, recent_count=0, duplicate_seen=True, now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc))
        self.assertEqual("duplicate_within_window", duplicate["reason"])
        quiet = evaluate_attention_budget(candidate, policy=policy, recent_count=0, duplicate_seen=False, now=datetime(2026, 8, 25, 1, tzinfo=timezone.utc))
        self.assertEqual("quiet_hours", quiet["reason"])
        self.assertFalse(quiet["delivery_performed"])

    def test_market_pack_order_is_explicit_and_non_activating(self):
        self.assertEqual(["USD_FREE", "BTC_USDT"], [item["pack_key"] for item in MARKET_PACKS])
        self.assertEqual("USD_FREE", MARKET_PACKS[1]["requires_predecessor"])

    def test_privacy_boundary_rejects_personal_data_in_phase_one(self):
        self.assertFalse(normalize_privacy_boundary({})["phase_one_personal_data_enabled"])
        with self.assertRaises(ValueError):
            normalize_privacy_boundary({"phase_one_personal_data_enabled": True})
        with self.assertRaises(ValueError):
            normalize_privacy_boundary({"phase_two_processing_enabled": True})

    def test_why_changed_reply_is_evidence_only_and_bounded(self):
        message = render_why_changed_message(
            diff={"status": "changed", "changed_fields": [{"field": "coverage_score"}], "new_evidence_ids": [], "no_model_rerun": True},
            report={"citations": [{"source_name": "منبع", "source_url": "https://example.com/evidence"}]},
            watch_name="طلای ۱۸ عیار",
        )
        self.assertIn("منابع همان گزارش", message)
        self.assertIn("forecast جدید یا توصیه شخصی تولید نمی‌کند", message)
        self.assertLessEqual(len(message), 1200)

    def test_post_phase_one_control_routes_are_registered(self):
        paths = set(app.openapi()["paths"])
        for path in (
            "/bee-cfo/pilot",
            "/bee-cfo/pilot/runs",
            "/bee-cfo/pilot/verified-runs",
            "/bee-cfo/source-ledger",
            "/bee-cfo/market-packs",
            "/bee-cfo/attention-policy",
            "/bee-cfo/privacy-boundary",
            "/bee-cfo/reports/{report_id}/why-changed",
        ):
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main()
