import os
import unittest


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.bee_cfo.release_gate import run_release_gate  # noqa: E402


class BeeCFOReleaseGateTest(unittest.TestCase):
    def test_golden_set_and_architecture_gate_pass(self):
        result = run_release_gate()
        self.assertEqual("passed", result["status"])
        self.assertEqual(6, result["cases"])
        self.assertTrue(result["live_uat_required"])


if __name__ == "__main__":
    unittest.main()
