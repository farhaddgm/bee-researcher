"""Post-phase-one governance contracts for Bee CFO.

The functions in this module are deliberately deterministic and data-only.
They make no network calls, do not activate a source or a market, and do not
produce investment advice.  Keeping these policies here makes the Bee CFO
bounded context independently portable from Bee Researcher.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from .quote_control import validate_provider_fixture


PILOT_WINDOW_DAYS = 14
PILOT_MIN_RUNS = 30
PILOT_MIN_VALID_RATE = 0.95
# Pilot evidence must come from separately observed market states.  This is
# deliberately shorter than a reporting cadence so a 14-day pilot can collect
# 30 genuine observations, but it prevents a retry loop from inflating the
# acceptance count.
PILOT_MIN_OBSERVATION_INTERVAL_HOURS = 4

MARKET_PACKS: tuple[dict[str, object], ...] = (
    {
        "pack_key": "USD_FREE",
        "sequence": 1,
        "market_key": "IR_FX",
        "indicator_key": "USD_FREE",
        "label": "دلار آزاد",
        "quote_unit": "تومان",
        "currency": "IRR",
        "requires_predecessor": "SRC-001",
    },
    {
        "pack_key": "BTC_USDT",
        "sequence": 2,
        "market_key": "GLOBAL_CRYPTO",
        "indicator_key": "BTC_USDT",
        "label": "بیت‌کوین",
        "quote_unit": "دلار",
        "currency": "USD",
        "requires_predecessor": "USD_FREE",
    },
)

DEFAULT_ATTENTION_POLICY: dict[str, object] = {
    "revision": "bee-cfo-attention-1",
    "enabled": True,
    "daily_cap": 3,
    "minimum_severity": "important",
    "dedup_hours": 12,
    "quiet_hours": {"start": "23:00", "end": "07:00", "timezone": "Asia/Tehran"},
    "expiry_hours": 24,
}

PHASE_TWO_PRIVACY_BOUNDARY: dict[str, object] = {
    "revision": "bee-cfo-privacy-1",
    "phase_one_personal_data_enabled": False,
    "phase_one_allowed_data": ["market_data", "source_metadata", "operational_audit"],
    "future_controls": [
        "explicit_consent",
        "data_minimization",
        "tenant_isolation",
        "retention_and_deletion",
        "export_and_delete",
        "threat_model",
    ],
    "phase_two_processing_enabled": False,
}

_SEVERITY = {"info": 0, "watch": 1, "important": 2, "critical": 3}


def _as_bool(value: object) -> bool:
    return bool(value) is True


def _bounded_int(value: object, *, name: str, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not low <= parsed <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return parsed


def _valid_time(value: object, *, name: str) -> str:
    raw = str(value or "").strip()
    try:
        time.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must use HH:MM") from exc
    if len(raw) != 5:
        raise ValueError(f"{name} must use HH:MM")
    return raw


def assess_pilot_run(checks: Mapping[str, object]) -> dict[str, object]:
    """Classify one controlled run without treating missing evidence as success."""
    required = (
        "report_available",
        "price_valid",
        "citations_valid",
        "horizons_valid",
        "conflict_preserved",
        "no_call_valid",
        "message_length_valid",
        "output_valid",
        "no_personal_advice",
        "no_duplicate_delivery",
    )
    failures = [key for key in required if not _as_bool(checks.get(key))]
    critical = [key for key in ("report_available", "price_valid", "output_valid", "no_personal_advice") if key in failures]
    return {
        "status": "passed" if not failures else "failed",
        "valid": not failures,
        "critical": bool(critical),
        "failed_checks": failures,
        "critical_failures": critical,
        "required_checks": list(required),
    }


def build_verified_pilot_checks(
    *,
    report: Mapping[str, object],
    price_snapshot: Mapping[str, object],
    quality_gate: Mapping[str, object],
    canary_preview: Mapping[str, object],
    shadow_run: Mapping[str, object],
) -> dict[str, bool]:
    """Derive a pilot checklist from canonical no-send controls.

    This removes the need for an operator to translate wrapper payloads by
    hand.  It deliberately accepts only persisted report data, a direct quote
    capture, a private canary, and a shadow-run receipt; it never calls
    Telegram or activates a schedule.
    """
    report_state = report.get("current_state") if isinstance(report.get("current_state"), Mapping) else {}
    quality_checks = quality_gate.get("checks") if isinstance(quality_gate.get("checks"), Mapping) else {}
    canary_checks = canary_preview.get("checks") if isinstance(canary_preview.get("checks"), Mapping) else {}
    price_health = price_snapshot.get("price_source_health") if isinstance(price_snapshot.get("price_source_health"), Mapping) else {}
    consensus = report_state.get("media_consensus") if isinstance(report_state.get("media_consensus"), Mapping) else {}
    media_forecasts = report.get("media_forecasts") if isinstance(report.get("media_forecasts"), list) else []
    shadow_receipt = shadow_run.get("run") if isinstance(shadow_run.get("run"), Mapping) else {}

    has_horizon = any(
        isinstance(item, Mapping) and str(item.get("horizon_key") or item.get("horizon_label") or "").strip()
        for item in media_forecasts
    )
    conflict_schema_present = "conflict_count" in consensus and isinstance(consensus.get("buckets"), list)
    return {
        "price_valid": bool(price_health.get("selected_source"))
        and str(price_snapshot.get("source_url") or "").startswith("https://"),
        "citations_valid": bool(quality_checks.get("citable_evidence_present"))
        and bool(quality_checks.get("media_links_valid")),
        "horizons_valid": bool(media_forecasts)
        and has_horizon
        and bool(canary_checks.get("messages_present")),
        "conflict_preserved": conflict_schema_present,
        "no_call_valid": bool(quality_checks.get("no_call_reasons_disclosed")),
        "message_length_valid": bool(canary_checks.get("message_limits")),
        "output_valid": str(canary_preview.get("status") or "") == "passed"
        and str(shadow_receipt.get("status") or "") == "passed",
        "no_personal_advice": bool(canary_checks.get("no_personal_investment_advice")),
        "no_duplicate_delivery": bool(shadow_run.get("outbound_message_sent") is False)
        and bool(canary_preview.get("outbound_message_sent") is False),
    }


def pilot_observation_eligibility(
    *,
    latest_observed_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Decide whether another no-send pilot observation is meaningful.

    The function is data-only: it does not record a run, call a provider or
    change scheduler state.  The caller uses it before building a fresh report.
    """
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        observed_now = observed_now.replace(tzinfo=timezone.utc)
    if latest_observed_at is None:
        return {
            "eligible": True,
            "reason": "no_previous_observation",
            "minimum_interval_hours": PILOT_MIN_OBSERVATION_INTERVAL_HOURS,
            "next_eligible_at": None,
        }
    normalized_latest = latest_observed_at
    if normalized_latest.tzinfo is None:
        normalized_latest = normalized_latest.replace(tzinfo=timezone.utc)
    next_eligible_at = normalized_latest + timedelta(hours=PILOT_MIN_OBSERVATION_INTERVAL_HOURS)
    return {
        "eligible": observed_now >= next_eligible_at,
        "reason": "eligible" if observed_now >= next_eligible_at else "minimum_observation_interval",
        "minimum_interval_hours": PILOT_MIN_OBSERVATION_INTERVAL_HOURS,
        "next_eligible_at": next_eligible_at.isoformat(),
    }


