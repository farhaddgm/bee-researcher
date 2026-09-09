import os
import unittest


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.bee_cfo.shadow import build_shadow_run  # noqa: E402
from app.main import app  # noqa: E402


class BeeCFOShadowRunTest(unittest.TestCase):
    def _report(self, *, report_id: str, coverage: float) -> dict[str, object]:
        return {
            "id": report_id,
            "as_of": "2026-08-25T00:00:00+00:00",
            "status": "ready",
            "current_state": {"coverage_score": coverage},
            "scenarios": [{"title": "base"}],
            "changes": {"coverage": coverage},
            "uncertainties": [],
            "citations": [],
            "confidence": coverage,
            "model": {"revision": "model-1"},
            "output_contract_revision": "contract-1",
        }

    def test_shadow_run_hashes_persisted_output_and_never_delivers(self):
        previous = self._report(report_id="report-0", coverage=0.4)
        current = self._report(report_id="report-1", coverage=0.8)
        first = build_shadow_run(report=current, previous_report=previous)
        same = build_shadow_run(report=current, previous_report=previous)
        self.assertEqual(first["output_hash"], same["output_hash"])
        self.assertEqual("report:report-1:output:" + first["output_hash"][:24], first["run_key"])
        self.assertEqual("changed", first["diff"]["status"])
        self.assertFalse(first["outbound_message_sent"])
        self.assertFalse(first["scheduler_changed"])
        self.assertFalse(first["model_rerun"])
        self.assertIn("shadow_mode", first["no_send_reason"])

    def test_shadow_hash_changes_when_persisted_output_changes(self):
        first = build_shadow_run(report=self._report(report_id="report-1", coverage=0.4))
        changed = build_shadow_run(report=self._report(report_id="report-1", coverage=0.9))
        self.assertNotEqual(first["output_hash"], changed["output_hash"])
        self.assertEqual("failed", first["status"])
        self.assertFalse(first["checks"]["evidence_pack_intact"])

    def test_shadow_run_routes_are_registered(self):
        paths = set(app.openapi()["paths"])
        self.assertIn("/bee-cfo/reports/{report_id}/shadow-run", paths)


if __name__ == "__main__":
    unittest.main()
