import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.bee_cfo.canary import build_canary_preview  # noqa: E402
from app.bee_cfo.claim_lifecycle import build_claim_lifecycle, extract_conditions  # noqa: E402
from app.bee_cfo.delivery import render_followup_messages  # noqa: E402
from app.bee_cfo.evidence import build_evidence_pack, verify_evidence_pack  # noqa: E402
from app.bee_cfo.forecasting import evaluate_champion_challenger  # noqa: E402
from app.bee_cfo.governance import source_decision_allows_delivery  # noqa: E402
from app.bee_cfo.quote_control import evaluate_source_contract, reconcile_quotes, source_contract_fingerprint  # noqa: E402
from app.bee_cfo.researcher_adapter import MarketEvidence  # noqa: E402
from app.main import app  # noqa: E402


class BeeCFOQualityGatesTest(unittest.TestCase):
    def setUp(self):
        self.as_of = datetime(2026, 8, 25, tzinfo=timezone.utc)
        self.evidence = MarketEvidence(
            title="Gold outlook",
            text="Gold is likely to rise in the next week if real yields decline.",
            source_key="MEDIA-1",
            source_name="Trusted Media",
            source_url="https://Example.com/gold#today",
            source_origin="user",
            source_authority="news",
            discovery_path="user_provided",
            published_at=self.as_of,
            discovered_at=self.as_of,
            extraction_status="complete",
            quality_score=0.9,
            provenance={"content_hash": "known-content"},
        )

    def test_evidence_pack_is_stable_and_requires_captured_https_evidence(self):
        pack = build_evidence_pack(
            [self.evidence], report_as_of=self.as_of, model_revision="model-1",
            renderer_revision="render-1", output_contract_revision="contract-1", source_policy_revision="policy-1",
        )
        self.assertTrue(verify_evidence_pack(pack)["ready"])
        self.assertEqual("https://example.com/gold", pack["entries"][0]["source_url"])
        self.assertEqual(pack["manifest_hash"], build_evidence_pack(
            [self.evidence], report_as_of=self.as_of, model_revision="model-1",
            renderer_revision="render-1", output_contract_revision="contract-1", source_policy_revision="policy-1",
        )["manifest_hash"])

    def test_claim_lifecycle_preserves_explicit_conditions_and_replacements(self):
        self.assertEqual(["if real yields decline"], extract_conditions("Gold rises if real yields decline."))
        old = build_claim_lifecycle([{
            "forecast_id": "old", "source_key": "MEDIA", "source_name": "Media", "source_url": "https://example.com/a",
            "stance": "up", "horizon_key": "3_7d", "horizon_label": "week", "evidence_type": "explicit_opinion",
            "snippet": "Gold rises if yields fall.", "status": "active",
        }])
        newer = build_claim_lifecycle([{
            "forecast_id": "new", "source_key": "MEDIA", "source_name": "Media", "source_url": "https://example.com/b",
            "stance": "down", "horizon_key": "3_7d", "horizon_label": "week", "evidence_type": "explicit_opinion",
            "snippet": "Gold falls if yields rise.", "status": "active",
        }], previous=old["claims"])
        self.assertEqual(1, newer["replaced_count"])
        self.assertTrue(any(row["lifecycle_status"] == "replaces" for row in newer["claims"]))

    def test_source_contract_drift_and_quote_mismatch_fail_closed(self):
        indicator = SimpleNamespace(indicator_key="GOLD_18K", quote_unit="تومان", parser_key="gold")
        source = SimpleNamespace(
            source_key="SRC-GOLD", fetch_url="https://example.com/gold", homepage_url="https://example.com",
            adapter="html", parser_json={"source_unit": "تومان"},
        )
        fingerprint = source_contract_fingerprint(indicator=indicator, source=source)
        decision = {"contract_fingerprint": fingerprint, "expires_at": "2026-09-01T00:00:00+00:00"}
        self.assertTrue(evaluate_source_contract(decision, current_fingerprint=fingerprint, now=self.as_of)["delivery_permitted"])
        self.assertFalse(evaluate_source_contract(decision, current_fingerprint="drift", now=self.as_of)["delivery_permitted"])
        self.assertFalse(source_decision_allows_delivery(
            "approved", {"status": "approved", "uat_status": "passed", "indicator_key": "GOLD_18K", "source_key": "SRC-GOLD"},
            indicator_key="GOLD_18K", source_key="SRC-GOLD", current_contract_fingerprint=fingerprint,
        ))
        primary = SimpleNamespace(value=100.0)
        verifier = SimpleNamespace(value=125.0)
        self.assertFalse(reconcile_quotes(primary, verifier, max_relative_spread=0.10)["delivery_permitted"])
        self.assertTrue(reconcile_quotes(primary, None)["delivery_permitted"])

    def test_challenger_never_self_promotes_to_public_target(self):
        eligible = evaluate_champion_challenger({"status": "available", "sample_size": 20, "baseline_mae": 10, "ensemble_mae": 8})
        held = evaluate_champion_challenger({"status": "available", "sample_size": 20, "baseline_mae": 8, "ensemble_mae": 10})
        self.assertTrue(eligible["eligible_for_owner_review"])
        self.assertFalse(eligible["public_target_permitted"])
        self.assertFalse(held["eligible_for_owner_review"])

    def test_unapproved_model_candidate_cannot_render_a_public_target(self):
        messages = render_followup_messages(
            report={
                "current_state": {
                    "price_forecast": {
                        "status": "available",
                        "publication": {"public_target_permitted": False},
                        "forecasts": [{
                            "horizon_days": 7, "point_value": 100, "lower_value": 90, "upper_value": 110,
                            "probability_up": 0.5, "probability_down": 0.3, "probability_flat": 0.2,
                        }],
                    }
                }
            },
            watch_name="Gold",
        )
        self.assertFalse(any("برآورد مدل" in message for message in messages))

    def test_canary_is_private_and_requires_an_intact_evidence_pack(self):
        pack = build_evidence_pack(
            [self.evidence], report_as_of=self.as_of, model_revision="model-1",
            renderer_revision="render-1", output_contract_revision="contract-1", source_policy_revision="policy-1",
        )
        report = {
            "id": "report-1",
            "current_state": {
                "evidence_pack": pack,
                "media_perspectives": [{
                    "forecast_id": "f-1", "source_key": "MEDIA-1", "source_name": "Trusted Media",
                    "source_url": "https://example.com/gold", "stance": "up", "horizon_key": "3_7d",
                    "horizon_label": "3 to 7 days", "horizon_explicit": True,
                    "evidence_type": "explicit_opinion", "confidence": 0.9, "status": "active",
                    "snippet": "Gold is likely to rise in the next week.", "published_at": self.as_of.isoformat(),
                }],
            },
            "scenarios": [],
        }
        preview = build_canary_preview(report=report, watch_name="Gold")
        self.assertEqual("passed", preview["status"])
        self.assertFalse(preview["outbound_message_sent"])

    def test_quality_gate_routes_are_registered(self):
        paths = set(app.openapi()["paths"])
        for path in (
            "/bee-cfo/source-ledger/revalidate",
            "/bee-cfo/reports/{report_id}/evidence-pack",
            "/bee-cfo/reports/{report_id}/claim-lifecycle",
            "/bee-cfo/reports/{report_id}/canary",
            "/bee-cfo/reports/{report_id}/canary/approve",
        ):
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main()
