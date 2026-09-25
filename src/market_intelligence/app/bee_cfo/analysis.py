from __future__ import annotations

import re
from datetime import datetime, timezone

from app.config import Settings
from app.openai_client import OpenAIClient

from .contracts import MarketReport, validate_market_report
from .benchmarking import evidence_fingerprint
from .media_forecasts import extract_media_forecasts
from .researcher_adapter import MarketEvidence


def _citation(evidence: MarketEvidence) -> dict[str, object]:
    claim = evidence.title.strip() or "صفحه بررسی‌شده"
    return {
        "source_key": evidence.source_key,
        "source_name": evidence.source_name,
        "source_url": evidence.source_url,
        "source_authority": evidence.source_authority,
        "source_origin": evidence.source_origin,
        "published_at": evidence.published_at.isoformat() if evidence.published_at else None,
        "claim": claim,
        "evidence_id": evidence_fingerprint(evidence),
        "evidence_kind": "article" if evidence.source_authority == "news" else "market_observation",
        "snippet": " ".join((evidence.text or evidence.title).split())[:320],
    }


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_PRICE_SIGNAL_MARKERS = (
    "قیمت",
    "نرخ",
    "فروش",
    "خرید",
    "آخرین",
    "درصد",
    "تغییر",
    "رشد",
    "افت",
    "بازده",
    "price",
    "rate",
    "change",
    "return",
)
_LOW_QUALITY_EXTRACTION = {"partial", "failed", "fallback"}
_MEDIA_AUTHORITIES = {"news"}
_MEDIA_OUTLOOK_MARKERS = (
    "پیش‌بینی",
    "پیش بینی",
    "چشم‌انداز",
    "چشم انداز",
    "انتظار می‌رود",
    "انتظار می رود",
    "احتمال دارد",
    "خواهد شد",
    "می‌رود",
    "می رود",
    "outlook",
    "forecast",
    "expect",
    "will ",
    "likely",
)
_MEDIA_ASSET_MARKERS = (
    "gold",
    "bullion",
    "metal",
    "metals",
    "طلا",
    "طلای",
    "اونس",
    "قیمت",
)
_MEDIA_UP_MARKERS = ("صعود", "افزایش", "رشد", "تقویت", "بالا می‌رود", "بالا می رود", "bullish", "rise", "increase", "rally", "higher", "upside", "advance")
_MEDIA_DOWN_MARKERS = ("نزول", "کاهش", "افت", "تضعیف", "پایین می‌رود", "پایین می رود", "bearish", "fall", "decrease", "lower", "downside", "decline", "drop", "slide", "retreat")
_MEDIA_FLAT_MARKERS = ("ثبات", "خنثی", "بدون تغییر", "stable", "flat", "unchanged")
_MEDIA_BOILERPLATE_MARKERS = (
    "copyright business recorder",
    "most read",
    "related stories",
    "latest news",
    "sc order on pti",
)


def _has_quantitative_signal(item: MarketEvidence) -> bool:
    """Accept only evidence that can support a market statement.

    Dynamic pages often return a navigation shell with titles such as
    ``طلای ۱۸ عیار``.  Those titles are useful for relevance filtering, but
    they are not market observations.  A complete, reasonably scored article
    with a number and a nearby price/change marker is the minimum signal for a
    directional claim.
    """
    text = (item.text or "").translate(_PERSIAN_DIGITS)
    if item.extraction_status in _LOW_QUALITY_EXTRACTION or item.quality_score < 0.45:
        return False
    if not text.strip():
        return False
    has_number = bool(re.search(r"\d[\d,.%]*", text))
    has_marker = any(marker in text.lower() for marker in _PRICE_SIGNAL_MARKERS)
    return has_number and has_marker


def _usable_evidence(evidence: list[MarketEvidence]) -> list[MarketEvidence]:
    return [item for item in evidence if _has_quantitative_signal(item)]


def _dedupe_labels(items: list[str], *, limit: int = 4) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in items:
        label = " ".join(str(value or "").split()).strip()
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            result.append(label)
        if len(result) >= limit:
            break
    return result


