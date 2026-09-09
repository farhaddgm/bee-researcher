from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from app.article_extraction import ArticleFetcher
from app.config import Settings
from app.fetchers import (
    FetchFailure,
    SourceFetcher,
    SourceSpec,
    TRANSIENT_STATUS_CODES,
    resolve_public_destination,
    validate_public_url_syntax,
)
from .quote_control import build_provider_signature


_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d[\d\s,٬،٫.]*")
_TAG_RE = re.compile(r"<[^>]+>")
_PARSER_LABELS: dict[str, tuple[str, ...]] = {
    "gold_18k": (r"هر\s*گرم\s*طلای?\s*(?:۱۸|18)\s*عیار", r"طلای?\s*(?:۱۸|18)\s*عیار", r"geram18"),
    "usd_free": (r"دلار\s*(?:آمریکا|آزاد)?", r"price[_ -]?dollar[_ -]?rl", r"usd"),
    "btc_usdt": (r"بیت\s*کوین", r"bitcoin", r"\bbtc\b"),
}
_HTML_CURRENT_QUOTE_PATTERNS: dict[str, tuple[str, ...]] = {
    # TGJU profile pages expose the current quote through this field. Read it
    # before label-based parsing, which can otherwise select menu numbers.
    "gold_18k": (
        r'data-col\s*=\s*["\']info\.last_trade\.PDrCotVal["\'][^>]*>\s*([^<]+)',
    ),
    "usd_free": (
        r'data-col\s*=\s*["\']info\.last_trade\.PDrCotVal["\'][^>]*>\s*([^<]+)',
    ),
}
_SOURCE_UNIT_RE = re.compile(r"واحد\s*پولی\s*[:：]?\s*(ریال|تومان)", re.IGNORECASE)
_PRICE_UNITS = {"ریال", "تومان"}
MAX_REASONABLE_RELATIVE_PRICE_MOVE = 0.75


@dataclass(frozen=True, slots=True)
class PriceQuote:
    value: float
    observed_at: datetime
    source_url: str
    source_name: str
    source_key: str
    raw: dict[str, object]


def validate_quote_value(value: float, parser_key: str) -> float:
    """Reject navigation/schema numbers that are not plausible quotes."""
    minimums = {
        "gold_18k": 100_000.0,
        "usd_free": 1_000.0,
        "btc_usdt": 100.0,
    }
    minimum = minimums.get(parser_key, 0.0)
    if value < minimum:
        raise ValueError(f"quote is implausibly low for {parser_key}")
    return value


