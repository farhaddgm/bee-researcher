from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Awaitable, Callable
from urllib.parse import urljoin

import httpx

from app.config import Settings
from app.fetchers import (
    FetchFailure,
    SourceFetcher,
    SourceSpec,
    TRANSIENT_STATUS_CODES,
    normalize_item_url,
    resolve_public_destination,
    validate_public_url_syntax,
)


SKIP_TAGS = {"script", "style", "noscript", "svg", "form", "nav", "footer", "aside"}
TEXT_TAGS = {"p", "h1", "h2", "h3", "li", "blockquote"}
ARTICLE_TYPES = {"article", "newsarticle", "reportagenewsarticle"}


def _clean(value: str | None) -> str:
    return " ".join(html.unescape(value or "").split()).strip()


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ArticleDocument:
    url: str
    canonical_url: str
    title: str
    author: str | None
    published_at: datetime | None
    language: str
    text: str
    raw_html: str | None
    extraction_status: str
    extraction_method: str
    quality_score: float
    content_hash: str | None
    image_url: str | None = None
    provenance: dict[str, object] = field(default_factory=dict)
    error: str | None = None


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.article_depth = 0
        self.main_depth = 0
        self.capture_tag: str | None = None
        self.capture_depth = 0
        self.capture_text: list[str] = []
        self.article_blocks: list[str] = []
        self.main_blocks: list[str] = []
        self.all_blocks: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical_url: str | None = None
        self.html_language = "fa"
        self.json_ld_depth = 0
        self.json_ld_parts: list[str] = []
        self.json_ld_documents: list[object] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "html" and values.get("lang"):
            self.html_language = values["lang"].split("-", 1)[0].lower()
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = _clean(values.get("content"))
            if key and content:
                self.meta.setdefault(key, content)
        if tag == "link" and "canonical" in values.get("rel", "").lower():
            self.canonical_url = values.get("href") or self.canonical_url
        if tag == "script" and "ld+json" in values.get("type", "").lower():
            self.json_ld_depth = 1
            self.json_ld_parts = []
            return
        if self.json_ld_depth:
            self.json_ld_depth += 1
            return
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "article":
            self.article_depth += 1
        if tag == "main" or values.get("role", "").lower() == "main":
            self.main_depth += 1
        if tag in TEXT_TAGS and self.capture_tag is None:
            self.capture_tag = tag
            self.capture_depth = 1
            self.capture_text = []
        elif self.capture_tag is not None:
            self.capture_depth += 1

    def handle_data(self, data: str) -> None:
        if self.json_ld_depth:
            self.json_ld_parts.append(data)
        elif not self.skip_depth and self.capture_tag is not None:
            self.capture_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.json_ld_depth:
            self.json_ld_depth -= 1
            if self.json_ld_depth == 0:
                raw = "".join(self.json_ld_parts).strip()
                try:
                    self.json_ld_documents.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass
                self.json_ld_parts = []
            return
        if self.skip_depth:
            if tag in SKIP_TAGS:
                self.skip_depth -= 1
            return
        if self.capture_tag is not None:
            self.capture_depth -= 1
            if self.capture_depth == 0:
                block = _clean(" ".join(self.capture_text))
                if len(block) >= 20:
                    self.all_blocks.append(block)
                    if self.main_depth:
                        self.main_blocks.append(block)
                    if self.article_depth:
                        self.article_blocks.append(block)
                self.capture_tag = None
                self.capture_text = []
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
        if tag == "main" and self.main_depth:
            self.main_depth -= 1