def _signal_summary(item: MarketEvidence) -> str:
    """Extract a short grounded observation without inventing direction."""
    text = " ".join((item.text or "").split())
    for marker in _PRICE_SIGNAL_MARKERS:
        match = re.search(rf"([^.!؟\n]{{0,70}}{re.escape(marker)}[^.!؟\n]{{0,100}})", text, flags=re.IGNORECASE)
        if match:
            snippet = " ".join(match.group(1).split()).strip(" -:؛")
            if snippet:
                return snippet[:180].rstrip() + ("…" if len(snippet) > 180 else "")
    return item.title.strip() or "شاهد بازار"


def _media_stance(text: str) -> str:
    lowered = text.casefold()
    up_score = sum(lowered.count(marker.casefold()) for marker in _MEDIA_UP_MARKERS)
    down_score = sum(lowered.count(marker.casefold()) for marker in _MEDIA_DOWN_MARKERS)
    flat_score = sum(lowered.count(marker.casefold()) for marker in _MEDIA_FLAT_MARKERS)
    if up_score and down_score and up_score == down_score:
        return "unknown"
    if up_score > max(down_score, flat_score):
        return "up"
    if down_score > max(up_score, flat_score):
        return "down"
    if flat_score > max(up_score, down_score):
        return "flat"
    return "unknown"


def _media_horizon(text: str) -> str:
    match = re.search(r"(?:در|تا|طی|for|over|within)\s+[^.!؟\n]{0,50}(?:روز|هفته|ماه|day|week|month)s?", text, flags=re.IGNORECASE)
    if match:
        return " ".join(match.group(0).split())[:80]
    return "نامشخص"


def _evidence_timestamp(item: MarketEvidence) -> datetime:
    value = item.published_at or item.discovered_at
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _legacy_media_perspectives(evidence: list[MarketEvidence]) -> list[dict[str, object]]:
    """Extract each news source's stated forward-looking view.

    This deliberately does not infer a media opinion from a price observation.
    If a news article does not explicitly discuss the future trend, the output
    says so rather than converting the article into a synthetic forecast.
    """
    media = [item for item in evidence if item.source_authority.casefold() in _MEDIA_AUTHORITIES]
    by_source: dict[str, MarketEvidence] = {}
    for item in media:
        current = by_source.get(item.source_key)
        if current is None or _evidence_timestamp(item) > _evidence_timestamp(current):
            by_source[item.source_key] = item
    result: list[dict[str, object]] = []
    for item in by_source.values():
        text = " ".join((item.text or "").split())
        lowered_text = text.casefold()
        boilerplate_positions = [
            lowered_text.find(marker)
            for marker in _MEDIA_BOILERPLATE_MARKERS
            if lowered_text.find(marker) > 120
        ]
        if boilerplate_positions:
            text = text[:min(boilerplate_positions)].strip()
        sentences = [part.strip() for part in re.split(r"(?<=[.!؟])\s+|\n+", text) if part.strip()]
        outlook = next(
            (
                sentence[:680]
                for sentence in sentences
                if any(marker.casefold() in sentence.casefold() for marker in _MEDIA_OUTLOOK_MARKERS)
                and any(marker.casefold() in sentence.casefold() for marker in _MEDIA_ASSET_MARKERS)
            ),
            None,
        )
        explicit = bool(outlook) and item.extraction_status not in _LOW_QUALITY_EXTRACTION and item.quality_score >= 0.45
        view = outlook if explicit else "در متن استخراج‌شده، نظر صریحی درباره روند آتی بازار پیدا نشد."
        result.append(
            {
                "source_key": item.source_key,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "view": view,
                "snippet": outlook if explicit else None,
                "stance": _media_stance(outlook or "") if explicit else "unknown",
                "horizon": _media_horizon(outlook or "") if explicit else "نامشخص",
                "horizon_days": 2 if explicit and re.search(r"۴۸|48|دو روز|two days", outlook or "", re.I) else 7 if explicit and re.search(r"هفته|week|۷ روز|7 day", outlook or "", re.I) else None,
                "evidence_type": "explicit_opinion" if explicit else "no_explicit_opinion",
                "confidence": round(min(0.9, 0.25 + item.quality_score * 0.6), 4) if explicit else 0.1,
                "evidence_id": evidence_fingerprint(item),
            }
        )
    return result[:12]


def _media_perspectives(evidence: list[MarketEvidence]) -> list[dict[str, object]]:
    """Use the article-level ledger; retain the legacy extractor only for archaeology."""
    return extract_media_forecasts(evidence)


