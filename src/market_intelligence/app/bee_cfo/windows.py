from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, TypeVar, TypedDict


DEFAULT_PRICE_COMPARISON_WINDOW_HOURS = 24
DEFAULT_MEDIA_ANALYSIS_WINDOW_HOURS = 24 * 7
DEFAULT_PRICE_COMPARISON_TOLERANCE_HOURS = 6
MAX_ANALYSIS_WINDOW_HOURS = 24 * 30
ANALYSIS_WINDOWS_REVISION = "bee-cfo-analysis-windows-1"
_EvidenceT = TypeVar("_EvidenceT")


class AnalysisWindows(TypedDict):
    price_comparison_window_hours: int
    media_analysis_window_hours: int
    price_comparison_tolerance_hours: int
    price_baseline_policy: str
    evidence_timestamp_policy: str
    revision: str


def _hours(value: object, *, field: str, default: int) -> int:
    candidate = value if value is not None else default
    # Configuration values arrive from JSON, where the supported scalar
    # representations are strings and numbers. Validate before coercion so
    # arbitrary objects cannot silently supply a custom __int__ implementation.
    if not isinstance(candidate, (str, bytes, bytearray, int, float, Decimal)):
        raise ValueError(f"{field} must be an integer number of hours")
    try:
        result = int(candidate)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be an integer number of hours") from exc
    if result < 1 or result > MAX_ANALYSIS_WINDOW_HOURS:
        raise ValueError(f"{field} must be between 1 and {MAX_ANALYSIS_WINDOW_HOURS} hours")
    return result


