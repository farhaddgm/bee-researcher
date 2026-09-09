from __future__ import annotations

import json
from pathlib import Path

from .audit import run_infrastructure_audit
from .benchmarking import benchmark_playbook
from .contracts import validate_market_report
from .operations import evaluate_telegram_uat


GOLDEN_PATH = Path(__file__).resolve().parents[2] / "golden" / "bee_cfo_market_analyst.json"


def run_release_gate() -> dict[str, object]:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    cases = golden.get("cases") or []
    required_kinds = {"relevant", "irrelevant", "conflict", "stale", "source_failure", "forecast"}
    present_kinds = {str(case.get("kind")) for case in cases if isinstance(case, dict)}
    audit = run_infrastructure_audit()
    offline_telegram_uat = evaluate_telegram_uat(
        price_delivery={"status": "sent", "message_ids": [1]},
        report_delivery={"status": "sent", "message_ids": [3], "media_message_ids": [2]},
    )
    validate_market_report(
        {
            "current_state": {"summary": "golden"},
            "scenarios": [
                {"key": "base", "title": "base", "probability": 0.5, "horizon": "7d", "expected_change": "flat", "triggers": ["data"], "invalidation": "new data"},
                {"key": "upside", "title": "upside", "probability": 0.3, "horizon": "7d", "expected_change": "up", "triggers": ["data"], "invalidation": "new data"},
                {"key": "downside", "title": "downside", "probability": 0.2, "horizon": "7d", "expected_change": "down", "triggers": ["data"], "invalidation": "new data"}
            ],
            "changes": [],
            "uncertainties": ["golden fixture"],
            "citations": [],
            "confidence": 0.2
        }
    )
    passed = (
        golden.get("contract_revision") == "bee-cfo-1"
        and required_kinds <= present_kinds
        and audit["status"] == "passed"
        and offline_telegram_uat["status"] == "passed"
        and len(benchmark_playbook()) >= 6
    )
    return {
        "status": "passed" if passed else "blocked",
        "golden_set": str(GOLDEN_PATH),
        "cases": len(cases),
        "missing_kinds": sorted(required_kinds - present_kinds),
        "infrastructure_audit": audit,
        "offline_telegram_uat": offline_telegram_uat,
        "benchmark_playbook_count": len(benchmark_playbook()),
        "operations_revision": "bee-cfo-ops-1",
        "live_uat_required": True,
    }


if __name__ == "__main__":
    print(json.dumps(run_release_gate(), ensure_ascii=False, indent=2))
