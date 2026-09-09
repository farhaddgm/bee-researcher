"""Deterministic benchmark capabilities owned by Bee CFO.

The module intentionally contains no Researcher imports.  It turns the
evidence already collected through the read-only adapter into auditable
cards, novelty/coverage signals, event-ledger records and calibration inputs.
External calendars and comparison feeds can be plugged into these contracts
without changing the reporting boundary.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .researcher_adapter import MarketEvidence


INDICATOR_SYNONYMS: dict[str, dict[str, tuple[str, ...]]] = {
    "GOLD_18K": {
        "fa": ("طلای ۱۸ عیار", "هر گرم طلای ۱۸ عیار", "گرم ۱۸", "geram18", "18k gold"),
        "en": ("18k gold", "gold gram", "gold bullion", "XAU", "gold"),
    },
    "USD_FREE": {
        "fa": ("دلار آزاد", "دلار آمریکا", "نرخ دلار", "دلار نقدی"),
        "en": ("free market usd", "usd/irr", "us dollar", "dollar rate"),
    },
    "BTC_USDT": {
        "fa": ("بیت‌کوین", "بیت کوین", "BTC", "بیت کوین تتر"),
        "en": ("bitcoin", "BTC", "BTC/USDT", "bitcoin price"),
    },
}

BENCHMARK_PLAYBOOK: tuple[dict[str, object], ...] = (
    {
        "product": "Quartr Pro",
        "source_url": "https://quartr.com/products/quartr-pro",
        "pattern": "traceable outputs, history comparison, alerts",
        "bee_cfo_control": "evidence_cards + report_diff + open_checks",
    },
    {
        "product": "Dataminr AI Platform",
        "source_url": "https://www.dataminr.com/ai-platform/",
        "pattern": "early warnings, corroboration and continuously updated briefs",
        "bee_cfo_control": "candidate/corroborated/suppressed alert maturity",
    },
    {
        "product": "RavenPack",
        "source_url": "https://www.ravenpack.com/products/edge/factors/company-news",
        "pattern": "factorized news analytics",
        "bee_cfo_control": "factor_attributions + confidence_budget",
    },
    {
        "product": "TradingView",
        "source_url": "https://www.tradingview.com/support/solutions/43000691889-learn-to-trade-on-historical-data/",
        "pattern": "historical replay",
        "bee_cfo_control": "point-in-time replay with no look-ahead",
    },
    {
        "product": "Koyfin",
        "source_url": "https://www.koyfin.com/features/alerts/",
        "pattern": "user-configurable alerts",
        "bee_cfo_control": "owner rules + idempotent delivery ledger",
    },
    {
        "product": "AlphaSense",
        "source_url": "https://www.alpha-sense.com/solutions/market-intelligence-platform/",
        "pattern": "market intelligence search and source-grounded analysis",
        "bee_cfo_control": "source links, coverage gaps and source independence",
    },
)


def benchmark_playbook() -> list[dict[str, object]]:
    return [dict(item) for item in BENCHMARK_PLAYBOOK]

_EVENT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("central_bank", ("فدرال رزرو", "بانک مرکزی", "central bank", "fed", "rate decision", "نرخ بهره")),
    ("inflation", ("تورم", "cpi", "inflation", "شاخص قیمت مصرف کننده")),
    ("employment", ("اشتغال", "employment", "payroll", "بیکاری", "unemployment")),
    ("etf_flow", ("etf", "صندوق طلا", "ورود سرمایه", "خروج سرمایه", "fund flow")),
    ("geopolitics", ("جنگ", "تنش", "تحریم", "geopolit", "conflict", "sanction")),
)


def expand_indicator_terms(indicator_key: str, *, language: str = "fa") -> list[str]:
    key = str(indicator_key or "").upper()
    lang = "en" if str(language).lower() == "en" else "fa"
    values = INDICATOR_SYNONYMS.get(key, {}).get(lang, ())
    cross_language = INDICATOR_SYNONYMS.get(key, {}).get("en" if lang == "fa" else "fa", ())
    return list(dict.fromkeys([*values, *cross_language]))


def _compact(value: object, limit: int = 600) -> str:
    result = " ".join(str(value or "").split()).strip()
    return result[:limit].rstrip() + ("…" if len(result) > limit else "")


def _canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if not key.lower().startswith(("utm_", "fbclid"))]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))
    except ValueError:
        return value.strip()


def evidence_fingerprint(item: MarketEvidence) -> str:
    raw = "|".join((_canonical_url(item.source_url), _compact(item.title, 240).casefold(), _compact(item.text, 420).casefold()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _sentence_snippet(text: str, *, markers: Iterable[str] = ()) -> str:
    clean = _compact(text, 1400)
    sentences = [part.strip(" -:؛") for part in re.split(r"(?<=[.!؟])\s+|\n+", clean) if part.strip()]
    marker_values = tuple(str(item).casefold() for item in markers)
    for sentence in sentences:
        if not marker_values or any(marker in sentence.casefold() for marker in marker_values):
            return _compact(sentence, 320)
    return _compact(sentences[0] if sentences else clean, 320)


def build_evidence_cards(evidence: list[MarketEvidence], clusters: list[list[MarketEvidence]]) -> list[dict[str, object]]:
    """Create one auditable card per retained source item."""
    cluster_by_fp: dict[str, int] = {}
    for index, cluster in enumerate(clusters):
        for item in cluster:
            cluster_by_fp[evidence_fingerprint(item)] = index
    cards: list[dict[str, object]] = []
    for item in evidence[:40]:
        source_items = [member for member in clusters[cluster_by_fp.get(evidence_fingerprint(item), -1)]] if cluster_by_fp.get(evidence_fingerprint(item), -1) >= 0 else [item]
        cards.append({
            "evidence_id": evidence_fingerprint(item),
            "source_key": item.source_key,
            "source_name": item.source_name,
            "source_url": item.source_url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "snippet": _sentence_snippet(item.text or item.title),
            "evidence_kind": "article" if item.source_authority == "news" else "market_observation",
            "source_independence": len({member.source_key for member in source_items}),
            "cluster_size": len(source_items),
            "quality_score": round(float(item.quality_score), 4),
            "extraction_status": item.extraction_status,
        })
    return cards


def compute_novelty_metrics(evidence: list[MarketEvidence], clusters: list[list[MarketEvidence]], *, previous_ids: set[str] | None = None) -> dict[str, object]:
    total = len(evidence)
    unique_events = len(clusters)
    duplicate_count = max(0, total - unique_events)
    ids = {evidence_fingerprint(item) for item in evidence}
    previous = previous_ids or set()
    new_count = len(ids - previous) if previous else unique_events
    independent_sources = len({item.source_key for item in evidence})
    return {
        "evidence_count": total,
        "unique_event_count": unique_events,
        "new_event_count": new_count,
        "duplicate_count": duplicate_count,
        "duplicate_ratio": round(duplicate_count / total, 4) if total else 0.0,
        "independent_source_count": independent_sources,
        "novelty_score": round(new_count / max(1, unique_events), 4),
        "fingerprints": sorted(ids)[:100],
    }


def build_media_pulse(perspectives: list[Mapping[str, object]], novelty: Mapping[str, object]) -> dict[str, object]:
    explicit = [item for item in perspectives if item.get("evidence_type") == "explicit_opinion"]
    counts = Counter(str(item.get("stance") or "unknown") for item in explicit)
    if counts.get("up", 0) and counts.get("down", 0):
        direction = "mixed"
    elif counts.get("up", 0):
        direction = "up"
    elif counts.get("down", 0):
        direction = "down"
    elif counts.get("flat", 0):
        direction = "flat"
    else:
        direction = "unknown"
    return {
        "coverage_volume": len(perspectives),
        "explicit_opinion_count": len(explicit),
        "independent_media_count": len({str(item.get("source_key")) for item in explicit}),
        "stance_counts": dict(counts),
        "direction": direction,
        "novelty_score": novelty.get("novelty_score", 0),
        "is_causal_claim": False,
        "interpretation": "خلاصه‌ی توصیفیِ مواضع رسانه‌هاست و علت‌ومعلول بازار محسوب نمی‌شود.",
    }


def compute_coverage_score(*, quote: bool, source_health: float, freshness: float, media_opinion: bool, benchmark: bool, forecast: bool) -> dict[str, object]:
    components = {
        "quote": 0.25 if quote else 0.0,
        "source_health": 0.20 * max(0.0, min(1.0, source_health)),
        "freshness": 0.15 * max(0.0, min(1.0, freshness)),
        "media_opinion": 0.15 if media_opinion else 0.0,
        "benchmark": 0.10 if benchmark else 0.0,
        "forecast": 0.15 if forecast else 0.0,
    }
    missing = [key for key, value in (("quote", quote), ("source_health", source_health > 0), ("freshness", freshness > 0), ("media_opinion", media_opinion), ("benchmark", benchmark), ("forecast", forecast)) if not value]
    score = round(sum(components.values()), 4)
    return {"score": score, "status": "complete" if score >= 0.8 and not missing else "partial" if score >= 0.45 else "insufficient", "components": components, "missing": missing, "publishable": score >= 0.45}


def model_agreement(price_forecast: Mapping[str, object]) -> dict[str, object]:
    if price_forecast.get("status") != "available":
        return {"status": "no_call", "label": "داده/مدل کافی نیست", "agreement": None, "methods": []}
    rows = price_forecast.get("forecasts") if isinstance(price_forecast.get("forecasts"), list) else []
    directions: list[str] = []
    methods: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        probs = {"up": float(row.get("probability_up", 0)), "down": float(row.get("probability_down", 0)), "flat": float(row.get("probability_flat", 0))}
        directions.append(max(probs, key=probs.get))
        methods.append(str(row.get("method") or "unknown"))
    unique = set(directions)
    agreement = len(unique) <= 1 if directions else None
    return {"status": "agreement" if agreement else "disagreement", "label": "هم‌جهت" if agreement else "اختلاف مدل/افق", "agreement": agreement, "directions": directions, "methods": list(dict.fromkeys(methods)), "baseline_floor": True, "confidence_reduction": not bool(agreement)}


def relative_benchmark_contract(indicator_key: str) -> dict[str, object]:
    key = str(indicator_key or "").upper()
    pairs = {
        "GOLD_18K": ["XAU_USD", "USD_FREE"],
        "USD_FREE": ["USD_REFERENCE"],
        "BTC_USDT": ["BTC_GLOBAL_REFERENCE"],
    }
    return {"indicator_key": key, "comparators": pairs.get(key, []), "status": "contract_ready", "spread": None, "note": "مقایسه تا تأیید و دریافت منبع benchmark مالک انجام نمی‌شود."}


def extract_event_ledger(evidence: list[MarketEvidence], *, watch_key: str, as_of: datetime) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in evidence[:50]:
        text = f"{item.title} {item.text}".casefold()
        event_type = next((kind for kind, markers in _EVENT_MARKERS if any(marker.casefold() in text for marker in markers)), None)
        if event_type is None:
            continue
        event_key = evidence_fingerprint(item)
        rows.append({
            "event_key": event_key,
            "watch_key": watch_key,
            "event_type": event_type,
            "title": _compact(item.title, 240),
            "source_keys": [item.source_key],
            "source_urls": [item.source_url],
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "expected": None,
            "actual": None,
            "previous": None,
            "novelty_score": 1.0,
            "status": "observed",
            "metadata": {"as_of": as_of.isoformat(), "extraction_status": item.extraction_status},
        })
    return rows


def evaluate_media_outcome(*, expected_stance: str, actual_direction: str | None, probability: float | None = None) -> dict[str, object]:
    expected = str(expected_stance or "unknown").lower()
    actual = str(actual_direction or "").lower()
    if expected not in {"up", "down", "flat"} or actual not in {"up", "down", "flat"}:
        return {"outcome": "not_evaluable", "direction_hit": None, "brier_score": None}
    p = max(0.0, min(1.0, float(probability))) if probability is not None else (1.0 if expected == actual else 0.0)
    return {"outcome": "hit" if expected == actual else "miss", "direction_hit": expected == actual, "brier_score": round((p - (1.0 if actual == expected else 0.0)) ** 2, 6)}


def source_scorecard(rows: list[Mapping[str, object]], *, minimum_sample: int = 20) -> dict[str, object]:
    minimum = max(1, int(minimum_sample))
    if len(rows) < minimum:
        return {"status": "insufficient_sample", "sample_size": len(rows), "minimum_sample": minimum, "direction_hit_rate": None, "brier_score": None, "calibration": None}
    hits = [row.get("direction_hit") for row in rows if isinstance(row.get("direction_hit"), bool)]
    briers = [float(row["brier_score"]) for row in rows if row.get("brier_score") is not None]
    return {"status": "available", "sample_size": len(rows), "minimum_sample": minimum, "direction_hit_rate": round(sum(hits) / len(hits), 4) if hits else None, "brier_score": round(sum(briers) / len(briers), 4) if briers else None, "calibration": "review_required"}


def default_alert_rules() -> list[dict[str, object]]:
    return [
        {"rule_key": "price_change_pct", "kind": "price_change_pct", "threshold": 2.0, "status": "draft", "config": {"window_minutes": 60}},
        {"rule_key": "volatility_jump", "kind": "volatility_jump", "threshold": 1.5, "status": "draft", "config": {"window_minutes": 60}},
        {"rule_key": "media_stance_shift", "kind": "media_stance_shift", "threshold": 1.0, "status": "draft", "config": {}},
        {"rule_key": "stale_quote", "kind": "stale_quote", "threshold": 1.0, "status": "draft", "config": {"max_age_minutes": 180}},
        {"rule_key": "source_failover", "kind": "source_failover", "threshold": 1.0, "status": "draft", "config": {}},
    ]


def evaluate_alert_rule(rule: Mapping[str, object], *, current: Mapping[str, object], previous: Mapping[str, object] | None = None) -> dict[str, object] | None:
    """Evaluate only explicit active rules; return an explainable candidate."""
    if str(rule.get("status") or "draft") != "active":
        return None
    kind = str(rule.get("kind") or "")
    threshold = float(rule.get("threshold") or 0)
    if kind == "price_change_pct":
        value = abs(float(current.get("price_change_percent") or 0))
        if value < threshold:
            return None
        explanation = f"تغییر قیمت در پنجره‌ی پایش از آستانه‌ی {threshold:g}٪ عبور کرد ({value:.2f}٪)."
    elif kind == "volatility_jump":
        value = float(current.get("volatility_ratio") or 0)
        if value < threshold:
            return None
        explanation = f"نسبت نوسان به {value:.2f} رسید و از آستانه‌ی {threshold:g} عبور کرد."
    elif kind == "media_stance_shift":
        before = ((previous or {}).get("media_pulse") or {}).get("direction")
        after = (current.get("media_pulse") or {}).get("direction")
        if not before or not after or before == after:
            return None
        explanation = f"جهت توصیفی مواضع رسانه‌ها از {before} به {after} تغییر کرد؛ این هشدار علت بازار را ادعا نمی‌کند."
    elif kind == "stale_quote":
        missing = set((current.get("coverage_score") or {}).get("missing") or [])
        if "quote" not in missing:
            return None
        explanation = "قیمت معتبر یا تازه در این نوبت در دسترس نیست؛ گزارش باید با برچسب ناقص منتشر شود."
    elif kind == "source_failover":
        missing = set((current.get("coverage_score") or {}).get("missing") or [])
        if "source_health" not in missing:
            return None
        explanation = "سلامت منبع اصلی کافی نیست؛ مسیر failover یا تأیید منبع جایگزین لازم است."
    else:
        return None
    return {"kind": kind, "rule_key": str(rule.get("rule_key") or kind), "severity": "important" if kind in {"price_change_pct", "volatility_jump"} else "watch", "explanation": explanation, "delta": {"rule": dict(rule), "current": dict(current)}}
