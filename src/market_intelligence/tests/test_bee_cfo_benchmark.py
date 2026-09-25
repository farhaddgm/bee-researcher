import unittest
from datetime import datetime, timezone

from app.bee_cfo.benchmarking import (
    build_evidence_cards,
    build_media_pulse,
    compute_coverage_score,
    compute_novelty_metrics,
    evaluate_alert_rule,
    evaluate_media_outcome,
    expand_indicator_terms,
    extract_event_ledger,
    model_agreement,
    relative_benchmark_contract,
    source_scorecard,
)
from app.bee_cfo.delivery import render_media_outlook_message, render_report_message
from app.bee_cfo.researcher_adapter import MarketEvidence


def evidence(key: str, title: str, text: str, authority: str = "news") -> MarketEvidence:
    return MarketEvidence(
        title=title,
        text=text,
        source_key=key,
        source_name=key,
        source_url=f"https://example.com/{key}",
        source_origin="user",
        source_authority=authority,
        discovery_path="user_provided",
        published_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        discovered_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        extraction_status="complete",
        quality_score=0.9,
        provenance={},
    )


class BeeCFOBenchmarkTest(unittest.TestCase):
    def test_aliases_are_bilingual_and_deterministic(self):
        terms = expand_indicator_terms("GOLD_18K")
        self.assertIn("طلای ۱۸ عیار", terms)
        self.assertIn("XAU", terms)

    def test_novelty_keeps_duplicates_visible_but_not_as_new_events(self):
        first = evidence("A", "CPI event", "تورم CPI در آمریکا منتشر شد و قیمت طلا تغییر کرد.")
        second = evidence("B", "CPI event", "تورم CPI در آمریکا منتشر شد و قیمت طلا تغییر کرد.")
        clusters = [[first, second]]
        metrics = compute_novelty_metrics([first, second], clusters)
        self.assertEqual(1, metrics["unique_event_count"])
        self.assertEqual(0.5, metrics["duplicate_ratio"])
        cards = build_evidence_cards([first, second], clusters)
        self.assertEqual(2, cards[0]["source_independence"])
        self.assertTrue(cards[0]["snippet"])

    def test_coverage_and_model_agreement_are_explicit(self):
        coverage = compute_coverage_score(quote=True, source_health=1, freshness=1, media_opinion=True, benchmark=False, forecast=True)
        self.assertEqual("partial", coverage["status"])
        agreement = model_agreement({"status": "available", "forecasts": [{"probability_up": 0.7, "probability_down": 0.2, "probability_flat": 0.1}, {"probability_up": 0.6, "probability_down": 0.3, "probability_flat": 0.1}]})
        self.assertEqual("agreement", agreement["status"])

    def test_event_ledger_and_benchmark_contract(self):
        row = extract_event_ledger([evidence("A", "Fed rate decision", "The Federal Reserve rate decision affects gold.")], watch_key="GOLD", as_of=datetime.now(timezone.utc))
        self.assertEqual("central_bank", row[0]["event_type"])
        self.assertEqual("contract_ready", relative_benchmark_contract("GOLD_18K")["status"])

    def test_active_rule_requires_threshold_or_state_change(self):
        self.assertIsNone(evaluate_alert_rule({"status": "draft", "kind": "stale_quote"}, current={"coverage_score": {"missing": ["quote"]}}))
        alert = evaluate_alert_rule({"status": "active", "rule_key": "stale", "kind": "stale_quote"}, current={"coverage_score": {"missing": ["quote"]}})
        self.assertEqual("stale_quote", alert["kind"])

    def test_media_outcome_and_scorecard_sample_gate(self):
        self.assertEqual("hit", evaluate_media_outcome(expected_stance="up", actual_direction="up")["outcome"])
        self.assertEqual("insufficient_sample", source_scorecard([{"direction_hit": True, "brier_score": 0.1}])["status"])

    def test_benchmark_helpers_fail_safe_on_malformed_persisted_values(self):
        agreement = model_agreement(
            {
                "status": "available",
                "forecasts": [
                    {"probability_up": "NaN", "probability_down": float("inf")},
                    "bad row",
                    {"probability_flat": "0.8"},
                ],
            }
        )
        self.assertEqual("agreement", agreement["status"])
        self.assertIsNone(
            evaluate_media_outcome(
                expected_stance="up", actual_direction="down", probability=float("nan")
            )["brier_score"]
        )
        scorecard = source_scorecard(
            [{"direction_hit": True, "brier_score": float("inf")}] * 20
        )
        self.assertIsNone(scorecard["brier_score"])
        self.assertIsNone(
            evaluate_alert_rule(
                {"status": "active", "kind": "stale_quote"},
                current={"coverage_score": {"missing": "quote"}},
            )
        )

    def test_renderers_expose_evidence_and_coverage_without_overflow(self):
        report = {
            "as_of": "2026-08-23T12:00:00+00:00", "confidence": 0.7,
            "current_state": {
                "summary": "خلاصه", "facts": ["قیمت معتبر ثبت شد"], "raw_evidence_count": 2,
                "valid_evidence_count": 2, "source_count": 2, "coverage_score": {"score": 0.8, "status": "complete"},
                "model_agreement": {"status": "agreement", "label": "هم‌جهت"},
                "media_perspectives": [{"source_key": "A", "source_name": "رسانه", "source_url": "https://example.com/a", "view": "انتظار افزایش قیمت طلا وجود دارد.", "snippet": "انتظار افزایش قیمت طلا وجود دارد.", "stance": "up", "horizon": "۴۸ ساعت", "evidence_type": "explicit_opinion"}],
            },
            "scenarios": [], "changes": [], "uncertainties": [], "citations": [],
        }
        self.assertLessEqual(len(render_report_message(report=report, watch_name="طلای ۱۸ عیار")), 1200)
        self.assertIn('href="https://example.com/a"', render_media_outlook_message(report=report, watch_name="طلای ۱۸ عیار"))
        self.assertNotIn("«انتظار افزایش", render_media_outlook_message(report=report, watch_name="طلای ۱۸ عیار"))


if __name__ == "__main__":
    unittest.main()