def normalize_analysis_windows(value: object = None) -> AnalysisWindows:
    """Normalize Bee CFO's two independent time windows.

    These settings live inside Bee CFO's profile source policy.  They are not
    shared with Bee Researcher, and the explicit names prevent confusing a
    forecast validity horizon with the period of evidence collected for a
    report.
    """
    raw = value if isinstance(value, Mapping) else {}
    price_hours = _hours(
        raw.get("price_comparison_window_hours", raw.get("price_comparison_hours")),
        field="price_comparison_window_hours",
        default=DEFAULT_PRICE_COMPARISON_WINDOW_HOURS,
    )
    media_hours = _hours(
        raw.get("media_analysis_window_hours", raw.get("media_lookback_hours")),
        field="media_analysis_window_hours",
        default=DEFAULT_MEDIA_ANALYSIS_WINDOW_HOURS,
    )
    tolerance_default = min(
        DEFAULT_PRICE_COMPARISON_TOLERANCE_HOURS,
        max(1, price_hours // 4),
    )
    tolerance_hours = _hours(
        raw.get("price_comparison_tolerance_hours"),
        field="price_comparison_tolerance_hours",
        default=tolerance_default,
    )
    return {
        "price_comparison_window_hours": price_hours,
        "media_analysis_window_hours": media_hours,
        "price_comparison_tolerance_hours": tolerance_hours,
        "price_baseline_policy": "nearest_observation_at_or_before_target",
        "evidence_timestamp_policy": "published_at_then_discovered_at",
        "revision": str(raw.get("revision") or ANALYSIS_WINDOWS_REVISION)[:64],
    }


def merge_analysis_windows(value: object = None) -> AnalysisWindows:
    """Backward-compatible alias used by profile/configuration merge paths."""
    return normalize_analysis_windows(value)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _evidence_timestamp(item: object) -> datetime | None:
    published = getattr(item, "published_at", None)
    discovered = getattr(item, "discovered_at", None)
    return as_utc(published or discovered)


def filter_evidence_by_lookback(
    evidence: Iterable[_EvidenceT],
    *,
    as_of: datetime,
    hours: int,
) -> tuple[list[_EvidenceT], dict[str, object]]:
    """Filter analysis evidence to the configured window without look-ahead."""
    evidence_rows = list(evidence)
    normalized_hours = _hours(hours, field="media_analysis_window_hours", default=DEFAULT_MEDIA_ANALYSIS_WINDOW_HOURS)
    end = as_utc(as_of) or as_of.replace(tzinfo=timezone.utc)
    start = end - timedelta(hours=normalized_hours)
    included: list[_EvidenceT] = []
    missing_timestamp = 0
    excluded_out_of_window = 0
    for item in evidence_rows:
        timestamp = _evidence_timestamp(item)
        if timestamp is None:
            missing_timestamp += 1
            continue
        if start <= timestamp <= end:
            included.append(item)
        else:
            excluded_out_of_window += 1
    return included, {
        "window_hours": normalized_hours,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "timestamp_policy": "published_at_then_discovered_at",
        "collected_evidence_count": len(evidence_rows),
        "included_evidence_count": len(included),
        "excluded_out_of_window_count": excluded_out_of_window,
        "excluded_missing_timestamp_count": missing_timestamp,
    }


def price_comparison(
    observations: Iterable[Mapping[str, object]],
    *,
    as_of: datetime,
    window_hours: int,
    tolerance_hours: int = DEFAULT_PRICE_COMPARISON_TOLERANCE_HOURS,
) -> dict[str, object]:
    """Compute a fail-closed price delta against the configured time target."""
    normalized_window = _hours(
        window_hours,
        field="price_comparison_window_hours",
        default=DEFAULT_PRICE_COMPARISON_WINDOW_HOURS,
    )
    normalized_tolerance = _hours(
        tolerance_hours,
        field="price_comparison_tolerance_hours",
        default=DEFAULT_PRICE_COMPARISON_TOLERANCE_HOURS,
    )
    report_time = as_utc(as_of) or as_of.replace(tzinfo=timezone.utc)
    target = report_time - timedelta(hours=normalized_window)
    lower_bound = target - timedelta(hours=normalized_tolerance)
    upper_bound = target + timedelta(hours=normalized_tolerance)
    parsed: list[tuple[datetime, float, Mapping[str, object]]] = []
    for item in observations:
        observed = item.get("observed_at")
        if isinstance(observed, str):
            try:
                observed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            except ValueError:
                continue
        observed = as_utc(observed if isinstance(observed, datetime) else None)
        if observed is None or observed > report_time:
            continue
        raw_value = item.get("value")
        if not isinstance(raw_value, (str, bytes, bytearray, int, float, Decimal)):
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        parsed.append((observed, value, item))
    parsed.sort(key=lambda row: row[0])
    current = parsed[-1] if parsed else None
    baseline_candidates = [row for row in parsed if lower_bound <= row[0] <= upper_bound]
    # A scheduled run is not guaranteed to have captured a quote immediately
    # before the exact target.  Use the closest valid observation on either
    # side of the target; on an exact tie, prefer the earlier observation.
    baseline = min(
        baseline_candidates,
        key=lambda row: (abs((row[0] - target).total_seconds()), row[0] > target, -row[0].timestamp()),
    ) if baseline_candidates else None
    base = {
        "status": "unavailable",
        "window_hours": normalized_window,
        "target_at": target.isoformat(),
        "tolerance_hours": normalized_tolerance,
        "policy": "nearest_observation_within_tolerance",
        "current_observed_at": current[0].isoformat() if current else None,
        "current_value": current[1] if current else None,
        "baseline_observed_at": None,
        "baseline_value": None,
        "change_value": None,
        "change_percent": None,
        "reason": "no_observation_within_tolerance",
    }
    if baseline is None:
        return base
    baseline_value = baseline[1]
    change_value = current[1] - baseline_value if current else None
    change_percent = (
        change_value / baseline_value * 100
        if change_value is not None and baseline_value != 0
        else None
    )
    return {
        **base,
        "status": "available" if current else "unavailable",
        "baseline_observed_at": baseline[0].isoformat(),
        "baseline_value": baseline_value,
        "change_value": change_value,
        "change_percent": change_percent,
        "baseline_age_hours": round((target - baseline[0]).total_seconds() / 3600, 3),
        "reason": None if current else "no_current_observation",
    }


def window_label_fa(hours: object) -> str:
    if not isinstance(hours, (str, bytes, bytearray, int, float, Decimal)):
        return "نامشخص"
    try:
        value = int(hours)
    except (TypeError, ValueError, OverflowError):
        return "نامشخص"
    if value % 24 == 0:
        days = value // 24
        return f"{days} روز"
    return f"{value} ساعت"
