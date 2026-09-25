import unittest
from datetime import datetime, timezone

from app.bee_cfo.delivery import render_media_outlook_message, render_media_outlook_messages
from app.bee_cfo.media_forecasts import (
    build_media_consensus,
    build_media_history,
    classify_media_statement,
    extract_media_forecasts,
    mark_media_expiry,
    normalize_media_weighting,
    parse_horizon,
)
from app.bee_cfo.researcher_adapter import MarketEvidence


def media(key: str, text: str, *, source: str | None = None) -> MarketEvidence:
    return MarketEvidence(
        title="Gold outlook",
        text=text,
        source_key=key,
        source_name=source or key,
        source_url=f"https://example.com/{key}",
        source_origin="user",
        source_authority="news",
        discovery_path="user_provided",
        published_at=datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
        discovered_at=datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
        extraction_status="complete",
        quality_score=0.9,
        provenance={"author": "Analyst One"},
    )


class BeeCFOMediaForecastTest(unittest.TestCase):
    def test_malformed_weight_configuration_uses_safe_bounded_defaults(self):
        normalized = normalize_media_weighting({
            "component_weights": {"source": object(), "analyst": float("nan"), "article_quality": True},
            "source_priors": {"bad": object(), "nan": float("inf"), "good": 1.5},
            "minimum_independent_sources": [],
            "minimum_sample": "2.5",
            "expiry_hours": {"48h": {"hours": 24}},
        })
        weights = normalized["component_weights"]
        self.assertAlmostEqual(1.0, sum(weights.values()))
        self.assertEqual(1, normalized["minimum_independent_sources"])
        self.assertEqual(20, normalized["minimum_sample"])
        self.assertEqual(96, normalized["expiry_hours"]["48h"])
        self.assertEqual({"good": 1.5}, normalized["source_priors"])

        rows = extract_media_forecasts([
            media("MEDIA-A", "Analysts forecast gold prices will rise over the next 48 hours."),
        ])
        rows[0]["confidence"] = object()
        rows[0]["independence_weight"] = float("nan")
        consensus = build_media_consensus(rows)
        self.assertEqual("up", consensus["buckets"][0]["direction"])
        self.assertTrue(0 <= consensus["buckets"][0]["confidence"] <= 1)

    def test_direction_requires_asset_context_and_does_not_read_lower_yields_as_bearish_gold(self):
        self.assertEqual(
            "up",
            classify_media_statement(
                "Gold extends its bullish move and remains supported by lower US Treasury yields."
            ),
        )
        rows = extract_media_forecasts([
            media("CORN", "Analysts forecast corn prices will fall over the next 48 hours."),
        ])
        self.assertEqual("unknown", rows[0]["stance"])
        self.assertEqual("no_explicit_opinion", rows[0]["evidence_type"])

    def test_renderer_revalidates_a_stored_legacy_direction(self):
        report = {
            "current_state": {
                "media_perspectives": [{
                    "source_name": "Legacy feed",
                    "source_url": "https://example.com/legacy",
                    "view": "Markets expect corn prices to fall over the next 48 hours.",
                    "stance": "down",
                    "horizon_key": "48h",
                    "horizon_label": "تا ۴۸ ساعت",
                    "evidence_type": "explicit_opinion",
                    "status": "active",
                }],
            },
        }
        messages = render_media_outlook_messages(report=report, watch_name="طلای ۱۸ عیار")
        self.assertEqual(["🧭 <b>جهت رسانه‌ها</b>", "در این نوبت مقاله قابل‌استناد با نظر رسانه‌ای استخراج نشد."], messages)

    def test_horizon_parser_is_discrete_and_does_not_force_unknown(self):
        self.assertEqual("24h", parse_horizon("gold may rise over the next 24 hours")["horizon_key"])
        self.assertEqual("48h", parse_horizon("gold may fall within two days")["horizon_key"])
        self.assertEqual("3_7d", parse_horizon("gold outlook for next week")["horizon_key"])
        self.assertEqual("30d_plus", parse_horizon("gold is bullish in the long term")["horizon_key"])
        self.assertEqual("unspecified", parse_horizon("gold may rise")["horizon_key"])

    def test_same_media_conflict_and_different_horizon_are_preserved(self):
        rows = extract_media_forecasts([
            media("MEDIA-A", "Analysts forecast gold prices will rise over the next 48 hours."),
            media("MEDIA-A", "Analysts forecast gold prices will fall over the next 48 hours."),
            media("MEDIA-A", "Analysts expect gold prices to rise in the long term."),
        ])
        explicit = [row for row in rows if row["evidence_type"] == "explicit_opinion"]
        self.assertEqual(3, len(explicit))
        self.assertEqual({"up", "down"}, {row["stance"] for row in explicit if row["horizon_key"] == "48h"})
        self.assertTrue(all(row["conflict_status"] == "internal_conflict" for row in explicit if row["horizon_key"] == "48h"))
        self.assertEqual("30d_plus", next(row["horizon_key"] for row in explicit if row["horizon_key"] == "30d_plus"))
        self.assertTrue(all(row["conflict_status"] == "clear" for row in explicit if row["horizon_key"] == "30d_plus"))

    def test_syndicated_narrative_is_retained_but_downweighted(self):
        rows = extract_media_forecasts([
            media("MEDIA-A", "Analysts forecast gold prices will rise over the next 48 hours."),
            media("MEDIA-B", "Analysts forecast gold prices will rise over the next 48 hours."),
        ])
        explicit = [row for row in rows if row["evidence_type"] == "explicit_opinion"]
        self.assertEqual(2, len(explicit))
        self.assertEqual({1.0, 0.25}, {row["independence_weight"] for row in explicit})
        self.assertIn("syndicated", {row["status"] for row in explicit})

    def test_consensus_is_separated_by_horizon_and_conflict_is_mixed(self):
        rows = extract_media_forecasts([
            media("MEDIA-A", "Analysts forecast gold prices will rise over the next 48 hours."),
            media("MEDIA-B", "Analysts forecast gold prices will rise over the next 48 hours."),
            media("MEDIA-A", "Analysts forecast gold prices will fall over the next 48 hours."),
            media("MEDIA-C", "Analysts expect gold prices to rise next week."),
        ])
        result = build_media_consensus(rows, now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc))
        buckets = {row["horizon_key"]: row for row in result["buckets"]}
        self.assertEqual("mixed", buckets["48h"]["direction"])
        self.assertEqual("up", buckets["3_7d"]["direction"])
        self.assertEqual({"48h", "3_7d"}, set(buckets))

    def test_history_exposes_transition(self):
        current = extract_media_forecasts([media("MEDIA-A", "Analysts forecast gold prices will fall over the next 48 hours.")])
        previous = extract_media_forecasts([media("MEDIA-A", "Analysts forecast gold prices will rise over the next 48 hours.")])
        history = build_media_history(current, [{"media_perspectives": previous}])
        self.assertEqual("up → down", history[0]["transition"])

    def test_expiry_is_horizon_specific_and_future_dated_rows_are_excluded(self):
        rows = extract_media_forecasts([
            media("MEDIA-A", "Analysts forecast gold prices will rise over the next 48 hours."),
        ])
        mark_media_expiry(rows, now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc))
        self.assertEqual("expired", rows[0]["status"])
        self.assertEqual("expired", rows[0]["temporal_status"])

        future = extract_media_forecasts([
            media("MEDIA-B", "Analysts forecast gold prices will rise over the next 48 hours."),
        ])
        future[0]["published_at"] = "2026-08-24T10:00:00+00:00"
        history = build_media_history(
            future,
            now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual([], history)

    def test_renderer_shows_horizons_and_internal_conflict_without_overflow(self):
        rows = extract_media_forecasts([
            media("MEDIA-A", "Analysts forecast gold prices will rise over the next 48 hours."),
            media("MEDIA-A", "Analysts forecast gold prices will fall over the next 48 hours."),
            media("MEDIA-C", "Analysts expect gold prices to rise next week."),
        ])
        report = {"current_state": {"media_perspectives": rows, "media_consensus": build_media_consensus(rows)}}
        message = render_media_outlook_message(report=report, watch_name="طلای ۱۸ عیار")
        self.assertLessEqual(len(message), 3900)
        self.assertIn("⏱ افق زمانی: تا ۴۸ ساعت", message)
        self.assertIn("دارای اختلاف", message)
        self.assertIn("○", message)
        self.assertIn("تا ۴۸ ساعت", message)
        self.assertIn("۳ تا ۷ روز", message)
        self.assertIn('href="https://example.com/MEDIA-A"', message)
        self.assertNotIn("Analysts forecast gold prices will rise", message)
        horizon_messages = render_media_outlook_messages(report=report, watch_name="طلای ۱۸ عیار")
        self.assertEqual(3, len(horizon_messages))
        self.assertEqual("🧭 <b>جهت رسانه‌ها</b>", horizon_messages[0])
        self.assertLessEqual(max(len(item) for item in horizon_messages), 3900)


if __name__ == "__main__":
    unittest.main()