def summarize_pilot_runs(runs: Sequence[Mapping[str, object]], *, now: datetime) -> dict[str, object]:
    start = now.timestamp() - PILOT_WINDOW_DAYS * 86400
    in_window: list[Mapping[str, object]] = []
    for run in runs:
        occurred = run.get("occurred_at")
        if isinstance(occurred, datetime) and occurred.timestamp() >= start:
            in_window.append(run)
    total = len(in_window)
    passed = sum(bool(row.get("valid")) for row in in_window)
    critical = sum(bool(row.get("critical")) for row in in_window)
    valid_rate = (passed / total) if total else 0.0
    eligible = total >= PILOT_MIN_RUNS and critical == 0 and valid_rate >= PILOT_MIN_VALID_RATE
    return {
        "window_days": PILOT_WINDOW_DAYS,
        "minimum_runs": PILOT_MIN_RUNS,
        "minimum_valid_rate": PILOT_MIN_VALID_RATE,
        "run_count": total,
        "passed_runs": passed,
        "critical_failures": critical,
        "valid_rate": round(valid_rate, 4),
        "status": "passed" if eligible else "collecting",
        "eligible_for_completion": eligible,
        "remaining_runs": max(0, PILOT_MIN_RUNS - total),
    }


def validate_source_decision(payload: Mapping[str, object]) -> dict[str, object]:
    """Normalize a direct-source decision; activation is deliberately absent."""
    required_text = ("indicator_key", "source_key", "owner", "permission_basis", "source_url", "quote_unit", "timezone", "fallback")
    normalized = {key: str(payload.get(key) or "").strip() for key in required_text}
    missing = [key for key, value in normalized.items() if not value]
    if missing:
        raise ValueError(f"source decision missing: {', '.join(missing)}")
    if not normalized["source_url"].startswith("https://"):
        raise ValueError("source_url must use https")
    status = str(payload.get("status") or "draft").strip().lower()
    if status not in {"draft", "approved", "rejected", "expired"}:
        raise ValueError("source decision status is invalid")
    uat_status = str(payload.get("uat_status") or "pending").strip().lower()
    if uat_status not in {"pending", "passed", "failed"}:
        raise ValueError("source decision uat_status is invalid")
    normalized.update(
        status=status,
        uat_status=uat_status,
        refresh_minutes=_bounded_int(payload.get("refresh_minutes", 60), name="refresh_minutes", low=1, high=10080),
        expires_at=str(payload.get("expires_at") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip()[:2000],
        activation_permitted=False,
    )
    fixture = payload.get("provider_fixture")
    enforced = bool(payload.get("provider_fixture_enforced", False))
    if fixture is not None:
        normalized["provider_fixture"] = validate_provider_fixture(fixture)
    if enforced and "provider_fixture" not in normalized:
        raise ValueError("provider_fixture is required when provider_fixture_enforced is true")
    normalized["provider_fixture_enforced"] = enforced
    return normalized


def source_decision_allows_delivery(
    event_status: object,
    decision: Mapping[str, object] | None,
    *,
    indicator_key: str,
    source_key: str,
    now: datetime | None = None,
    current_contract_fingerprint: str | None = None,
) -> bool:
    """Return whether the latest owner decision permits a live quote.

    An active catalog row is only a technical configuration.  It is not enough
    to publish a price: the workspace must also hold an approved, passed and
    non-expired owner decision for the same indicator/source pair.
    """
    payload = dict(decision or {})
    if str(event_status or "").strip().lower() != "approved":
        return False
    if str(payload.get("status") or "").strip().lower() != "approved":
        return False
    if str(payload.get("uat_status") or "").strip().lower() != "passed":
        return False
    if str(payload.get("indicator_key") or "").strip().upper() != str(indicator_key).strip().upper():
        return False
    if str(payload.get("source_key") or "").strip() != str(source_key).strip():
        return False
    if current_contract_fingerprint is not None:
        # New decisions pin the source URL, parser and indicator unit. Legacy
        # decisions remain readable but cannot authorise a changed contract.
        if str(payload.get("contract_fingerprint") or "") != current_contract_fingerprint:
            return False
    expires_at = str(payload.get("expires_at") or "").strip()
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            return False
    except ValueError:
        return False
    return expiry > (now or datetime.now(timezone.utc))


def normalize_attention_policy(payload: Mapping[str, object] | None) -> dict[str, object]:
    raw = {**DEFAULT_ATTENTION_POLICY, **dict(payload or {})}
    severity = str(raw.get("minimum_severity") or "important").strip().lower()
    if severity not in _SEVERITY:
        raise ValueError("minimum_severity is invalid")
    quiet = raw.get("quiet_hours")
    if not isinstance(quiet, Mapping):
        raise ValueError("quiet_hours must be an object")
    timezone_name = str(quiet.get("timezone") or "Asia/Tehran").strip()
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("quiet_hours.timezone must be a valid IANA timezone") from exc
    return {
        "revision": str(raw.get("revision") or "bee-cfo-attention-1")[:64],
        "enabled": bool(raw.get("enabled", True)),
        "daily_cap": _bounded_int(raw.get("daily_cap"), name="daily_cap", low=1, high=20),
        "minimum_severity": severity,
        "dedup_hours": _bounded_int(raw.get("dedup_hours"), name="dedup_hours", low=1, high=168),
        "expiry_hours": _bounded_int(raw.get("expiry_hours"), name="expiry_hours", low=1, high=168),
        "quiet_hours": {
            "start": _valid_time(quiet.get("start"), name="quiet_hours.start"),
            "end": _valid_time(quiet.get("end"), name="quiet_hours.end"),
            "timezone": timezone_name,
        },
    }


def _in_quiet_hours(now: datetime, quiet: Mapping[str, object]) -> bool:
    local = now.astimezone(ZoneInfo(str(quiet["timezone"]))).time()
    start = time.fromisoformat(str(quiet["start"]))
    end = time.fromisoformat(str(quiet["end"]))
    return (start <= local < end) if start < end else (local >= start or local < end)


def evaluate_attention_budget(
    candidate: Mapping[str, object],
    *,
    policy: Mapping[str, object],
    recent_count: int,
    duplicate_seen: bool,
    now: datetime,
) -> dict[str, object]:
    """Return an explainable send/suppress decision. It never sends anything."""
    normalized = normalize_attention_policy(policy)
    severity = str(candidate.get("severity") or "info").lower()
    if severity not in _SEVERITY:
        raise ValueError("candidate severity is invalid")
    reason: str | None = None
    if not normalized["enabled"]:
        reason = "policy_disabled"
    elif _SEVERITY[severity] < _SEVERITY[str(normalized["minimum_severity"])]:
        reason = "below_minimum_severity"
    elif duplicate_seen:
        reason = "duplicate_within_window"
    elif recent_count >= int(normalized["daily_cap"]):
        reason = "daily_attention_cap"
    elif _in_quiet_hours(now, normalized["quiet_hours"]):
        reason = "quiet_hours"
    elif not str(candidate.get("dedup_key") or "").strip():
        reason = "missing_dedup_key"
    return {
        "status": "suppressed" if reason else "eligible",
        "reason": reason,
        "severity": severity,
        "policy_revision": normalized["revision"],
        "send_permitted": reason is None,
        "delivery_performed": False,
    }


def normalize_privacy_boundary(payload: Mapping[str, object] | None) -> dict[str, object]:
    raw = {**PHASE_TWO_PRIVACY_BOUNDARY, **dict(payload or {})}
    if bool(raw.get("phase_one_personal_data_enabled")):
        raise ValueError("phase one cannot enable personal data")
    if bool(raw.get("phase_two_processing_enabled")):
        raise ValueError("phase two processing cannot be enabled from Bee CFO phase one")
    allowed = raw.get("phase_one_allowed_data")
    permitted = set(PHASE_TWO_PRIVACY_BOUNDARY["phase_one_allowed_data"])
    if not isinstance(allowed, list) or set(map(str, allowed)) - permitted:
        raise ValueError("phase one data boundary only allows market and operational metadata")
    return {
        "revision": str(raw.get("revision") or "bee-cfo-privacy-1")[:64],
        "phase_one_personal_data_enabled": False,
        "phase_one_allowed_data": list(PHASE_TWO_PRIVACY_BOUNDARY["phase_one_allowed_data"]),
        "future_controls": list(PHASE_TWO_PRIVACY_BOUNDARY["future_controls"]),
        "phase_two_processing_enabled": False,
        "consent_status": "design_only",
    }
