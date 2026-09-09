import unittest
from types import SimpleNamespace

from app.insights import _conflict_state, classify_priority, quality_projection


class InsightsProjectionTest(unittest.TestCase):
    def test_priority_separates_urgent_from_digest(self):
        urgent = SimpleNamespace(time_horizon="فوری", risk="",)
        digest = SimpleNamespace(time_horizon="کوتاه‌مدت", risk="اطلاع‌رسانی")
        self.assertEqual("urgent", classify_priority(urgent, 0.4))
        self.assertEqual("digest", classify_priority(digest, 0.9))

    def test_quality_projection_is_bounded_and_explainable(self):
        article = SimpleNamespace(quality_score=0.8, normalized_text="x" * 2500)
        source = SimpleNamespace(health_status="healthy")
        result = quality_projection(article, source, corroboration=2)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 1)
        self.assertEqual(0.8, result["extraction"])
        self.assertIn("source_reliability", result)

    def test_conflict_projection_flags_divergent_titles(self):
        result = _conflict_state(["بانک مرکزی نرخ بهره را کاهش داد", "اختلال گسترده در شبکه پرداخت کشور"])
        self.assertEqual("review", result["state"])
        self.assertEqual(2, result["source_count"])


if __name__ == "__main__":
    unittest.main()
