"""Operational governance primitives for Bee CFO.

These functions are deliberately pure.  They make the benchmark ideas
auditable without coupling Bee CFO to Researcher's persistence or UI.  The
service layer can persist their JSON output in the immutable report snapshot
and expose it through the Bee CFO API.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


OPERATIONS_REVISION = "bee-cfo-ops-2"
EVIDENCE_QUALITY_REVISION = "bee-cfo-evidence-quality-1"
REPLAY_BUNDLE_REVISION = "bee-cfo-replay-bundle-1"

_GAP_LABELS = {
    "quote": ("قیمت معتبر", "ثبت دوباره قیمت از منبع فعال و مالک‌تأییدشده"),
    "source_health": ("سلامت منبع", "بررسی منبع جایگزین و ثبت نتیجه failover"),
    "freshness": ("تازگی داده", "منبع تازه‌تر یا نوبت جمع‌آوری بعدی"),
    "media_opinion": ("نظر صریح رسانه‌ای", "جست‌وجوی مقاله‌ای که افق و جهت را صریح بیان کند"),
    "benchmark": ("benchmark مقایسه‌ای", "ثبت مرجع مقایسه‌ای معتبر توسط مالک محصول"),
    "forecast": ("پیش‌بینی عددی", "جمع‌آوری حداقل تاریخچه قیمت کافی"),
    "independent_sources": ("منابع مستقل", "افزودن یا تأیید دست‌کم یک منبع مستقل دیگر"),
    "persian_coverage": ("پوشش فارسی", "ثبت یک منبع فارسیِ مرتبط و قابل‌ردیابی"),
    "english_coverage": ("پوشش انگلیسی", "ثبت یک منبع انگلیسیِ مرتبط و قابل‌ردیابی"),
    "official_coverage": ("منبع رسمی", "ثبت یا تأیید یک منبع رسمی/اولیه برای موضوع‌های حساس"),
    "news_coverage": ("منبع خبری", "ثبت یک منبع خبری مستقل برای راستی‌آزمایی روایت"),
}


def _clamp(value: object, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return round(max(low, min(high, float(value))), 4)
    except (TypeError, ValueError):
        return low


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _stable_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _stable_json(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_stable_json(item) for item in value]
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(_stable_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def assess_evidence_quality(current_state: Mapping[str, object]) -> dict[str, object]:
    """Make a report's evidence sufficiency explicit before publication.

    Missing optional inputs remain visible as no-call reasons; they are not
    silently manufactured.  A report with no captured/citable evidence or
    insufficient coverage is held rather than published as analysis.
    """
    from .evidence import verify_evidence_pack

    state = dict(current_state or {})
    coverage = state.get("coverage_score") if isinstance(state.get("coverage_score"), Mapping) else {}
    pack = verify_evidence_pack(state.get("evidence_pack"))
    evidence_count = int(state.get("analysis_evidence_count") or 0)
    media = state.get("media_perspectives") if isinstance(state.get("media_perspectives"), list) else []
    invalid_media = [item for item in media if isinstance(item, Mapping) and not str(item.get("source_url") or "").startswith("https://")]
    no_call_reasons: list[dict[str, str]] = []
    forecast = state.get("price_forecast") if isinstance(state.get("price_forecast"), Mapping) else {}
    if forecast.get("status") in {"no_call", "limited"}:
        no_call_reasons.append({"component": "price_forecast", "reason": str(forecast.get("reason") or forecast.get("status"))})
    for item in coverage.get("missing", []) if isinstance(coverage.get("missing"), list) else []:
        no_call_reasons.append({"component": str(item), "reason": "missing_or_unavailable_input"})
    checks = {
        "evidence_pack_intact": bool(pack.get("ready")),
        "citable_evidence_present": evidence_count > 0 and int(pack.get("entry_count") or 0) > 0,
        "coverage_sufficient": str(coverage.get("status") or "") in {"partial", "complete"} and float(coverage.get("score") or 0) >= 0.45,
        "media_links_valid": not invalid_media,
        "no_call_reasons_disclosed": bool(no_call_reasons) or bool(forecast) or bool(coverage),
    }
    blockers = [key for key, valid in checks.items() if not valid]
    return {
        "revision": EVIDENCE_QUALITY_REVISION,
        "status": "publishable" if not blockers else "held",
        "publication_permitted": not blockers,
        "checks": checks,
        "blockers": blockers,
        "coverage": {"score": coverage.get("score"), "status": coverage.get("status"), "missing": coverage.get("missing", [])},
        "evidence": pack,
        "invalid_media_link_count": len(invalid_media),
        "no_call_reasons": no_call_reasons,
    }


def build_confidence_budget(
    *,
    coverage: Mapping[str, object] | None,
    model_agreement: Mapping[str, object] | None,
    media_pulse: Mapping[str, object] | None,
    forecast: Mapping[str, object] | None,
    source_health: Mapping[str, object] | None = None,
    evidence_count: int = 0,
    source_count: int = 0,
) -> dict[str, object]:
    """Decompose confidence so a user can see what limits the conclusion."""

    coverage = coverage or {}
    agreement = model_agreement or {}
    pulse = media_pulse or {}
    forecast = forecast or {}
    health = source_health or {}
    components = {
        "coverage": _clamp(coverage.get("score")),
        "source_health": _clamp(health.get("score", 1.0 if source_count else 0.0)),
        "history": _clamp(min(1.0, evidence_count / 8.0)),
        "forecast_quality": _clamp(1.0 if forecast.get("status") == "available" else 0.35 if forecast.get("status") == "limited" else 0.0),
        "model_agreement": _clamp(1.0 if agreement.get("status") == "agreement" else 0.55 if agreement.get("status") == "mixed" else 0.25),
        "media_explicitness": _clamp(
            float(pulse.get("explicit_opinion_count", 0) or 0)
            / max(1.0, float(pulse.get("coverage_volume", 0) or 0))
        ),
    }
    weights = {
        "coverage": 0.25,
        "source_health": 0.20,
        "history": 0.15,
        "forecast_quality": 0.15,
        "model_agreement": 0.15,
        "media_explicitness": 0.10,
    }
    overall = _clamp(sum(components[key] * weights[key] for key in weights))
    missing: list[str] = []
    if components["coverage"] < 0.6:
        missing.append("coverage")
    if components["source_health"] < 0.6:
        missing.append("source_health")
    if components["history"] < 0.5:
        missing.append("history")
    if components["forecast_quality"] < 0.5:
        missing.append("forecast_quality")
    if components["model_agreement"] < 0.5:
        missing.append("model_agreement")
    return {
        "revision": OPERATIONS_REVISION,
        "overall": overall,
        "label": "بالا" if overall >= 0.75 else "متوسط" if overall >= 0.5 else "محدود",
        "components": components,
        "weights": weights,
        "missing": missing,
        "basis": {"evidence_count": max(0, int(evidence_count)), "source_count": max(0, int(source_count))},
    }


def _evidence_value(item: object, key: str) -> object:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def build_coverage_gaps(
    coverage: Mapping[str, object] | None,
    *,
    evidence: Iterable[object] = (),
) -> list[dict[str, object]]:
    """Turn machine coverage gaps into actionable, non-alarming checks.

    The optional evidence view adds structural gaps (language, authority and
    independent-source diversity) without pretending that an absent source is
    a market signal.  It is deliberately a coverage disclosure only.
    """

    missing = coverage.get("missing", []) if isinstance(coverage, Mapping) else []
    result: list[dict[str, object]] = []
    for key in missing if isinstance(missing, list) else []:
        normalized = str(key)
        label, next_action = _GAP_LABELS.get(normalized, (normalized, "بررسی داده و منبع مربوط"))
        result.append({"key": normalized, "label": label, "next_action": next_action, "severity": "watch"})
    rows = list(evidence)
    if not rows:
        return result
    texts = [
        " ".join(str(_evidence_value(item, key) or "") for key in ("title", "text", "source_name"))
        for item in rows
    ]
    authorities = {str(_evidence_value(item, "source_authority") or "").casefold() for item in rows}
    source_keys = {str(_evidence_value(item, "source_key") or "") for item in rows if _evidence_value(item, "source_key")}
    structural = {
        "independent_sources": len(source_keys) >= 2,
        "persian_coverage": any(re.search(r"[\u0600-\u06FF]", text) for text in texts),
        "english_coverage": any(re.search(r"[A-Za-z]", text) for text in texts),
        "official_coverage": bool(authorities & {"official", "primary", "government", "regulator"}),
        "news_coverage": bool(authorities & {"news", "media", "analysis"}),
    }
    present = {str(item.get("key") or "") for item in result}
    for key, available in structural.items():
        if available or key in present:
            continue
        label, next_action = _GAP_LABELS[key]
        result.append({"key": key, "label": label, "next_action": next_action, "severity": "watch"})
    return result


def classify_alert_maturity(
    *,
    candidate: Mapping[str, object],
    independent_sources: int,
    source_quality: float,
    stale: bool = False,
) -> dict[str, object]:
    """Classify an alert before it can become a public notification."""

    reasons: list[str] = []
    if stale:
        reasons.append("داده یا قیمت کهنه است")
    if independent_sources <= 0:
        reasons.append("منبع مستقل کافی وجود ندارد")
    if source_quality < 0.45:
        reasons.append("کیفیت منبع زیر حداقل است")
    if stale or independent_sources <= 0 or source_quality < 0.25:
        status = "suppressed"
        can_publish = False
    elif independent_sources >= 2 and source_quality >= 0.6:
        status = "corroborated"
        can_publish = True
    else:
        status = "candidate"
        can_publish = False
        reasons.append("برای انتشار عمومی به تأیید مستقل دوم یا کیفیت بالاتر نیاز است")
    return {
        "status": status,
        "can_publish": can_publish,
        "reasons": reasons,
        "independent_sources": max(0, int(independent_sources)),
        "source_quality": _clamp(source_quality),
        "candidate": dict(candidate),
    }


def build_open_checks(
    *,
    current_state: Mapping[str, object],
    report_as_of: object,
    forecasts: Sequence[Mapping[str, object]] = (),
    live_uat_required: bool = True,
) -> list[dict[str, object]]:
    """Build a deterministic review queue from the report itself."""

    checks: list[dict[str, object]] = []
    coverage = current_state.get("coverage_score") if isinstance(current_state.get("coverage_score"), Mapping) else {}
    recorded_gaps = current_state.get("coverage_gaps")
    gaps = recorded_gaps if isinstance(recorded_gaps, list) else build_coverage_gaps(coverage)
    for gap in gaps:
        if not isinstance(gap, Mapping):
            continue
        checks.append({"check_key": f"coverage:{gap['key']}", "kind": "coverage_gap", "status": "open", **gap})
    if current_state.get("media_conflicts"):
        checks.append({
            "check_key": "media:internal_conflict",
            "kind": "media_conflict",
            "status": "open",
            "label": "تعارض داخلی رسانه",
            "next_action": "هر دو مقاله و افق زمانی آن‌ها را جداگانه نگه دار؛ یکی را حذف نکن",
            "severity": "important",
        })
    if (current_state.get("model_agreement") or {}).get("status") == "disagreement":
        checks.append({
            "check_key": "forecast:model_disagreement",
            "kind": "model_disagreement",
            "status": "open",
            "label": "اختلاف مدل یا افق",
            "next_action": "سناریوها و عدم‌قطعیت را قبل از تصمیم بررسی کن",
            "severity": "watch",
        })
    if current_state.get("price_forecast_status") in {"limited", "no_call"}:
        checks.append({
            "check_key": "forecast:limited",
            "kind": "forecast_quality",
            "status": "open",
            "label": "پیش‌بینی عددی محدود است",
            "next_action": "تاریخچه قیمت و کیفیت منبع را تکمیل کن",
            "severity": "watch",
        })
    for forecast in forecasts:
        if not isinstance(forecast, Mapping):
            continue
        scenario_key = str(forecast.get("key") or forecast.get("scenario_key") or "").strip()
        if not scenario_key:
            continue
        checks.append({
            "check_key": f"forecast:{scenario_key}",
            "kind": "forecast_review",
            "status": "open",
            "label": f"بازبینی سناریوی {scenario_key}",
            "next_action": str(forecast.get("invalidation") or "ثبت actual در پایان افق و ارزیابی نتیجه"),
            "severity": "watch",
            "review_due": forecast.get("horizon_end") or report_as_of,
        })
    if live_uat_required:
        checks.append({
            "check_key": "delivery:live_uat",
            "kind": "live_uat",
            "status": "open",
            "label": "تأیید زنده تلگرام",
            "next_action": "یک ارسال کنترل‌شده در کانال آزمایشی و بررسی ترتیب پیام‌ها",
            "severity": "important",
        })
    return [{"as_of": str(report_as_of), **item} for item in checks]


def deduplicate_open_checks(checks: Sequence[Mapping[str, object]], *, limit: int = 200) -> list[dict[str, object]]:
    """Keep the newest copy of a check so follow-up digests are idempotent."""

    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in checks:
        key = str(item.get("watch_id") or "") + ":" + str(item.get("check_key") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
        if len(result) >= limit:
            break
    return result


def _stable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _stable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


def build_report_diff(previous: Mapping[str, object] | None, current: Mapping[str, object]) -> dict[str, object]:
    """Compare report facts and evidence without re-running a model."""

    fields = (
        "confidence_budget", "coverage_score", "price_forecast", "media_pulse",
        "media_consensus", "media_conflicts", "factor_summary", "events", "open_checks",
    )
    changed: list[dict[str, object]] = []
    before = previous or {}
    for field in fields:
        old = _stable(before.get(field))
        new = _stable(current.get(field))
        if old != new:
            changed.append({"field": field, "before": old, "after": new})
    old_cards = {str(item.get("evidence_id")) for item in (before.get("evidence_cards") or []) if isinstance(item, Mapping)}
    new_cards = {str(item.get("evidence_id")) for item in (current.get("evidence_cards") or []) if isinstance(item, Mapping)}
    return {
        "revision": OPERATIONS_REVISION,
        "status": "baseline" if previous is None else "changed" if changed or old_cards != new_cards else "unchanged",
        "changed_fields": changed,
        "new_evidence_ids": sorted(new_cards - old_cards),
        "removed_evidence_ids": sorted(old_cards - new_cards),
        "evidence_delta": len(new_cards) - len(old_cards),
        "no_model_rerun": True,
    }


def build_replay_payload(reports: Sequence[Mapping[str, object]], cutoff: object) -> dict[str, object]:
    """Select the last report available at a point in time."""

    cutoff_dt = _as_datetime(cutoff)
    if cutoff_dt is None:
        raise ValueError("cutoff must be an ISO timestamp")
    eligible: list[Mapping[str, object]] = []
    excluded = 0
    for report in reports:
        timestamp = _as_datetime(report.get("as_of"))
        if timestamp is not None and timestamp <= cutoff_dt:
            eligible.append(report)
        else:
            excluded += 1
    eligible.sort(key=lambda item: _as_datetime(item.get("as_of")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    selected = dict(eligible[0]) if eligible else None
    selected_state = selected.get("current_state") if isinstance(selected, Mapping) and isinstance(selected.get("current_state"), Mapping) else {}
    evidence_pack = selected_state.get("evidence_pack") if isinstance(selected_state, Mapping) else {}
    entries = evidence_pack.get("entries") if isinstance(evidence_pack, Mapping) and isinstance(evidence_pack.get("entries"), list) else []
    source_manifest = [
        {
            "evidence_id": item.get("evidence_id"), "source_key": item.get("source_key"),
            "source_url": item.get("source_url"), "content_hash": item.get("content_hash"),
            "published_at": item.get("published_at"), "captured_at": item.get("captured_at"),
        }
        for item in entries if isinstance(item, Mapping)
    ]
    manifest = {
        "revision": REPLAY_BUNDLE_REVISION,
        "report_id": selected.get("id") if selected else None,
        "as_of": selected.get("as_of") if selected else None,
        "cutoff": cutoff_dt.isoformat(),
        "evidence_manifest_hash": evidence_pack.get("manifest_hash") if isinstance(evidence_pack, Mapping) else None,
        "source_manifest": source_manifest,
        "analysis_window": selected_state.get("analysis_window") if isinstance(selected_state, Mapping) else None,
        "output_contract_revision": selected.get("output_contract_revision") if selected else None,
        "model": selected.get("model") if selected else None,
        "raw_bodies_included": False,
        "secret_values_included": False,
    }
    manifest["replay_hash"] = _digest(manifest)
    return {
        "revision": OPERATIONS_REVISION,
        "cutoff": cutoff_dt.isoformat(),
        "selected_report": selected,
        "eligible_count": len(eligible),
        "excluded_future_count": excluded,
        "no_lookahead": True,
        "status": "available" if selected else "no_report_at_cutoff",
        "replay_manifest": manifest,
    }


def build_capacity_budget(
    *,
    source_count: int,
    evidence_count: int,
    media_forecast_count: int,
    price_source_count: int,
    model_calls: int = 1,
) -> dict[str, object]:
    """Expose bounded work before a report is accepted by the scheduler."""

    limits = {
        "sources": 40,
        "evidence": 200,
        "media_forecasts": 120,
        "price_sources": 8,
        "model_calls": 2,
    }
    usage = {
        "sources": max(0, int(source_count)),
        "evidence": max(0, int(evidence_count)),
        "media_forecasts": max(0, int(media_forecast_count)),
        "price_sources": max(0, int(price_source_count)),
        "model_calls": max(0, int(model_calls)),
    }
    exceeded = [key for key, value in usage.items() if value > limits[key]]
    return {
        "revision": OPERATIONS_REVISION,
        "status": "blocked" if exceeded else "within_budget",
        "limits": limits,
        "usage": usage,
        "remaining": {key: max(0, limits[key] - value) for key, value in usage.items()},
        "exceeded": exceeded,
        "estimated_work_units": usage["sources"] + usage["evidence"] + usage["media_forecasts"] + usage["price_sources"] * 2 + usage["model_calls"] * 10,
        "latency_budget_seconds": 90,
        "degraded_mode": bool(exceeded or usage["sources"] > 30 or usage["evidence"] > 150),
        "cost_visibility": "estimated_work_units; provider billing is intentionally not inferred",
    }


def assess_delivery_readiness(
    *,
    profile_status: object,
    timezone_configured: bool,
    has_schedule_slots: bool,
    selected_market_configured: bool,
    indicator_selected: bool,
    active_source_count: int,
    active_watch_count: int,
    watches_reference_active_sources: bool,
    telegram_token_configured: bool,
    telegram_destination_configured: bool,
    output_contract_valid: bool = True,
) -> dict[str, object]:
    """Separate a controlled manual pilot from automatic publication.

    A manual pilot must be able to deliver one explicitly requested report
    while the scheduler remains inactive.  Automatic publication has the
    stricter requirements: an active profile and at least one validated slot.
    The function is pure so the API can expose both decisions without
    changing profile state or sending a Telegram message.
    """

    manual_blockers: list[str] = []
    if str(profile_status) not in {"testing", "active"}:
        manual_blockers.append("profile must be testing or active for a controlled manual pilot")
    if not timezone_configured:
        manual_blockers.append("timezone must be configured")
    if not selected_market_configured:
        manual_blockers.append("at least one selected market is required")
    if not indicator_selected:
        manual_blockers.append("one active market/index selection is required")
    if active_source_count <= 0:
        manual_blockers.append("at least one active, validated source is required")
    if active_watch_count <= 0:
        manual_blockers.append("at least one active watch is required")
    if not watches_reference_active_sources:
        manual_blockers.append("every active watch must reference at least one active source")
    if not telegram_token_configured or not telegram_destination_configured:
        manual_blockers.append("Telegram token and destination must be configured outside the Sheet")
    if not output_contract_valid:
        manual_blockers.append("output language must be fa or en")

    scheduled_blockers = list(manual_blockers)
    if str(profile_status) != "active":
        scheduled_blockers.append("profile must be active before automatic publication")
    if not has_schedule_slots:
        scheduled_blockers.append("timezone and schedule slots must be configured for automatic publication")

    return {
        "revision": "bee-cfo-delivery-readiness-1",
        "manual_pilot": {
            "status": "ready" if not manual_blockers else "blocked",
            "ready": not manual_blockers,
            "blockers": manual_blockers,
            "mode": "explicit on-demand generation and delivery only; scheduler remains inactive",
        },
        "scheduled_delivery": {
            "status": "ready" if not scheduled_blockers else "blocked",
            "ready": not scheduled_blockers,
            "blockers": scheduled_blockers,
            "mode": "automatic publication only after an active profile and configured slots",
        },
    }


def build_price_source_health(
    *,
    attempted_sources: Sequence[str],
    selected_source: str | None,
    errors: Sequence[str] = (),
) -> dict[str, object]:
    """Represent primary/failover behaviour without exposing credentials."""

    attempted = [str(item) for item in attempted_sources if str(item).strip()]
    errors_list = [str(item)[:240] for item in errors]
    success = bool(selected_source)
    score = 1.0 if success and len(errors_list) == 0 else 0.75 if success else 0.0
    return {
        "revision": OPERATIONS_REVISION,
        "status": "healthy" if score >= 0.9 else "failover" if success else "failed",
        "score": score,
        "attempted_sources": attempted,
        "selected_source": selected_source,
        "failover_used": bool(selected_source and attempted and attempted[0] != selected_source),
        "errors": errors_list,
    }


def evaluate_telegram_uat(
    *,
    price_delivery: Mapping[str, object] | None,
    report_delivery: Mapping[str, object] | None,
) -> dict[str, object]:
    """Validate Telegram delivery ordering and idempotency from ledgers."""

    price = price_delivery or {}
    report = report_delivery or {}
    checks = [
        {"key": "price_sent", "passed": price.get("status") == "sent" and bool(price.get("message_ids"))},
        {"key": "media_sent", "passed": bool(report.get("media_message_ids"))},
        {"key": "report_sent", "passed": report.get("status") == "sent" and bool(report.get("media_message_ids") or report.get("message_ids"))},
        {"key": "no_duplicate", "passed": report.get("status") != "duplicate"},
    ]
    return {
        "revision": OPERATIONS_REVISION,
        "status": "passed" if all(item["passed"] for item in checks) else "blocked",
        "checks": checks,
        "ordering": "price → media outlook",
        "live": True,
    }
