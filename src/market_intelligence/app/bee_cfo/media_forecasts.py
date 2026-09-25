from __future__ import annotations

"""Article-level media forecasts for Bee CFO.

This module deliberately treats a published statement as the unit of analysis,
not a media outlet.  A single outlet can therefore have multiple statements,
different horizons, or an internal conflict without losing evidence.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import math
import re
from typing import Mapping, Sequence

from .researcher_adapter import MarketEvidence


HORIZON_LABELS = {
    "24h": "تا ۲۴ ساعت",
    "48h": "تا ۴۸ ساعت",
    "3_7d": "۳ تا ۷ روز",
    "8_30d": "۸ تا ۳۰ روز",
    "30d_plus": "بیش از ۳۰ روز",
    "unspecified": "بدون افق مشخص",
}
HORIZON_ORDER = ("24h", "48h", "3_7d", "8_30d", "30d_plus", "unspecified")
HORIZON_DAYS = {"24h": 1, "48h": 2, "3_7d": 7, "8_30d": 30, "30d_plus": 90, "unspecified": None}
HORIZON_EXPIRY_HOURS = {"24h": 72, "48h": 96, "3_7d": 14 * 24, "8_30d": 45 * 24, "30d_plus": 120 * 24, "unspecified": 72}
_DEFAULT_COMPONENT_WEIGHTS: dict[str, float] = {
    "source": 0.20,
    "analyst": 0.15,
    "article_quality": 0.20,
    "independence": 0.20,
    "horizon_fit": 0.10,
    "recency": 0.15,
}

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_OUTLOOK_MARKERS = (
    "پیش‌بینی", "پیش بینی", "چشم‌انداز", "چشم انداز", "انتظار می‌رود",
    "انتظار می رود", "احتمال دارد", "خواهد شد", "می‌رود", "می رود",
    "outlook", "forecast", "expect", "will ", "likely", "target",
)
_ASSET_MARKERS = (
    # A generic word such as "price" is deliberately not an asset marker.
    # It made unrelated forecasts (for example, corn prices) look relevant to
    # a gold watch simply because they contained both "forecast" and "price".
    "gold", "bullion", "precious metal", "طلا", "طلای", "اونس", "xau", "18k", "۱۸ عیار",
    "bitcoin", "btc", "بیت کوین", "بیت‌کوین", "دلار", "usd", "dollar",
)
_UP_MARKERS = ("صعود", "افزایش", "رشد", "تقویت", "بالا می‌رود", "بالا می رود", "bullish", "rise", "increase", "rally", "higher", "upside", "advance", "rebound", "supported", "support", "gain")
_DOWN_MARKERS = ("نزول", "کاهش", "افت", "تضعیف", "پایین می‌رود", "پایین می رود", "bearish", "fall", "decrease", "lower", "downside", "decline", "drop", "slide", "retreat")
_FLAT_MARKERS = ("ثبات", "خنثی", "بدون تغییر", "stable", "flat", "unchanged", "range-bound")
_BOILERPLATE_MARKERS = (
    "copyright business recorder", "most read", "related stories", "latest news",
    "sc order on pti",
)


def default_media_weighting() -> dict[str, object]:
    return {
        "component_weights": dict(_DEFAULT_COMPONENT_WEIGHTS),
        "source_priors": {},
        "analyst_priors": {},
        "minimum_independent_sources": 1,
        "minimum_sample": 20,
        "expiry_hours": dict(HORIZON_EXPIRY_HOURS),
        "revision": "bee-cfo-media-weights-1",
    }


def normalize_media_weighting(value: object) -> dict[str, object]:
    base = default_media_weighting()
    if not isinstance(value, Mapping):
        return base
    raw_components = value.get("component_weights")
    if isinstance(raw_components, Mapping):
        components: dict[str, float] = {}
        for key, default in _DEFAULT_COMPONENT_WEIGHTS.items():
            number = _number(raw_components.get(key, default))
            components[key] = max(0.0, min(1.0, number)) if number is not None else default
        total = sum(components.values())
        if total > 0:
            base["component_weights"] = {key: round(value / total, 6) for key, value in components.items()}
    for field in ("source_priors", "analyst_priors"):
        raw = value.get(field)
        if isinstance(raw, Mapping):
            base[field] = {
                str(key)[:120]: _bounded_prior(item)
                for key, item in raw.items()
                if str(key).strip()
                and _is_number(item)
            }
    minimum_sources = _integer(value.get("minimum_independent_sources", 1))
    if minimum_sources is not None:
        base["minimum_independent_sources"] = max(1, min(10, minimum_sources))
    minimum_sample = _integer(value.get("minimum_sample", 20))
    if minimum_sample is not None:
        base["minimum_sample"] = max(20, min(500, minimum_sample))
    raw_expiry = value.get("expiry_hours")
    if isinstance(raw_expiry, Mapping):
        expiry_policy: dict[str, int] = dict(HORIZON_EXPIRY_HOURS)
        for key in HORIZON_ORDER:
            hours = _integer(raw_expiry.get(key, expiry_policy[key]))
            if hours is not None:
                expiry_policy[key] = max(24, min(24 * 365, hours))
        base["expiry_hours"] = expiry_policy
    base["revision"] = str(value.get("revision") or base["revision"])[:64]
    return base


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError, InvalidOperation):
        return None
    return result if math.isfinite(result) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _is_number(value: object) -> bool:
    return _number(value) is not None


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _timestamp(item: MarketEvidence) -> datetime:
    value = item.published_at or item.discovered_at
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_digits(value: str) -> str:
    return value.translate(_PERSIAN_DIGITS).casefold()


def parse_horizon(text: str) -> dict[str, object]:
    """Map only explicit time language to a discrete display bucket."""
    raw = _clean(text)
    normalized = _normalize_digits(raw)
    patterns = (
        ("48h", r"(?:48\s*(?:h|hours?|ساعت)|two\s+days?|دو\s+روز|۴۸\s*ساعت|تا\s+دو\s+روز)"),
        ("24h", r"(?:24\s*(?:h|hours?|ساعت)|one\s+day|یک\s+روز|فردا|tomorrow)"),
        ("3_7d", r"(?:3\s*(?:-|تا)\s*7\s*(?:days?|روز)|7\s*(?:days?|روز)|one\s+week|next\s+week|یک\s+هفته|هفته\s+آینده)"),
        ("30d_plus", r"(?:more\s+than\s+30\s*(?:days?|روز)|بیش\s+از\s*30\s*(?:days?|روز)|long[- ]?term|months?|years?|بلندمدت|ماه‌ها|ماه ها|سال(?:‌ها|ها)?)"),
        ("8_30d", r"(?:8\s*(?:-|تا)\s*30\s*(?:days?|روز)|two\s+weeks?|14\s*(?:days?|روز)|one\s+month|30\s*(?:days?|روز)|دو\s+هفته|یک\s+ماه|ماه\s+آینده)"),
    )
    for key, pattern in patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return {
                "horizon_key": key,
                "horizon_label": HORIZON_LABELS[key],
                "horizon_days": HORIZON_DAYS[key],
                "horizon_explicit": True,
                "horizon_confidence": 0.95,
                "horizon_text": raw[:100] or HORIZON_LABELS[key],
            }
    return {
        "horizon_key": "unspecified",
        "horizon_label": HORIZON_LABELS["unspecified"],
        "horizon_days": None,
        "horizon_explicit": False,
        "horizon_confidence": 0.0,
        "horizon_text": "نامشخص",
    }


def _contains_asset_marker(text: str) -> bool:
    lowered = _normalize_digits(text)
    return any(marker.casefold() in lowered for marker in _ASSET_MARKERS)


def _asset_context_direction_score(text: str, markers: tuple[str, ...]) -> int:
    """Count direction terms only when they are locally about the asset.

    A statement such as ``Gold remains supported by lower Treasury yields`` is
    bullish for gold.  The earlier keyword counter treated the word ``lower``
    (which describes yields) as a bearish gold call.  Limiting each directional
    word to a small window containing a specific asset avoids that inversion.
    """
    lowered = _normalize_digits(text)
    score = 0
    for marker in markers:
        needle = marker.casefold()
        position = lowered.find(needle)
        while position >= 0:
            start = max(0, position - 42)
            end = min(len(lowered), position + len(needle) + 42)
            if _contains_asset_marker(lowered[start:end]):
                score += 1
            position = lowered.find(needle, position + len(needle))
    return score


def classify_media_statement(text: str) -> str:
    """Return a conservative direction for one explicit, asset-specific view."""
    if not _contains_asset_marker(text):
        return "unknown"
    scores = {
        "up": _asset_context_direction_score(text, _UP_MARKERS),
        "down": _asset_context_direction_score(text, _DOWN_MARKERS),
        "flat": _asset_context_direction_score(text, _FLAT_MARKERS),
    }
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ordered or ordered[0][1] == 0 or (len(ordered) > 1 and ordered[0][1] == ordered[1][1]):
        return "unknown"
    return ordered[0][0]


def _stance(text: str) -> str:
    return classify_media_statement(text)


def _article_text(item: MarketEvidence) -> str:
    text = _clean(item.text)
    lowered = text.casefold()
    positions = [lowered.find(marker) for marker in _BOILERPLATE_MARKERS if lowered.find(marker) > 120]
    return text[:min(positions)].strip() if positions else text


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!؟])\s+|\n+", text) if part.strip()]


def _digest(*parts: object, length: int = 64) -> str:
    payload = "|".join(_clean(part).casefold() for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def extract_media_forecasts(evidence: list[MarketEvidence]) -> list[dict[str, object]]:
    """Extract all explicit statements; never collapse by source."""
    rows: list[dict[str, object]] = []
    for item in evidence:
        if item.source_authority.casefold() != "news":
            continue
        article_id = _digest(item.source_key, item.source_url, item.title, length=64)
        author = _clean((item.provenance or {}).get("author")) or None
        text = _article_text(item)
        candidates = [
            sentence[:680]
            for sentence in _sentences(text)
            if any(marker.casefold() in sentence.casefold() for marker in _OUTLOOK_MARKERS)
            and _contains_asset_marker(sentence)
        ]
        valid = item.extraction_status not in {"partial", "failed", "fallback"} and item.quality_score >= 0.45
        if not valid:
            candidates = []
        if not candidates:
            rows.append(
                {
                    "forecast_id": _digest(article_id, "no-explicit-opinion"),
                    "article_id": article_id,
                    "statement_index": 0,
                    "source_key": item.source_key,
                    "source_name": item.source_name,
                    "source_url": item.source_url,
                    "analyst_name": author,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "view": "در متن استخراج‌شده، نظر صریحی درباره روند آتی بازار پیدا نشد.",
                    "snippet": None,
                    "stance": "unknown",
                    "horizon": "نامشخص",
                    "horizon_key": "unspecified",
                    "horizon_label": HORIZON_LABELS["unspecified"],
                    "horizon_days": None,
                    "horizon_explicit": False,
                    "horizon_confidence": 0.0,
                    "evidence_type": "no_explicit_opinion",
                    "confidence": 0.1,
                    "evidence_id": item.provenance.get("content_hash") if isinstance(item.provenance, dict) else None,
                    "status": "active",
                    "conflict_status": "clear",
                    "conflict_group": None,
                    "narrative_key": None,
                    "independence_weight": 1.0,
                }
            )
            continue
        for index, statement in enumerate(candidates):
            horizon = parse_horizon(statement)
            stance = _stance(statement)
            narrative_key = _digest(statement, stance, horizon["horizon_key"], length=24)
            rows.append(
                {
                    "forecast_id": _digest(article_id, index, statement, length=64),
                    "article_id": article_id,
                    "statement_index": index,
                    "source_key": item.source_key,
                    "source_name": item.source_name,
                    "source_url": item.source_url,
                    "analyst_name": author,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "view": statement,
                    "snippet": statement,
                    "stance": stance,
                    "horizon": horizon["horizon_text"],
                    "horizon_key": horizon["horizon_key"],
                    "horizon_label": horizon["horizon_label"],
                    "horizon_days": horizon["horizon_days"],
                    "horizon_explicit": horizon["horizon_explicit"],
                    "horizon_confidence": horizon["horizon_confidence"],
                    "evidence_type": "explicit_opinion" if stance != "unknown" else "no_explicit_opinion",
                    "confidence": round(min(0.95, 0.25 + item.quality_score * 0.6 + (0.1 if stance != "unknown" else 0)), 4),
                    "evidence_id": item.provenance.get("content_hash") if isinstance(item.provenance, dict) else None,
                    "status": "active",
                    "conflict_status": "clear",
                    "conflict_group": None,
                    "narrative_key": narrative_key,
                    "independence_weight": 1.0,
                }
            )
    _mark_syndication(rows)
    _mark_conflicts(rows)
    return sorted(rows, key=lambda row: (str(row.get("source_key")), str(row.get("article_id")), _integer(row.get("statement_index")) or 0))


def mark_media_expiry(
    rows: list[dict[str, object]],
    *,
    now: datetime,
    expiry_hours: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Mark stale or future-dated statements before they enter consensus.

    Expiry is deliberately horizon-specific.  A long-range published outlook
    can remain useful longer than a one-day call, while an article timestamp
    after the report's as-of time is never allowed to leak into the report.
    """
    policy = dict(HORIZON_EXPIRY_HOURS)
    if isinstance(expiry_hours, Mapping):
        for key in HORIZON_ORDER:
            configured_hours = _integer(expiry_hours.get(key, policy[key]))
            if configured_hours is not None:
                policy[key] = max(24, min(24 * 365, configured_hours))
    reference = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    for row in rows:
        if row.get("evidence_type") != "explicit_opinion":
            continue
        raw_timestamp = row.get("published_at")
        if not raw_timestamp:
            continue
        try:
            published = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            published = published.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        horizon_key = str(row.get("horizon_key") or "unspecified")
        expiry_at = published + timedelta(hours=policy.get(horizon_key, policy["unspecified"]))
        row["expires_at"] = expiry_at.isoformat()
        if published > reference.astimezone(timezone.utc):
            row["status"] = "expired"
            row["temporal_status"] = "future_dated"
        elif reference.astimezone(timezone.utc) >= expiry_at:
            row["status"] = "expired"
            row["temporal_status"] = "expired"
        else:
            row["temporal_status"] = "active"
    return rows


