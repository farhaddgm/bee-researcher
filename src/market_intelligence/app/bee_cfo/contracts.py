from __future__ import annotations

import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.fetchers import validate_public_url_syntax


SOURCE_ORIGINS = {"user", "discovered"}
SOURCE_AUTHORITIES = {"official", "specialist", "news", "exploratory", "unknown"}
SOURCE_STATUSES = {"draft", "active", "disabled", "rejected"}
WATCH_STATUSES = {"draft", "active", "paused"}
REPORT_KINDS = {"scheduled", "weekly", "on_demand", "change_alert"}
MEDIA_PERSPECTIVE_STANCES = {"up", "down", "flat", "unknown"}
MEDIA_PERSPECTIVE_TYPES = {"explicit_opinion", "no_explicit_opinion"}
REQUIRED_OUTPUT_SECTIONS = (
    "current_state",
    "scenarios",
    "changes",
    "sources",
    "uncertainties",
)
PERSONAL_ADVICE_TERMS = (
    "بخر",
    "بفروش",
    "خرید کن",
    "فروش کن",
    "سرمایه گذاری کن",
    "سرمایه‌گذاری کن",
    "سبد شما",
    "دارایی شما",
    "پورتفوی شما",
)


def _require_text(value: object, field: str, *, max_length: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > max_length:
        raise ValueError(f"{field} is too long")
    return result


def validate_timezone(value: object) -> str:
    timezone_name = _require_text(value, "timezone", max_length=64)
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return timezone_name


def validate_schedule_slots(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("schedule_slots must contain at least one weekday/time slot")
    normalized: set[tuple[int, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("schedule_slots must contain objects")
        try:
            weekday = int(item.get("weekday"))
        except (TypeError, ValueError) as exc:
            raise ValueError("schedule slot weekday must be an integer from 0 to 6") from exc
        time_value = str(item.get("time", "")).strip()
        if weekday < 0 or weekday > 6 or len(time_value) != 5 or time_value[2] != ":":
            raise ValueError("schedule slot must contain weekday 0..6 and HH:MM")
        try:
            hour, minute = (int(part) for part in time_value.split(":"))
        except ValueError as exc:
            raise ValueError("schedule slot must contain HH:MM") from exc
        if hour > 23 or minute > 59:
            raise ValueError("schedule slot must contain HH:MM")
        normalized.add((weekday, f"{hour:02d}:{minute:02d}"))
    return [
        {"weekday": weekday, "time": time_value}
        for weekday, time_value in sorted(normalized, key=lambda row: (row[0], row[1]))
    ]


def validate_output_contract(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("output_contract must be an object")
    sections = value.get("sections", list(REQUIRED_OUTPUT_SECTIONS))
    if not isinstance(sections, list) or any(not isinstance(item, str) for item in sections):
        raise ValueError("output_contract.sections must be a list of strings")
    missing = [section for section in REQUIRED_OUTPUT_SECTIONS if section not in sections]
    if missing:
        raise ValueError(f"output_contract is missing sections: {', '.join(missing)}")
    language = str(value.get("language", "fa")).strip().lower()
    if language not in {"fa", "en"}:
        raise ValueError("output_contract.language must be fa or en")
    try:
        max_chars = int(value.get("max_chars", 6000))
    except (TypeError, ValueError) as exc:
        raise ValueError("output_contract.max_chars must be an integer") from exc
    if max_chars < 500 or max_chars > 20_000:
        raise ValueError("output_contract.max_chars must be between 500 and 20000")
    return {
        "sections": list(dict.fromkeys(sections)),
        "language": language,
        "max_chars": max_chars,
        "tone": str(value.get("tone", "رسمی، شفاف و تحلیلی")).strip()[:200],
        "include_citations": bool(value.get("include_citations", True)),
    }


def validate_source_registration(payload: dict[str, Any]) -> dict[str, object]:
    # The shared fetch catalog currently accepts sixteen-character keys.  The
    # Bee CFO registry keeps the same bound so the adapter cannot truncate or
    # silently remap provenance when it syncs an operational source.
    source_key = _require_text(payload.get("source_key"), "source_key", max_length=16)
    if not all(character.isalnum() or character in {"-", "_"} for character in source_key):
        raise ValueError("source_key contains invalid characters")
    name = _require_text(payload.get("name"), "name", max_length=200)
    homepage_url = validate_public_url_syntax(_require_text(payload.get("homepage_url"), "homepage_url", max_length=2048))
    fetch_url = validate_public_url_syntax(_require_text(payload.get("fetch_url"), "fetch_url", max_length=2048))
    adapter = str(payload.get("adapter", "rss")).strip().lower()
    if adapter not in {"rss", "html", "json"}:
        raise ValueError("adapter must be rss, html, or json")
    origin = str(payload.get("origin", "user")).strip().lower()
    if origin not in SOURCE_ORIGINS:
        raise ValueError("origin must be user or discovered")
    authority = str(payload.get("authority", "unknown")).strip().lower()
    if authority not in SOURCE_AUTHORITIES:
        raise ValueError("authority is invalid")
    status = str(payload.get("status", "active" if origin == "user" else "draft")).strip().lower()
    if status not in SOURCE_STATUSES:
        raise ValueError("source status is invalid")
    if origin == "discovered" and status == "active":
        raise ValueError("discovered sources require explicit approval before activation")
    try:
        priority = int(payload.get("priority", 3))
        freshness_hours = int(payload.get("freshness_hours", 72))
    except (TypeError, ValueError) as exc:
        raise ValueError("priority and freshness_hours must be integers") from exc
    if priority < 1 or priority > 5 or freshness_hours < 1 or freshness_hours > 24 * 30:
        raise ValueError("priority or freshness_hours is outside the allowed range")
    return {
        "source_key": source_key,
        "name": name,
        "homepage_url": homepage_url,
        "fetch_url": fetch_url,
        "adapter": adapter,
        "origin": origin,
        "discovery_path": str(payload.get("discovery_path", "user_provided" if origin == "user" else "domain_discovery"))[:64],
        "authority": authority,
        "status": status,
        "priority": priority,
        "freshness_hours": freshness_hours,
        "language": str(payload.get("language", "fa"))[:16],
        "region": str(payload.get("region", "global"))[:32],
        "metadata_json": payload.get("metadata_json") if isinstance(payload.get("metadata_json"), dict) else {},
    }


def validate_watch_registration(payload: dict[str, Any]) -> dict[str, object]:
    watch_key = _require_text(payload.get("watch_key"), "watch_key", max_length=64)
    name = _require_text(payload.get("name"), "name", max_length=200)
    market = _require_text(payload.get("market"), "market", max_length=80)
    asset_class = _require_text(payload.get("asset_class"), "asset_class", max_length=80)
    status = str(payload.get("status", "draft")).strip().lower()
    if status not in WATCH_STATUSES:
        raise ValueError("watch status is invalid")
    indicator_keys = payload.get("indicator_keys", [])
    source_keys = payload.get("source_keys", [])
    if not isinstance(indicator_keys, list) or any(not isinstance(item, str) for item in indicator_keys):
        raise ValueError("indicator_keys must be a list of strings")
    if not isinstance(source_keys, list) or any(not isinstance(item, str) for item in source_keys):
        raise ValueError("source_keys must be a list of strings")
    return {
        "watch_key": watch_key,
        "name": name,
        "market": market,
        "asset_class": asset_class,
        "region": str(payload.get("region", "global"))[:32],
        "currency": str(payload.get("currency"))[:16] if payload.get("currency") else None,
        "description": str(payload.get("description", ""))[:4000],
        "indicator_keys": list(dict.fromkeys(indicator_keys)),
        "source_keys": list(dict.fromkeys(source_keys)),
        "status": status,
    }


def validate_market_report(payload: dict[str, Any]) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("market report must be an object")
    current_state = payload.get("current_state")
    scenarios = payload.get("scenarios")
    if not isinstance(current_state, dict) or not isinstance(scenarios, list) or len(scenarios) != 3:
        raise ValueError("market report requires current_state and exactly three scenarios")
    raw_media_perspectives = current_state.get("media_perspectives", [])
    if not isinstance(raw_media_perspectives, list):
        raise ValueError("current_state.media_perspectives must be a list")
    media_perspectives: list[dict[str, object]] = []
    for perspective in raw_media_perspectives[:100]:
        if not isinstance(perspective, dict):
            raise ValueError("each media perspective must be an object")
        source_key = _require_text(perspective.get("source_key"), "media_perspective.source_key", max_length=64)
        source_name = _require_text(perspective.get("source_name"), "media_perspective.source_name", max_length=200)
        source_url = validate_public_url_syntax(
            _require_text(perspective.get("source_url"), "media_perspective.source_url", max_length=2048)
        )
        view = _require_text(perspective.get("view"), "media_perspective.view", max_length=700)
        stance = str(perspective.get("stance", "unknown")).strip().lower()
        if stance not in MEDIA_PERSPECTIVE_STANCES:
            raise ValueError("media_perspective.stance is invalid")
        evidence_type = str(perspective.get("evidence_type", "explicit_opinion")).strip().lower()
        if evidence_type not in MEDIA_PERSPECTIVE_TYPES:
            raise ValueError("media_perspective.evidence_type is invalid")
        try:
            perspective_confidence = float(perspective.get("confidence", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("media_perspective.confidence must be numeric") from exc
        if perspective_confidence < 0 or perspective_confidence > 1:
            raise ValueError("media_perspective.confidence must be between 0 and 1")
        published_at = perspective.get("published_at")
        if published_at is not None and not isinstance(published_at, str):
            raise ValueError("media_perspective.published_at must be a string or null")
        media_perspectives.append(
            {
                "source_key": source_key,
                "source_name": source_name,
                "source_url": source_url,
                "published_at": published_at,
                "forecast_id": str(perspective.get("forecast_id") or "")[:64] or None,
                "article_id": str(perspective.get("article_id") or "")[:64] or None,
                "statement_index": int(perspective.get("statement_index") or 0),
                "analyst_name": str(perspective.get("analyst_name") or "")[:500] or None,
                "view": view,
                "snippet": str(perspective.get("snippet") or "")[:700] or None,
                "stance": stance,
                "horizon": str(perspective.get("horizon", "نامشخص")).strip()[:80] or "نامشخص",
                "horizon_key": str(perspective.get("horizon_key", "unspecified")).strip()[:24] or "unspecified",
                "horizon_label": str(perspective.get("horizon_label") or perspective.get("horizon") or "نامشخص").strip()[:80] or "نامشخص",
                "horizon_days": int(perspective["horizon_days"]) if str(perspective.get("horizon_days", "")).isdigit() else None,
                "horizon_explicit": bool(perspective.get("horizon_explicit", False)),
                "horizon_confidence": max(0.0, min(1.0, float(perspective.get("horizon_confidence", 0) or 0))),
                "evidence_type": evidence_type,
                "confidence": round(perspective_confidence, 6),
                "evidence_id": str(perspective.get("evidence_id") or "")[:64] or None,
                "conflict_status": str(perspective.get("conflict_status") or "clear")[:32],
                "conflict_group": str(perspective.get("conflict_group") or "")[:64] or None,
                "narrative_key": str(perspective.get("narrative_key") or "")[:64] or None,
                "independence_weight": max(0.0, min(1.0, float(perspective.get("independence_weight", 1) or 1))),
                "status": str(perspective.get("status") or "active")[:24],
                "expires_at": str(perspective.get("expires_at") or "")[:64] or None,
                "temporal_status": str(perspective.get("temporal_status") or "active")[:24],
            }
        )
    scenario_keys: set[str] = set()
    probability_total = 0.0
    normalized_scenarios: list[dict[str, object]] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("each scenario must be an object")
        key = _require_text(scenario.get("key"), "scenario.key", max_length=32)
        if key in scenario_keys:
            raise ValueError("scenario keys must be unique")
        scenario_keys.add(key)
        try:
            probability = float(scenario.get("probability"))
        except (TypeError, ValueError) as exc:
            raise ValueError("scenario probability must be numeric") from exc
        if probability < 0 or probability > 1:
            raise ValueError("scenario probability must be between 0 and 1")
        probability_total += probability
        horizon = _require_text(scenario.get("horizon"), "scenario.horizon", max_length=80)
        expected_change = _require_text(scenario.get("expected_change"), "scenario.expected_change")
        triggers = scenario.get("triggers")
        if not isinstance(triggers, list) or not triggers or any(not isinstance(item, str) or not item.strip() for item in triggers):
            raise ValueError("each scenario requires at least one trigger")
        invalidation = _require_text(scenario.get("invalidation"), "scenario.invalidation")
        normalized_scenarios.append({
            "key": key,
            "title": _require_text(scenario.get("title"), "scenario.title", max_length=200),
            "probability": round(probability, 6),
            "horizon": horizon,
            "expected_change": expected_change,
            "triggers": [str(item).strip() for item in triggers[:12]],
            "invalidation": invalidation,
            "evidence": scenario.get("evidence", []),
        })
    if abs(probability_total - 1.0) > 0.02:
        raise ValueError("scenario probabilities must sum to 1")
    changes = payload.get("changes", [])
    uncertainties = payload.get("uncertainties", [])
    citations = payload.get("citations", [])
    for collection, name in ((changes, "changes"), (uncertainties, "uncertainties"), (citations, "citations")):
        if not isinstance(collection, list):
            raise ValueError(f"{name} must be a list")
    normalized_current_state = dict(current_state)
    normalized_current_state["media_perspectives"] = media_perspectives
    report_text = json.dumps({"current_state": normalized_current_state, "scenarios": normalized_scenarios, "changes": changes, "uncertainties": uncertainties}, ensure_ascii=False)
    if any(term in report_text for term in PERSONAL_ADVICE_TERMS):
        raise ValueError("phase one report cannot contain personalized investment advice")
    try:
        confidence = float(payload.get("confidence", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")
    return {
        "current_state": normalized_current_state,
        "scenarios": normalized_scenarios,
        "changes": changes,
        "uncertainties": uncertainties,
        "citations": citations,
        "confidence": round(confidence, 6),
    }


def state_fingerprint(state: dict[str, object]) -> str:
    canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def detect_state_changes(previous: dict[str, object] | None, current: dict[str, object]) -> list[dict[str, object]]:
    if not previous:
        return []
    changes: list[dict[str, object]] = []
    keys = sorted(set(previous) | set(current))
    for key in keys:
        if previous.get(key) == current.get(key):
            continue
        changes.append({
            "field": key,
            "before": previous.get(key),
            "after": current.get(key),
            "significance": "watch",
        })
    return changes


def calibration_bucket(probability: float) -> str:
    if probability < 0.4:
        return "low"
    if probability < 0.7:
        return "medium"
    return "high"


def evaluate_forecast_outcome(*, expected_direction: str, actual_direction: str | None) -> tuple[str, float | None]:
    if not actual_direction:
        return "not_evaluable", None
    expected = expected_direction.strip().lower()
    actual = actual_direction.strip().lower()
    if expected == actual:
        return "hit", 0.0
    if {expected, actual} <= {"flat", "up", "down"}:
        return "miss", 1.0
    return "partial", 0.5