def fallback_market_report(*, watch: dict[str, object], evidence: list[MarketEvidence]) -> MarketReport:
    """Return a safe report that distinguishes coverage from usable signal.

    The fallback is intentionally conservative.  A source URL or a relevant
    page title is disclosed as coverage, but it is not promoted to a market
    fact unless the extraction is complete and contains a quantitative signal.
    """
    raw_evidence = [item for item in evidence if item.title.strip() or item.text.strip()]
    usable = _usable_evidence(raw_evidence)
    source_count = len({item.source_key for item in raw_evidence})
    usable_source_count = len({item.source_key for item in usable})
    source_names = _dedupe_labels([item.source_name for item in raw_evidence], limit=4)
    media_perspectives = _media_perspectives(raw_evidence)
    market_name = str(watch.get("name", watch.get("watch_key", "بازار")))
    if usable:
        facts = _dedupe_labels([_signal_summary(item) for item in usable], limit=3)
        summary = (
            f"برای {market_name}، {len(usable)} شاهد قابل اتکا از "
            f"{usable_source_count} منبع در پنجره تازگی ثبت شد. "
            "این جمع‌بندی فقط بر داده‌ی استخراج‌شده تکیه دارد و جهت بازار را قطعی نمی‌کند."
        )
        trends = ["سیگنال کمی در متن منابع ثبت شده؛ جهت نهایی فقط با تداوم همین سیگنال و تأیید چندمنبعی معتبر است"]
        drivers = [f"داده‌ی قابل استفاده از: {', '.join(_dedupe_labels([item.source_name for item in usable], limit=3))}"]
        risks = ["هم‌جهتی و تداوم سیگنال‌ها هنوز باید در نوبت‌های بعدی تأیید شود"]
        base_probability, upside_probability, downside_probability = 0.50, 0.30, 0.20
        scenario_evidence = facts[:3]
        confidence = 0.30 + min(0.35, usable_source_count * 0.12 + len(usable) * 0.03)
    else:
        facts = []
        summary = (
            f"برای {market_name}، {len(raw_evidence)} صفحه مرتبط از {source_count} منبع بررسی شد، "
            "اما هیچ شاهد قابل اتکای قابل استفاده برای قیمت یا درصد تغییر ثبت نشد. "
            "بنابراین در این نوبت سیگنال جهت‌دار صادر نمی‌شود."
        )
        trends = ["جهت بازار از داده‌ی معتبر قابل تأیید نیست"]
        drivers = ["کیفیت استخراج صفحات برای تحلیل کمی کافی نیست"]
        risks = [
            "داده‌ی قیمت یا درصد تغییر معتبر در دسترس نیست",
            "تعداد صفحات مرتبط، بدون استخراج کامل، به‌تنهایی نشانه‌ی بازار نیست",
        ]
        base_probability, upside_probability, downside_probability = 0.60, 0.20, 0.20
        scenario_evidence = []
        confidence = 0.08 if raw_evidence else 0.03
    horizon = "کوتاه‌مدت؛ تا ۷ روز پس از زمان گزارش"
    if usable:
        scenarios = [
            {
                "key": "base",
                "title": "تداوم سیگنال فعلی",
                "probability": base_probability,
                "expected_change": "ادامه‌ی نوسان نزدیک به وضعیت فعلی تا تأیید سیگنال تازه",
                "triggers": ["تکرار سیگنال کمی در منابع معتبر", "هم‌جهتی حداقل دو منبع یا دو نوبت پایش"],
                "invalidation": "عدد یا خبر معتبر تازه، خلاف این مسیر را نشان دهد",
            },
            {
                "key": "upside",
                "title": "حرکت صعودی مشروط",
                "probability": upside_probability,
                "expected_change": "تقویت حرکت صعودی فقط در صورت استمرار داده‌ی مثبت و تأیید چندمنبعی",
                "triggers": ["افزایش معتبر قیمت/درصد تغییر در چند نوبت", "تأیید هم‌جهت از منبع مستقل"],
                "invalidation": "بازگشت عددها یا انتشار داده‌ی معتبر خلاف جهت",
            },
            {
                "key": "downside",
                "title": "حرکت نزولی مشروط",
                "probability": downside_probability,
                "expected_change": "افزایش فشار یا نوسان فقط در صورت تداوم داده‌ی منفی معتبر",
                "triggers": ["افت معتبر قیمت/درصد تغییر در چند نوبت", "تأیید هم‌جهت از منبع مستقل"],
                "invalidation": "تثبیت یا برگشت معتبر شاخص‌ها",
            },
        ]
    else:
        scenarios = [
            {
                "key": "base",
                "title": "بدون سیگنال جهت‌دار",
                "probability": base_probability,
                "expected_change": "تا تکمیل استخراج داده، مسیر قابل اتکایی برای بازار اعلام نمی‌شود",
                "triggers": ["تکمیل استخراج قیمت و درصد تغییر", "ثبت داده‌ی معتبر در نوبت بعدی"],
                "invalidation": "ورود داده‌ی کمی معتبر و قابل تکرار",
            },
            {
                "key": "upside",
                "title": "صعود مشروط به داده",
                "probability": upside_probability,
                "expected_change": "فقط با مشاهده‌ی رشد معتبر و تأییدشده، سناریوی صعودی فعال می‌شود",
                "triggers": ["رشد کمی در دو پایش یا دو منبع مستقل"],
                "invalidation": "نبود داده‌ی معتبر یا ثبت عدد خلاف جهت",
            },
            {
                "key": "downside",
                "title": "نزول مشروط به داده",
                "probability": downside_probability,
                "expected_change": "فقط با مشاهده‌ی افت معتبر و تأییدشده، سناریوی نزولی فعال می‌شود",
                "triggers": ["افت کمی در دو پایش یا دو منبع مستقل"],
                "invalidation": "نبود داده‌ی معتبر یا تثبیت شاخص‌ها",
            },
        ]
    common = {"horizon": horizon, "evidence": scenario_evidence}
    scenarios = [{**common, **scenario} for scenario in scenarios]
    payload = {
        "current_state": {
            "summary": summary,
            "facts": facts,
            "trends": trends,
            "drivers": drivers,
            "risks": risks,
            "raw_evidence_count": len(raw_evidence),
            "valid_evidence_count": len(usable),
            "source_count": source_count,
            "usable_source_count": usable_source_count,
            "quality_status": "good" if usable else "degraded",
            "media_perspectives": media_perspectives,
        },
        "scenarios": scenarios,
        "changes": [],
        "uncertainties": [
            "صفحات مرتبط ممکن است پوسته‌ی ناقص یا منوی سایت باشند؛ استخراج کامل باید در نوبت بعد کنترل شود",
            "سناریوها شرطی‌اند و تا ورود داده‌ی معتبر، پیش‌بینی قطعی محسوب نمی‌شوند",
        ],
        "citations": [_citation(item) for item in raw_evidence[:20]],
        "confidence": round(min(0.75, confidence), 4),
    }
    return validate_market_report(payload)