def _canonical_price_unit(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    aliases = {
        "ریال": "ریال",
        "rial": "ریال",
        "rials": "ریال",
        "irr": "ریال",
        "تومان": "تومان",
        "تومن": "تومان",
        "toman": "تومان",
        "tomans": "تومان",
    }
    return aliases.get(normalized)


def normalize_number(value: object) -> float | None:
    """Parse Persian/Arabic/English quote text without assuming a locale."""
    if value is None:
        return None
    text = str(value).translate(_DIGIT_TRANSLATION)
    text = text.replace("٬", ",").replace("،", ",").replace("٫", ".")
    text = re.sub(r"[^0-9+\-.,]", "", text)
    if not text:
        return None
    # A comma is a thousands separator in the product's Persian price feeds;
    # a lone decimal dot is preserved for API values such as BTC/USD.
    if text.count(".") > 1:
        text = text.replace(".", "")
    if "," in text:
        if "." in text:
            text = text.replace(",", "")
        else:
            chunks = text.split(",")
            text = "".join(chunks) if all(len(chunk) == 3 for chunk in chunks[1:]) else ".".join(chunks)
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number >= 0 else None


def _plain_text(value: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", value)).split())


def _numbers_after(text: str, offset: int, *, limit: int = 180) -> list[float]:
    values: list[float] = []
    for match in _NUMBER_RE.finditer(text[offset : offset + limit]):
        number = normalize_number(match.group(0))
        if number is not None:
            values.append(number)
    return values


def _structured_html_quote(text: str, parser_key: str) -> float | None:
    if "<" not in text or ">" not in text:
        return None
    for pattern in _HTML_CURRENT_QUOTE_PATTERNS.get(parser_key, ()):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = normalize_number(match.group(1))
            if value is not None:
                return value
    return None


def parse_price_text(text: str, parser_key: str) -> float | None:
    """Extract a quote only next to an explicit instrument label.

    This intentionally refuses to guess from an arbitrary first number. It is
    the final safety boundary before a price is stored or delivered.
    """
    structured = _structured_html_quote(text, parser_key)
    if structured is not None:
        return structured
    plain = _plain_text(text).translate(_DIGIT_TRANSLATION)
    patterns = _PARSER_LABELS.get(parser_key, ())
    for pattern in patterns:
        for match in re.finditer(pattern, plain, flags=re.IGNORECASE):
            candidates = _numbers_after(plain, match.end())
            if candidates:
                return max(candidates)
    return None


def normalize_quote_unit(
    value: float,
    *,
    body: str,
    target_unit: object,
    configured_source_unit: object = None,
) -> tuple[float, dict[str, object]]:
    """Normalize a source quote using an explicit owner-approved unit contract.

    A page-level unit is useful, but it is not sufficient for APIs whose JSON
    payload contains no unit at all.  Catalog sources may therefore declare
    ``configured_source_unit``; if both the source document and the catalog
    declare a unit, a conflict is rejected instead of silently guessing.
    """
    source_match = _SOURCE_UNIT_RE.search(_plain_text(body))
    detected_source_unit = _canonical_price_unit(source_match.group(1)) if source_match else None
    source_unit = _canonical_price_unit(configured_source_unit) or detected_source_unit
    configured = _canonical_price_unit(configured_source_unit)
    if configured and detected_source_unit and configured != detected_source_unit:
        raise ValueError(
            f"configured source unit {configured} conflicts with page unit {detected_source_unit}"
        )
    target = str(target_unit or "").strip()
    if source_unit == "ریال" and target == "تومان":
        return value / 10, {
            "source_unit": source_unit,
            "target_unit": target,
            "operation": "divide_by_10",
            "reason": "source_contract_declares_riyal" if configured else "source_page_declares_riyal",
        }
    if source_unit == "تومان" and target == "ریال":
        return value * 10, {
            "source_unit": source_unit,
            "target_unit": target,
            "operation": "multiply_by_10",
            "reason": "source_contract_declares_toman" if configured else "source_page_declares_toman",
        }
    return value, {
        "source_unit": source_unit,
        "target_unit": target,
        "operation": "none",
        "reason": "source_contract_matches_target" if configured else "no_explicit_unit_conversion_needed",
    }


def validate_quote_normalization(
    raw_value: float,
    normalized_value: float,
    conversion: Mapping[str, object],
    *,
    target_unit: object,
) -> float:
    """Enforce that a delivered fiat quote has an auditable unit conversion."""
    target = str(target_unit or "").strip()
    source = _canonical_price_unit(conversion.get("source_unit"))
    if target in _PRICE_UNITS and source is None:
        raise ValueError("fiat price source unit is not explicit; quote rejected")
    if raw_value <= 0 or normalized_value <= 0:
        raise ValueError("price quote must be positive")
    expected = raw_value
    if source == "ریال" and target == "تومان":
        expected = raw_value / 10
    elif source == "تومان" and target == "ریال":
        expected = raw_value * 10
    if abs(normalized_value - expected) > max(0.01, abs(expected) * 1e-9):
        raise ValueError("price quote normalization is inconsistent with its unit contract")
    return normalized_value


def validate_quote_delta(
    previous_value: float | None,
    current_value: float,
    *,
    max_relative_move: float = MAX_REASONABLE_RELATIVE_PRICE_MOVE,
) -> float:
    """Reject a likely tenfold unit error before it reaches Telegram."""
    if current_value <= 0:
        raise ValueError("current price quote must be positive")
    if previous_value in (None, 0):
        return 0.0
    relative_move = abs(current_value - previous_value) / abs(previous_value)
    if relative_move > max_relative_move:
        raise ValueError(
            f"price quote moved {relative_move:.2%} since the last trusted snapshot; delivery held for review"
        )
    return relative_move


def _json_path(payload: object, path: object) -> object:
    current = payload
    if not isinstance(path, list):
        return current
    for key in path:
        if isinstance(current, Mapping):
            current = current.get(str(key))
        elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
            current = current[key]
        else:
            return None
    return current


async def _fetch_json(
    *,
    source,
    settings: Settings,
) -> tuple[object, dict[str, object]]:
    validate_public_url_syntax(source.fetch_url)
    await resolve_public_destination(source.fetch_url)
    spec = SourceSpec(
        source_key=source.source_key,
        name=source.name,
        homepage_url=source.homepage_url,
        fetch_url=source.fetch_url,
        adapter="json",
        robots_policy="respect",
        request_timeout_seconds=settings.fetch_timeout_seconds,
        max_retries=2,
    )
    helper = SourceFetcher(settings)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.fetch_timeout_seconds),
        follow_redirects=False,
        headers={"User-Agent": settings.fetch_user_agent},
    ) as client:
        allowed, robots_status = await helper._robots_allowed(client, spec)
        if not allowed:
            raise FetchFailure("robots.txt denied the price URL")
        for attempt in range(1, 4):
            try:
                response = await helper._request(client, source.fetch_url)
                if response.status_code in TRANSIENT_STATUS_CODES and attempt < 3:
                    continue
                response.raise_for_status()
                if len(response.content) > settings.fetch_max_bytes:
                    raise FetchFailure("price response exceeds the byte limit")
                return response.json(), {"attempts": attempt, "robots_status": robots_status, "status_code": response.status_code}
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt == 3:
                    raise FetchFailure(f"price request failed: {type(exc).__name__}: {exc}") from exc
            except (httpx.HTTPStatusError, json.JSONDecodeError, ValueError) as exc:
                raise FetchFailure(f"invalid price response: {exc}") from exc
    raise FetchFailure("price source did not return a quote")