def _mark_syndication(rows: list[dict[str, object]]) -> None:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        key = row.get("narrative_key")
        if key and row.get("evidence_type") == "explicit_opinion":
            grouped[str(key)].append(row)
    for group in grouped.values():
        sources = sorted({str(row.get("source_key")) for row in group})
        if len(sources) <= 1:
            continue
        primary = sources[0]
        for row in group:
            if str(row.get("source_key")) != primary:
                row["independence_weight"] = 0.25
                row["status"] = "syndicated"


def _mark_conflicts(rows: list[dict[str, object]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row.get("evidence_type") == "explicit_opinion" and row.get("horizon_key") != "unspecified":
            # Conflict is a property of the media outlet, not of an internal
            # feed/topic identifier. This catches two articles from the same
            # outlet even when the researcher adapter assigned different keys.
            source_name = _clean(row.get("source_name"))
            source_identity = source_name.split("·", 1)[0].strip().casefold() or str(row.get("source_key"))
            grouped[(source_identity, str(row.get("horizon_key")))].append(row)
    for key, group in grouped.items():
        stances = {str(row.get("stance")) for row in group if row.get("stance") in {"up", "down", "flat"}}
        if len(stances) < 2:
            continue
        conflict_group = _digest("internal-conflict", *key, length=32)
        for row in group:
            if row.get("stance") in stances:
                row["conflict_status"] = "internal_conflict"
                row["conflict_group"] = conflict_group
                row["status"] = "conflicted"


def _recency_weight(published_at: object, *, now: datetime, horizon_days: int | None) -> float:
    if not published_at:
        return 0.5
    try:
        timestamp = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - timestamp.astimezone(timezone.utc)).total_seconds() / 3600)
    except (TypeError, ValueError):
        return 0.5
    half_life_hours = max(24.0, float(horizon_days or 7) * 48.0)
    return max(0.15, math.exp(-math.log(2) * age_hours / half_life_hours))