async def generate_market_report(
    *,
    settings: Settings,
    watch: dict[str, object],
    evidence: list[MarketEvidence],
    output_contract: dict[str, object],
) -> tuple[MarketReport, str, dict[str, int]]:
    """Use the approved model when available and retain a deterministic fallback."""
    client = OpenAIClient(settings)
    if not client.configured:
        return fallback_market_report(watch=watch, evidence=evidence), "deterministic-fallback", {"input_tokens": 0, "output_tokens": 0}
    # Do not let a language model turn a navigation shell or partial page into
    # a directional market claim.  A model is useful after the extraction
    # layer has produced at least one quantitative, auditable signal.
    if not _usable_evidence(evidence):
        return fallback_market_report(watch=watch, evidence=evidence), "deterministic-fallback-degraded-evidence", {"input_tokens": 0, "output_tokens": 0}
    try:
        result = await client.analyze_market(
            watch=watch,
            evidence=[item.prompt_payload() for item in evidence[:50]],
            output_contract=output_contract,
        )
        normalized = validate_market_report(result.payload)
        # Media forecasts are a deterministic, article-level evidence product.
        # Do not let a model collapse two articles from one outlet or infer a
        # stance that is not explicitly present in the source sentence.
        normalized["current_state"]["media_perspectives"] = _media_perspectives(evidence)
        return normalized, result.model, {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
    except Exception:
        # Model failures must not block ingestion or hide the report's
        # degraded state.  The caller records the fallback model explicitly.
        return fallback_market_report(watch=watch, evidence=evidence), "deterministic-fallback-after-model-error", {"input_tokens": 0, "output_tokens": 0}
