from __future__ import annotations

"""Deterministic, non-delivery shadow-run records for Bee CFO.

The module accepts only persisted report payloads.  It deliberately contains no
collector, renderer, scheduler, Telegram, or model call, so the Bee CFO shadow
ledger can later be moved out of the shared Researcher runtime unchanged.
"""

from collections.abc import Mapping
import hashlib
import json

from .evidence import verify_evidence_pack
from .operations import build_report_diff


SHADOW_RUN_REVISION = "bee-cfo-shadow-run-1"


def _stable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _stable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _output_projection(report: Mapping[str, object]) -> dict[str, object]:
    """Select the persisted output fields whose mutation must be detectable."""
    return {
        "report_id": report.get("id"),
        "as_of": report.get("as_of"),
        "status": report.get("status"),
        "current_state": report.get("current_state") if isinstance(report.get("current_state"), Mapping) else {},
        "scenarios": report.get("scenarios") or [],
        "changes": report.get("changes") or {},
        "uncertainties": report.get("uncertainties") or [],
        "citations": report.get("citations") or [],
        "confidence": report.get("confidence"),
        "model": report.get("model") or {},
        "output_contract_revision": report.get("output_contract_revision"),
    }


def build_shadow_run(
    *,
    report: Mapping[str, object],
    previous_report: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a reproducible audit record without attempting delivery.

    A failed integrity check is recorded as a failed shadow run, but it still
    cannot cause a message, source activation, scheduler change, or model rerun.
    """
    output = _output_projection(report)
    previous_output = _output_projection(previous_report) if previous_report else None
    output_hash = _digest(output)
    previous_hash = _digest(previous_output) if previous_output is not None else None
    state = output["current_state"]
    evidence = verify_evidence_pack(state.get("evidence_pack")) if isinstance(state, Mapping) else {
        "ready": False,
        "reason": "missing_evidence_pack",
        "entry_count": 0,
    }
    diff = build_report_diff(
        previous_output.get("current_state") if previous_output is not None else None,
        state if isinstance(state, Mapping) else {},
    )
    checks = {
        "persisted_report": bool(output.get("report_id")),
        "output_hash_recorded": bool(output_hash),
        "evidence_pack_intact": bool(evidence.get("ready")),
        "comparison_read_only": bool(diff.get("no_model_rerun")),
        "outbound_delivery_disabled": True,
        "scheduler_unchanged": True,
    }
    return {
        "revision": SHADOW_RUN_REVISION,
        "run_key": f"report:{output.get('report_id')}:output:{output_hash[:24]}",
        "report_id": output.get("report_id"),
        "report_as_of": output.get("as_of"),
        "output_hash": output_hash,
        "previous_report_id": previous_output.get("report_id") if previous_output else None,
        "previous_output_hash": previous_hash,
        "diff": diff,
        "evidence": evidence,
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
        "no_send_reason": "shadow_mode: outbound delivery and scheduler activation are disabled by design",
        "outbound_message_sent": False,
        "scheduler_changed": False,
        "model_rerun": False,
    }
