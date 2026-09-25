"""Deterministic, source-grounded attribution of market factors.

This module intentionally describes evidence and directional association.  It
does not claim that a factor caused a price move and never assigns a fake
numeric contribution to a news item.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from .researcher_adapter import MarketEvidence


MODEL_REVISION = "bee-cfo-factors-1"
_UP = ("افزایش", "رشد", "صعود", "تقویت", "بالا", "مثبت", "rise", "increase", "bullish", "up")
_DOWN = ("کاهش", "افت", "نزول", "تضعیف", "پایین", "منفی", "fall", "decrease", "bearish", "down")
_FLAT = ("ثبات", "خنثی", "بدون تغییر", "stable", "flat", "unchanged")

_TAXONOMY: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("global_benchmark", "شاخص مرجع جهانی", ("اونس", "طلا", "gold", "bitcoin", "btc", "بیت کوین", "شاخص جهانی", "benchmark")),
    ("rates_liquidity", "نرخ بهره و نقدینگی", ("نرخ بهره", "بازده", "yield", "interest", "cpi", "تورم", "inflation", "بانک مرکزی", "liquidity")),
    ("fx_local_premium", "ارز و پریمیوم داخلی", ("دلار", "usd", "ارز", "exchange", "نرخ ارز", "حباب", "premium", "spread")),
    ("flow_positioning", "جریان نقدینگی و موقعیت‌ها", ("حجم", "volume", "etf", "funding", "open interest", "ورود پول", "خروج پول", "flow")),
    ("policy_regulation", "سیاست، مقررات و ریسک سیاسی", ("تحریم", "sanction", "مقررات", "regulation", "سیاست", "جنگ", "تنش", "geopolit", "policy")),
)


def _timestamp(item: MarketEvidence) -> datetime:
    value = item.published_at or item.discovered_at
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _has_marker(text: str, marker: str) -> bool:
    """Match a word/phrase without treating a Persian substring as a signal."""
    return re.search(rf"(?<!\w){re.escape(marker.casefold())}(?!\w)", text.casefold()) is not None


def _direction(text: str) -> str:
    lowered = text.casefold()
    up = any(_has_marker(lowered, marker) for marker in _UP)
    down = any(_has_marker(lowered, marker) for marker in _DOWN)
    if up and down:
        return "unknown"
    if up:
        return "up"
    if down:
        return "down"
    if any(_has_marker(lowered, marker) for marker in _FLAT):
        return "flat"
    return "unknown"


def _factor_for(item: MarketEvidence) -> tuple[str, str]:
    text = f"{item.title} {item.text}".casefold()
    for key, label, markers in _TAXONOMY:
        if any(marker.casefold() in text for marker in markers):
            return key, label
    if item.source_authority.casefold() == "news":
        return "media_outlook", "چشم‌انداز رسانه‌ای"
    return "market_context", "زمینه عمومی بازار"


def _snippet(item: MarketEvidence) -> str:
    text = " ".join((item.text or item.title or "").split())
    if not text:
        return ""
    markers = [marker for _, _, values in _TAXONOMY for marker in values] + list(_UP) + list(_DOWN) + list(_FLAT)
    positions = [text.casefold().find(marker.casefold()) for marker in markers if text.casefold().find(marker.casefold()) >= 0]
    start = max(0, (min(positions) if positions else 0) - 85)
    snippet = text[start:start + 260].strip(" -:؛")
    return snippet[:260].rstrip() + ("…" if len(snippet) > 260 else "")


def _strength(score: float, *, conflict: bool) -> str:
    if conflict or score < 0.48:
        return "weak"
    if score < 0.72:
        return "medium"
    return "strong"


def build_factor_attributions(evidence: Iterable[MarketEvidence]) -> dict[str, object]:
    """Build explainable factor cards from extracted evidence.

    Direction is emitted only when explicit language supports it.  Conflicting
    source directions become ``unknown`` rather than an averaged causal claim.
    """
    grouped: dict[str, list[MarketEvidence]] = {}
    for item in evidence:
        if not (item.title.strip() or item.text.strip()) or item.extraction_status in {"failed", "partial", "fallback"}:
            continue
        key, _ = _factor_for(item)
        grouped.setdefault(key, []).append(item)
    factors: list[dict[str, object]] = []
    for factor_key, items in grouped.items():
        label = next((label for key, label, _ in _TAXONOMY if key == factor_key), {
            "media_outlook": "چشم‌انداز رسانه‌ای",
            "market_context": "زمینه عمومی بازار",
        }.get(factor_key, factor_key))
        directions = {_direction(f"{item.title} {item.text}") for item in items}
        explicit_directions = {value for value in directions if value != "unknown"}
        conflict = len(explicit_directions) > 1
        direction = "unknown" if conflict or not explicit_directions else next(iter(explicit_directions))
        source_keys = sorted({item.source_key for item in items})
        score = min(0.95, max(0.05, sum(max(0.0, min(1.0, item.quality_score)) for item in items) / len(items) + min(0.2, (len(source_keys) - 1) * 0.08)))
        if conflict:
            score *= 0.65
        kind = "media_statement" if factor_key == "media_outlook" else ("explicit_driver" if any(re.search(r"دلیل|سبب|در پی|because|due to|because of", item.text, re.I) for item in items) else "co_movement")
        evidence_cards = [
            {
                "source_key": item.source_key,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "snippet": _snippet(item),
                "published_at": _timestamp(item).isoformat() if item.published_at or item.discovered_at else None,
                "quality_score": round(float(item.quality_score), 4),
            }
            for item in sorted(items, key=_timestamp, reverse=True)[:4]
        ]
        factors.append({
            "factor_key": factor_key,
            "category": factor_key,
            "label": label,
            "direction": direction,
            "strength": _strength(score, conflict=conflict),
            "score": round(score, 4),
            "confidence": round(min(0.92, score * (0.75 if conflict else 0.95)), 4),
            "evidence_count": len(items),
            "source_keys": source_keys,
            "evidence": evidence_cards,
            "horizon": "کوتاه‌مدت؛ تا ۷ روز" if factor_key != "rates_liquidity" else "میان‌مدت؛ چند هفته تا چند ماه",
            "invalidation": "داده معتبر تازه یا شواهد چندمنبعی خلاف این جهت منتشر شود",
            "attribution_kind": kind,
            "conflict": conflict,
        })
    def factor_sort_key(item: dict[str, object]) -> tuple[float, str]:
        score = item.get("score")
        numeric_score = float(score) if isinstance(score, (int, float)) else 0.0
        return (-numeric_score, str(item.get("factor_key", "")))

    factors.sort(key=factor_sort_key)
    status = "available" if factors else "no_call"
    limitations = [
        "این کارت‌ها نسبت‌دادن شواهد و هم‌حرکتی هستند، نه اثبات رابطه علّی یا سهم عددی هر عامل.",
        "اختلاف جهت منابع به‌صورت نامشخص حفظ می‌شود و به سیگنال صعودی/نزولی تبدیل نمی‌شود.",
    ]
    if not factors:
        limitations.insert(0, "برای نسبت‌دادن عامل، شاهد استخراج‌شده و قابل استفاده در دسترس نبود.")
    return {
        "model_revision": MODEL_REVISION,
        "status": status,
        "quality_status": "good" if factors else "no_call",
        "factors": factors,
        "top_factors": factors[:3],
        "limitations": limitations,
    }