def build_media_consensus(
    rows: Sequence[Mapping[str, object]],
    *,
    weighting: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return transparent, horizon-specific descriptive media consensus."""
    config = normalize_media_weighting(weighting)
    now = now or datetime.now(timezone.utc)
    raw_components = config.get("component_weights")
    components: Mapping[str, object] = raw_components if isinstance(raw_components, Mapping) else {}
    raw_source_priors = config.get("source_priors")
    source_priors: Mapping[str, object] = raw_source_priors if isinstance(raw_source_priors, Mapping) else {}
    raw_analyst_priors = config.get("analyst_priors")
    analyst_priors: Mapping[str, object] = raw_analyst_priors if isinstance(raw_analyst_priors, Mapping) else {}
    explicit = [
        row for row in rows
        if row.get("evidence_type") == "explicit_opinion"
        and row.get("stance") in {"up", "down", "flat"}
        and row.get("status") not in {"expired"}
    ]
    buckets: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in explicit:
        buckets[str(row.get("horizon_key") or "unspecified")].append(row)
    result: list[dict[str, object]] = []
    for horizon_key in HORIZON_ORDER:
        bucket = buckets.get(horizon_key, [])
        if not bucket:
            continue
        source_horizon_groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
        for row in bucket:
            source_horizon_groups[(str(row.get("source_key")), horizon_key)].append(row)
        weighted: dict[str, float] = {"up": 0.0, "down": 0.0, "flat": 0.0}
        weighted_rows: list[dict[str, object]] = []
        for row in bucket:
            source = str(row.get("source_key") or "")
            analyst = str(row.get("analyst_name") or "")
            source_prior = _bounded_prior(source_priors.get(source, 1.0))
            analyst_prior = _bounded_prior(analyst_priors.get(analyst, 1.0) if analyst else 1.0)
            article_quality = _bounded_rate(row.get("confidence") or 0.5, default=0.5, low=0.15, high=1.0)
            independence = _bounded_rate(row.get("independence_weight") or 1.0, default=1.0, low=0.1, high=1.0)
            horizon_fit = 1.0 if row.get("horizon_explicit") else 0.5
            recency = _recency_weight(row.get("published_at"), now=now, horizon_days=HORIZON_DAYS.get(horizon_key))
            values = {
                "source": source_prior,
                "analyst": analyst_prior,
                "article_quality": article_quality,
                "independence": independence,
                "horizon_fit": horizon_fit,
                "recency": recency,
            }
            weight = sum(
                (_number(components.get(key)) or 0.0) * component_value
                for key, component_value in values.items()
            )
            group_size = len(source_horizon_groups[(source, horizon_key)])
            if row.get("conflict_status") == "internal_conflict":
                weight *= 0.75 / max(1, group_size)
            weight = round(max(0.01, weight), 6)
            weighted[str(row["stance"])] += weight
            weighted_rows.append({"forecast_id": row.get("forecast_id"), "weight": weight, "components": values})
        total = sum(weighted.values())
        probabilities = {key: round(value / total, 6) for key, value in weighted.items()} if total else {key: 0.0 for key in weighted}
        ordered = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        top = ordered[0] if ordered else ("unknown", 0.0)
        second = ordered[1][1] if len(ordered) > 1 else 0.0
        independent_sources = len({
            str(row.get("source_key"))
            for row in bucket
            if _bounded_rate(row.get("independence_weight") or 1, default=1.0, low=0.1, high=1.0) >= 0.75
        })
        conflict_count = len({str(row.get("conflict_group")) for row in bucket if row.get("conflict_group")})
        margin = round(top[1] - second, 6)
        minimum_sources = _integer(config.get("minimum_independent_sources")) or 1
        if not total or independent_sources < minimum_sources:
            direction = "no_call"
        elif margin < 0.15 or conflict_count:
            direction = "mixed"
        else:
            direction = top[0]
        result.append(
            {
                "horizon_key": horizon_key,
                "horizon_label": HORIZON_LABELS[horizon_key],
                "horizon_days": HORIZON_DAYS[horizon_key],
                "direction": direction,
                "direction_score": round(probabilities["up"] - probabilities["down"], 6),
                "probabilities": probabilities,
                "coverage_count": len(bucket),
                "independent_source_count": independent_sources,
                "analyst_count": len({str(row.get("analyst_name")) for row in bucket if row.get("analyst_name")}),
                "conflict_group_count": conflict_count,
                "disagreement": margin < 0.15 or bool(conflict_count),
                "confidence": round(min(1.0, top[1] * min(1.0, independent_sources / 3)), 6),
                "weighted_rows": weighted_rows,
            }
        )
    unknown_count = len([row for row in rows if row.get("evidence_type") == "no_explicit_opinion"])
    return {
        "buckets": result,
        "unknown_opinion_count": unknown_count,
        "explicit_forecast_count": len(explicit),
        "conflict_count": len({str(row.get("conflict_group")) for row in rows if row.get("conflict_group")}),
        "weighting_revision": config["revision"],
        "interpretation": "اجماع توصیفیِ پیش‌بینی‌های منتشرشده است، نه پیش‌بینی قطعی قیمت یا توصیه سرمایه‌گذاری.",
    }


def _bounded_prior(value: object) -> float:
    number = _number(value)
    return max(0.1, min(2.0, number)) if number is not None else 1.0


def _bounded_rate(value: object, *, default: float, low: float, high: float) -> float:
    number = _number(value)
    return max(low, min(high, number)) if number is not None else default


def build_media_history(
    current_rows: Sequence[Mapping[str, object]],
    previous_states: list[Mapping[str, object]] | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    history: dict[str, list[dict[str, object]]] = defaultdict(list)
    states = list(previous_states or []) + [{"media_perspectives": current_rows}]
    for state in states:
        items = state.get("media_perspectives") if isinstance(state, Mapping) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping) or not item.get("source_key"):
                continue
            if now is not None and item.get("published_at"):
                try:
                    published = datetime.fromisoformat(str(item["published_at"]).replace("Z", "+00:00"))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    if published > now.astimezone(timezone.utc):
                        continue
                except (TypeError, ValueError):
                    pass
            history[str(item["source_key"])].append(
                {
                    "forecast_id": item.get("forecast_id"),
                    "source_key": item.get("source_key"),
                    "source_name": item.get("source_name"),
                    "stance": item.get("stance", "unknown"),
                    "horizon_key": item.get("horizon_key", "unspecified"),
                    "horizon_label": item.get("horizon_label") or item.get("horizon", "نامشخص"),
                    "published_at": item.get("published_at"),
                    "source_url": item.get("source_url"),
                }
            )
    result: list[dict[str, object]] = []
    for source_key, items in sorted(history.items()):
        items.sort(key=lambda item: str(item.get("published_at") or ""))
        compact: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in reversed(items):
            key = str(item.get("forecast_id") or _digest(item.get("source_url"), item.get("published_at"), item.get("stance"), item.get("horizon_key")))
            if key in seen:
                continue
            seen.add(key)
            compact.append(item)
            if len(compact) >= 5:
                break
        compact.reverse()
        stances = [str(item.get("stance")) for item in compact if item.get("stance") in {"up", "down", "flat"}]
        transition = f"{stances[-2]} → {stances[-1]}" if len(stances) >= 2 and stances[-2] != stances[-1] else None
        result.append(
            {
                "source_key": source_key,
                "source_name": compact[-1].get("source_name") if compact else source_key,
                "latest_stance": compact[-1].get("stance") if compact else "unknown",
                "latest_horizon_key": compact[-1].get("horizon_key") if compact else "unspecified",
                "transition": transition,
                "items": compact,
            }
        )
    return result[:50]