def _walk_json_ld(value: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(value, dict):
        found.append(value)
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                found.extend(_walk_json_ld(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_json_ld(item))
    return found


def _json_ld_article(parser: _ArticleParser) -> dict[str, object]:
    for document in parser.json_ld_documents:
        for item in _walk_json_ld(document):
            item_type = item.get("@type")
            types = {item_type.lower()} if isinstance(item_type, str) else {
                str(value).lower() for value in item_type or []
            }
            if types & ARTICLE_TYPES:
                return item
    return {}


def _article_image_url(parser: _ArticleParser, article_json: dict[str, object], response_url: str) -> str | None:
    """Resolve a public hero image from standard metadata without fetching it."""
    candidate: object = parser.meta.get("og:image") or parser.meta.get("twitter:image")
    if not candidate:
        candidate = article_json.get("image")
    if isinstance(candidate, dict):
        candidate = candidate.get("url") or candidate.get("contentUrl")
    elif isinstance(candidate, list):
        candidate = candidate[0] if candidate else None
        if isinstance(candidate, dict):
            candidate = candidate.get("url") or candidate.get("contentUrl")
    value = str(candidate or "").strip()
    if not value:
        return None
    resolved = urljoin(response_url, value)
    try:
        validate_public_url_syntax(resolved)
    except ValueError:
        return None
    return normalize_item_url(resolved)


def extract_article_document(
    content: bytes,
    response_url: str,
    *,
    fallback_title: str,
    fallback_published_at: datetime | None,
    settings: Settings,
) -> ArticleDocument:
    decoded = content.decode("utf-8", errors="replace")
    parser = _ArticleParser()
    parser.feed(decoded)
    article_json = _json_ld_article(parser)
    blocks = parser.article_blocks or parser.main_blocks or parser.all_blocks
    unique_blocks = list(dict.fromkeys(blocks))
    normalized_text = "\n\n".join(unique_blocks)
    truncated = len(normalized_text) > settings.extraction_max_chars
    normalized_text = normalized_text[: settings.extraction_max_chars].strip()
    canonical_candidate = (
        parser.canonical_url
        or str(article_json.get("url") or article_json.get("mainEntityOfPage") or "")
        or response_url
    )
    if isinstance(article_json.get("mainEntityOfPage"), dict):
        canonical_candidate = str(
            article_json["mainEntityOfPage"].get("@id") or response_url
        )
    canonical_url = normalize_item_url(urljoin(response_url, canonical_candidate))
    try:
        validate_public_url_syntax(canonical_url)
    except ValueError:
        canonical_url = normalize_item_url(response_url)
    author_value: object = article_json.get("author")
    if isinstance(author_value, dict):
        author_value = author_value.get("name")
    elif isinstance(author_value, list):
        author_value = "، ".join(
            str(item.get("name") if isinstance(item, dict) else item)
            for item in author_value
        )
    author = _clean(
        str(
            author_value
            or parser.meta.get("author")
            or parser.meta.get("article:author")
            or ""
        )
    ) or None
    title = _clean(
        str(
            article_json.get("headline")
            or parser.meta.get("og:title")
            or parser.meta.get("twitter:title")
            or fallback_title
        )
    )
    published_at = (
        _parse_datetime(article_json.get("datePublished"))
        or _parse_datetime(parser.meta.get("article:published_time"))
        or fallback_published_at
    )
    image_url = _article_image_url(parser, article_json, response_url)
    length_score = min(len(normalized_text) / 2500, 1.0)
    structural_bonus = 0.15 if parser.article_blocks else 0.08 if parser.main_blocks else 0
    quality_score = round(min(length_score * 0.85 + structural_bonus, 1.0), 4)
    if not normalized_text:
        status = "failed"
        error = "no article body text could be extracted"
    elif len(normalized_text) < settings.extraction_min_complete_chars or truncated:
        status = "partial"
        error = "text is short or truncated and must be labeled incomplete"
    else:
        status = "complete"
        error = None
    content_hash = (
        hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        if normalized_text
        else None
    )
    return ArticleDocument(
        url=normalize_item_url(response_url),
        canonical_url=canonical_url,
        title=title or fallback_title,
        author=author,
        published_at=published_at,
        language=parser.html_language or "fa",
        text=normalized_text,
        raw_html=decoded[: settings.fetch_max_bytes] if settings.store_raw_html else None,
        extraction_status=status,
        extraction_method=(
            "article_html" if parser.article_blocks else "main_html" if parser.main_blocks else "page_html"
        ),
        quality_score=quality_score,
        content_hash=content_hash,
        image_url=image_url,
        provenance={
            "response_url": normalize_item_url(response_url),
            "canonical_url": canonical_url,
            "body_blocks": len(unique_blocks),
            "text_chars": len(normalized_text),
            "truncated": truncated,
            "json_ld_article": bool(article_json),
            **({"image_url": image_url} if image_url else {}),
        },
        error=error,
    )


class ArticleFetcher:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Callable[[str], Awaitable[None]] = resolve_public_destination,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.resolver = resolver
        self.sleeper = sleeper

    async def fetch(
        self,
        *,
        url: str,
        source_key: str,
        source_name: str,
        fallback_title: str,
        fallback_published_at: datetime | None,
        robots_policy: str = "respect",
        max_retries: int = 2,
    ) -> ArticleDocument:
        source = SourceSpec(
            source_key=source_key,
            name=source_name,
            homepage_url=url,
            fetch_url=url,
            adapter="html",
            robots_policy=robots_policy,
            request_timeout_seconds=self.settings.fetch_timeout_seconds,
            max_retries=max_retries,
        )
        helper = SourceFetcher(
            self.settings,
            transport=self.transport,
            resolver=self.resolver,
            sleeper=self.sleeper,
        )
        timeout = self.settings.fetch_timeout_seconds
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            headers={"User-Agent": self.settings.fetch_user_agent},
            transport=self.transport,
        ) as client:
            allowed, robots_status = await helper._robots_allowed(client, source)
            if not allowed:
                return ArticleDocument(
                    url=url,
                    canonical_url=url,
                    title=fallback_title,
                    author=None,
                    published_at=fallback_published_at,
                    language="fa",
                    text="",
                    raw_html=None,
                    extraction_status="blocked",
                    extraction_method="robots",
                    quality_score=0,
                    content_hash=None,
                    provenance={"robots_status": robots_status},
                    error="robots.txt denied the article URL",
                )
            attempts = max_retries + 1
            for attempt in range(1, attempts + 1):
                try:
                    response = await helper._request(client, url)
                    if response.status_code in TRANSIENT_STATUS_CODES and attempt < attempts:
                        await self.sleeper(min(2 ** (attempt - 1), 4))
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and not any(
                        value in content_type for value in ("html", "xhtml", "text/plain")
                    ):
                        raise FetchFailure(
                            f"unsupported article content type: {content_type}",
                            status_code=response.status_code,
                            attempts=attempt,
                        )
                    if len(response.content) > self.settings.fetch_max_bytes:
                        raise FetchFailure(
                            "article response exceeds the byte limit",
                            status_code=response.status_code,
                            attempts=attempt,
                        )
                    document = extract_article_document(
                        response.content,
                        str(response.url),
                        fallback_title=fallback_title,
                        fallback_published_at=fallback_published_at,
                        settings=self.settings,
                    )
                    provenance = dict(document.provenance)
                    provenance.update(
                        {
                            "robots_status": robots_status,
                            "status_code": response.status_code,
                            "attempts": attempt,
                        }
                    )
                    return ArticleDocument(
                        url=document.url,
                        canonical_url=document.canonical_url,
                        title=document.title,
                        author=document.author,
                        published_at=document.published_at,
                        language=document.language,
                        text=document.text,
                        raw_html=document.raw_html,
                        extraction_status=document.extraction_status,
                        extraction_method=document.extraction_method,
                        quality_score=document.quality_score,
                        content_hash=document.content_hash,
                        image_url=document.image_url,
                        provenance=provenance,
                        error=document.error,
                    )
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    if attempt < attempts:
                        await self.sleeper(min(2 ** (attempt - 1), 4))
                        continue
                    raise FetchFailure(
                        f"article request failed: {type(exc).__name__}: {exc}",
                        attempts=attempt,
                    ) from exc
                except httpx.HTTPStatusError as exc:
                    raise FetchFailure(
                        f"HTTP {exc.response.status_code} from article",
                        status_code=exc.response.status_code,
                        attempts=attempt,
                    ) from exc
        raise FetchFailure("article extraction exhausted retries", attempts=attempts)