async def fetch_price_quote(*, indicator, source, settings: Settings) -> PriceQuote:
    """Fetch one owner-approved source through the shared public-fetch boundary."""
    observed_at = datetime.now(timezone.utc)
    if source.adapter == "json":
        payload, fetch_meta = await _fetch_json(source=source, settings=settings)
        parser = source.parser_json or {}
        source_value = normalize_number(_json_path(payload, parser.get("path")))
        if source_value is None:
            raise ValueError(f"JSON path did not contain a numeric quote for {indicator.indicator_key}")
        normalized_value, unit_conversion = normalize_quote_unit(
            source_value,
            body="",
            target_unit=indicator.quote_unit,
            configured_source_unit=parser.get("source_unit"),
        )
        validate_quote_normalization(
            source_value,
            normalized_value,
            unit_conversion,
            target_unit=indicator.quote_unit,
        )
        validate_quote_value(normalized_value, indicator.parser_key)
        value = normalized_value
        raw = {
            "adapter": "json",
            "path": parser.get("path"),
            "fetch": fetch_meta,
            "source_quote_value": source_value,
            "unit_conversion": unit_conversion,
            "provider_signature": build_provider_signature(
                adapter="json", payload=payload, parser=parser, parser_key=indicator.parser_key,
            ),
        }
    else:
        document = await ArticleFetcher(settings).fetch(
            url=source.fetch_url,
            source_key=source.source_key[:16],
            source_name=source.name,
            fallback_title=indicator.display_name,
            fallback_published_at=None,
            robots_policy="respect",
            max_retries=2,
        )
        if document.extraction_status not in {"complete", "partial"}:
            raise ValueError(document.error or "price source extraction failed")
        body = "\n".join(part for part in (document.text, document.raw_html or "") if part)
        source_value = parse_price_text(body, indicator.parser_key)
        if source_value is None:
            raise ValueError(f"no explicit {indicator.indicator_key} quote found in source")
        parser = source.parser_json or {}
        value, unit_conversion = normalize_quote_unit(
            source_value,
            body=body,
            target_unit=indicator.quote_unit,
            configured_source_unit=parser.get("source_unit"),
        )
        value = validate_quote_normalization(
            source_value,
            value,
            unit_conversion,
            target_unit=indicator.quote_unit,
        )
        validate_quote_value(value, indicator.parser_key)
        raw = {
            "adapter": "html",
            "extraction_status": document.extraction_status,
            "source_quote_value": source_value,
            "unit_conversion": unit_conversion,
            "provenance": document.provenance,
            "provider_signature": build_provider_signature(
                adapter="html",
                payload={"quote_extracted": True, "structured_quote": bool(_structured_html_quote(body, indicator.parser_key))},
                parser=parser,
                parser_key=indicator.parser_key,
                extraction_status=document.extraction_status,
            ),
        }
    return PriceQuote(
        value=value,
        observed_at=observed_at,
        source_url=source.fetch_url,
        source_name=source.name,
        source_key=source.source_key,
        raw=raw,
    )
