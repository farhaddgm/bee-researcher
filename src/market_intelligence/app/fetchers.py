from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import json
import re
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from app.config import Settings


TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
MAX_REDIRECTS = 5

# A connector credential is bound both to its adapter family and to the
# provider API hosts that legitimately consume it.  A source can therefore
# never make the server send a token to an arbitrary (attacker-chosen) host,
# directly or through a redirect.
_CREDENTIAL_REFS = {
    "telegram_source_bot_token": frozenset({"TELEGRAM_SOURCE_BOT_TOKEN", "MARKET_INTELLIGENCE_TELEGRAM_SOURCE_BOT_TOKEN"}),
    "instagram_source_access_token": frozenset({"INSTAGRAM_SOURCE_ACCESS_TOKEN", "MARKET_INTELLIGENCE_INSTAGRAM_SOURCE_ACCESS_TOKEN"}),
    "x_source_bearer_token": frozenset({"X_SOURCE_BEARER_TOKEN", "MARKET_INTELLIGENCE_X_SOURCE_BEARER_TOKEN"}),
}
CONNECTOR_CREDENTIALS: dict[str, tuple[str, frozenset[str]]] = {
    "telegram_private": ("telegram_source_bot_token", frozenset({"api.telegram.org"})),
    "instagram_public": ("instagram_source_access_token", frozenset({"graph.facebook.com", "graph.instagram.com"})),
    "instagram_private": ("instagram_source_access_token", frozenset({"graph.facebook.com", "graph.instagram.com"})),
    "x_public": ("x_source_bearer_token", frozenset({"api.x.com", "api.twitter.com"})),
    "x_private": ("x_source_bearer_token", frozenset({"api.x.com", "api.twitter.com"})),
}


def credential_hosts(adapter: str, settings: Settings) -> frozenset[str]:
    """Hosts allowed to receive the adapter's credential (provider + gateways)."""
    spec = CONNECTOR_CREDENTIALS.get(adapter)
    if spec is None:
        return frozenset()
    return spec[1] | settings.connector_gateway_host_values


def validate_connector_binding(adapter: str, credential_ref: str | None, fetch_url: str, settings: Settings) -> None:
    """Raise ValueError when a source configuration could leak a credential.

    Used by the admin API (to fail early with 422) and again at fetch time.
    """
    spec = CONNECTOR_CREDENTIALS.get(adapter)
    ref = (credential_ref or "").strip().upper()
    if spec is None:
        if ref:
            raise ValueError("this connector does not use a server credential")
        return
    if ref not in _CREDENTIAL_REFS[spec[0]]:
        raise ValueError("the credential reference does not belong to this connector")
    parsed = urlparse(fetch_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in credential_hosts(adapter, settings):
        raise ValueError("credentialed connectors may only call their provider API over HTTPS")


@dataclass(frozen=True, slots=True)
class SourceSpec:
    source_key: str
    name: str
    homepage_url: str
    fetch_url: str
    adapter: str
    access_policy: str = "public_only"
    credential_ref: str | None = None
    account_ref: str | None = None
    item_url_pattern: str | None = None
    item_title_class_pattern: str | None = None
    robots_policy: str = "respect"
    etag: str | None = None
    last_modified: str | None = None
    request_timeout_seconds: int = 20
    max_retries: int = 2


@dataclass(frozen=True, slots=True)
class DiscoveredItem:
    title: str
    url: str
    excerpt: str = ""
    published_at: datetime | None = None
    raw_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FetchResult:
    status: str
    items: tuple[DiscoveredItem, ...]
    attempts: int
    status_code: int | None
    response_url: str
    etag: str | None = None
    last_modified: str | None = None
    robots_status: str = "not_checked"


class FetchFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        attempts: int = 0,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts


def validate_public_url_syntax(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("source URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials in source URLs are not allowed")
    # Provider tokens in query strings are routinely copied into logs and
    # referrers. Require a server-side credential reference instead.
    sensitive_query = {"token", "access_token", "api_key", "apikey", "secret", "password", "auth", "signature"}
    query_keys = {part.split("=", 1)[0].lower() for part in parsed.query.split("&") if part}
    if query_keys & sensitive_query:
        raise ValueError("credentials in source URL query parameters are not allowed")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise ValueError("local source hosts are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url
    if not address.is_global:
        raise ValueError("private or non-global source addresses are not allowed")
    return url


async def resolve_public_destination(url: str) -> None:
    parsed = urlparse(validate_public_url_syntax(url))
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    loop = asyncio.get_running_loop()
    addresses = await loop.getaddrinfo(
        parsed.hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    if not addresses:
        raise ValueError("source host did not resolve")
    for address in {item[4][0] for item in addresses}:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("source host resolves to a private or non-global address")


def normalize_item_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            parsed.query,
            "",
        )
    )


def item_fingerprint(title: str, url: str) -> str:
    normalized_url = normalize_item_url(url)
    basis = normalized_url or " ".join(title.lower().split())
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _clean(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split()).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        name = child.tag.rsplit("}", 1)[-1].lower()
        if name in names and child.text:
            return child.text
    return ""


def _entry_url(entry: ET.Element, base_url: str) -> str:
    for child in entry.iter():
        if child.tag.rsplit("}", 1)[-1].lower() != "link":
            continue
        candidate = child.attrib.get("href") or (child.text or "")
        if candidate.strip():
            return urljoin(base_url, candidate.strip())
    guid = _child_text(entry, ("guid", "id"))
    return urljoin(base_url, guid.strip()) if guid else ""


def parse_feed(content: bytes, base_url: str, limit: int = 50) -> list[DiscoveredItem]:
    if b"<!DOCTYPE" in content[:4096].upper():
        raise ValueError("XML documents with a DOCTYPE are not accepted")
    try:
        root = SafeET.fromstring(
            content,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except DefusedXmlException as exc:
        raise ValueError("Unsafe XML document rejected") from exc
    entries = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}
    ]
    items: list[DiscoveredItem] = []
    for entry in entries[:limit]:
        title = _clean(_child_text(entry, ("title",)))
        url = _entry_url(entry, base_url)
        excerpt = _clean(
            _child_text(entry, ("description", "summary", "content", "encoded"))
        )[:2000]
        published_at = _parse_date(
            _child_text(entry, ("pubdate", "published", "updated", "date"))
        )
        try:
            validate_public_url_syntax(url)
        except ValueError:
            continue
        if title:
            items.append(
                DiscoveredItem(
                    title=title,
                    url=normalize_item_url(url),
                    excerpt=excerpt,
                    published_at=published_at,
                    raw_metadata={"adapter": "rss"},
                )
            )
    return items


def parse_json_feed(content: bytes, base_url: str, limit: int = 50) -> list[DiscoveredItem]:
    payload = json.loads(content)
    entries = payload.get("items", []) if isinstance(payload, dict) else []
    items: list[DiscoveredItem] = []
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            continue
        title = _clean(str(entry.get("title") or ""))
        candidate = entry.get("url") or entry.get("external_url") or entry.get("id")
        url = urljoin(base_url, str(candidate or "").strip())
        try:
            validate_public_url_syntax(url)
        except ValueError:
            continue
        if not title:
            continue
        excerpt = _clean(
            str(entry.get("summary") or entry.get("content_text") or "")
        )[:2000]
        items.append(
            DiscoveredItem(
                title=title,
                url=normalize_item_url(url),
                excerpt=excerpt,
                published_at=_parse_date(
                    str(entry.get("date_published") or entry.get("date_modified") or "")
                ),
                raw_metadata={"adapter": "json"},
            )
        )
    return items


def parse_social_json(content: bytes, base_url: str, adapter: str, limit: int = 50) -> list[DiscoveredItem]:
    """Normalize official Instagram/X (or an approved gateway) responses.

    The parser deliberately accepts only the small public fields needed by
    ingestion. It never stores the response wholesale, which prevents access
    tokens and provider metadata from leaking into SourceItem.raw_metadata.
    """
    payload = json.loads(content)
    entries: object = payload.get("data", payload.get("items", [])) if isinstance(payload, dict) else []
    # Meta's Business Discovery response nests public media under
    # ``business_discovery.media.data``.  Only that bounded list is promoted
    # to source items; the surrounding account/token metadata is discarded.
    if adapter.startswith("instagram") and isinstance(payload, dict):
        discovery = payload.get("business_discovery")
        if isinstance(discovery, dict):
            media = discovery.get("media")
            if isinstance(media, dict):
                entries = media.get("data", [])
    if not isinstance(entries, list):
        entries = []
    items: list[DiscoveredItem] = []
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            continue
        title = _clean(str(entry.get("caption") or entry.get("text") or entry.get("title") or ""))
        if not title:
            continue
        candidate = entry.get("permalink") or entry.get("url") or entry.get("external_url")
        if not candidate and entry.get("id"):
            candidate = urljoin(base_url, str(entry["id"]))
        url = urljoin(base_url, str(candidate or ""))
        try:
            validate_public_url_syntax(url)
        except ValueError:
            continue
        timestamp = entry.get("timestamp") or entry.get("created_at") or entry.get("date")
        items.append(DiscoveredItem(
            title=title[:500],
            url=normalize_item_url(url),
            excerpt=title[:2000],
            published_at=_parse_date(str(timestamp or "")),
            raw_metadata={"adapter": adapter, "provider_id": str(entry.get("id") or "")[:128]},
        ))
    return items


class _LinkParser(HTMLParser):
    def __init__(self, title_class_pattern: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.title_class_pattern = (
            re.compile(title_class_pattern) if title_class_pattern else None
        )
        self.article_depth = 0
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.current_heading_text: list[str] = []
        self.current_class_title_text: list[str] = []
        self.current_in_article = False
        self.heading_depth = 0
        self.class_title_depth = 0
        self.links: list[tuple[str, str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            self.article_depth += 1
        if tag == "a":
            values = dict(attrs)
            self.current_href = values.get("href")
            self.current_text = []
            self.current_heading_text = []
            self.current_class_title_text = []
            self.current_in_article = self.article_depth > 0
        elif self.current_href and self.class_title_depth:
            self.class_title_depth += 1
        elif self.current_href and self.title_class_pattern:
            class_value = dict(attrs).get("class") or ""
            if self.title_class_pattern.search(class_value):
                self.class_title_depth = 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.current_href:
            self.heading_depth += 1

    def handle_data(self, data: str) -> None:
        if self.current_href is not None:
            self.current_text.append(data)
            if self.heading_depth:
                self.current_heading_text.append(data)
            if self.class_title_depth:
                self.current_class_title_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_href is not None:
            self.links.append(
                (
                    self.current_href,
                    _clean(
                        " ".join(
                            self.current_class_title_text
                            or self.current_heading_text
                            or self.current_text
                        )
                    ),
                    self.current_in_article,
                )
            )
            self.current_href = None
            self.current_text = []
            self.current_heading_text = []
            self.current_class_title_text = []
            self.current_in_article = False
            self.class_title_depth = 0
        elif self.class_title_depth:
            self.class_title_depth -= 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading_depth:
            self.heading_depth -= 1
        if tag == "article" and self.article_depth:
            self.article_depth -= 1


class _TelegramPublicParser(HTMLParser):
    """Extract bounded, public Telegram ``t.me/s`` message data.

    Telegram's public web view is HTML rather than an RSS/JSON feed.  A
    generic link parser sees navigation and reaction links but misses the
    message body, post permalink and publication timestamp.  This parser
    deliberately keeps only the fields needed by ingestion and never stores
    the page markup.  A photo caption is the message text attached to the
    photo; it is therefore preserved as the item's excerpt and metadata.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.message_depth = 0
        self.text_depth = 0
        self.date_depth = 0
        self.current: dict[str, object] | None = None
        self.text_parts: list[str] = []
        self.caption_parts: list[str] = []
        self.date_value = ""
        self.date_href = ""
        self._photo = False
        self.items: list[dict[str, object]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value for key, value in attrs if value is not None}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        classes = set((values.get("class") or "").split())
        if self.message_depth == 0 and "tgme_widget_message" in classes and "tgme_widget_message_wrap" not in classes:
            self.message_depth = 1
            self.current = {
                "post": values.get("data-post") or "",
                "url": "",
                "media": "",
            }
            self.text_parts = []
            self.caption_parts = []
            self.date_value = ""
            self.date_href = ""
            self._photo = False
            return
        if self.message_depth == 0:
            return
        self.message_depth += 1
        if "tgme_widget_message_text" in classes:
            self.text_depth = 1
        elif self.text_depth:
            self.text_depth += 1
        if "tgme_widget_message_date" in classes:
            self.date_depth = 1
            self.date_href = values.get("href") or ""
        elif self.date_depth:
            self.date_depth += 1
        if tag == "time" and self.date_depth:
            self.date_value = values.get("datetime") or self.date_value
        if "tgme_widget_message_photo_wrap" in classes:
            self._photo = True
            if self.current is not None:
                self.current["media"] = "photo"
        if tag in {"img", "video"}:
            alt = _clean(values.get("alt") or values.get("title") or "")
            if alt and alt.lower() not in {"photo", "image", "video"}:
                self.caption_parts.append(alt)

    def handle_data(self, data: str) -> None:
        if self.message_depth == 0:
            return
        if self.text_depth:
            self.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.message_depth == 0:
            return
        if self.text_depth:
            self.text_depth -= 1
        if self.date_depth:
            self.date_depth -= 1
        self.message_depth -= 1
        if self.message_depth == 0:
            self._finish()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def _finish(self) -> None:
        if not self.current:
            return
        text = _clean(" ".join(self.text_parts))
        caption = _clean(" ".join(self.caption_parts))
        if not text and caption:
            text = caption
        post = str(self.current.get("post") or "").strip().lstrip("/")
        self.items.append({
            "post": post,
            "url": self.date_href,
            "text": text,
            "caption": caption or text,
            "published": self.date_value,
            "media": self.current.get("media") or ("photo" if self._photo else ""),
        })
        self.current = None
        self.text_depth = 0
        self.date_depth = 0


def parse_telegram_public(
    content: bytes,
    base_url: str,
    limit: int = 50,
) -> list[DiscoveredItem]:
    """Parse public Telegram web messages into safe ``DiscoveredItem`` rows."""
    parser = _TelegramPublicParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    base = urlparse(base_url)
    if not base.hostname:
        return []
    items: list[DiscoveredItem] = []
    seen: set[str] = set()
    for raw in parser.items:
        text = str(raw.get("text") or "").strip()
        post = str(raw.get("post") or "").strip()
        candidate = str(raw.get("url") or "").strip()
        if post and "/" in post:
            channel, message_id = post.rsplit("/", 1)
            if channel and message_id.isdigit():
                candidate = f"{base.scheme or 'https'}://{base.hostname}/{channel}/{message_id}"
        if not candidate:
            continue
        candidate = normalize_item_url(urljoin(base_url, candidate))
        try:
            validate_public_url_syntax(candidate)
        except ValueError:
            continue
        if not text or candidate in seen:
            # A media-only post with no caption has no analyzable text. It is
            # intentionally omitted so source health can flag an extraction
            # problem instead of presenting an empty article to the model.
            continue
        seen.add(candidate)
        message_id = post.rsplit("/", 1)[-1] if post else ""
        items.append(
            DiscoveredItem(
                title=text[:500],
                url=candidate,
                excerpt=text[:2000],
                published_at=_parse_date(str(raw.get("published") or "")),
                raw_metadata={
                    "adapter": "telegram_public",
                    "telegram_message_id": message_id[:64],
                    "media_type": str(raw.get("media") or "text")[:24],
                    "caption": str(raw.get("caption") or "")[:2000],
                },
            )
        )
        if len(items) >= limit:
            break
    return items


def parse_html_listing(
    content: bytes,
    base_url: str,
    limit: int = 50,
    item_url_pattern: str | None = None,
    item_title_class_pattern: str | None = None,
) -> list[DiscoveredItem]:
    parser = _LinkParser(item_title_class_pattern)
    parser.feed(content.decode("utf-8", errors="replace"))
    base_host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
    excluded = ("/tag/", "/author/", "/category/", "/page/", "/login", "/about")
    candidates = [link for link in parser.links if link[2]] or parser.links
    items: list[DiscoveredItem] = []
    seen: set[str] = set()
    path_pattern = re.compile(item_url_pattern) if item_url_pattern else None
    for href, title, _ in candidates:
        url = normalize_item_url(urljoin(base_url, href))
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host != base_host or any(part in parsed.path.lower() for part in excluded):
            continue
        if path_pattern and not path_pattern.search(parsed.path):
            continue
        if len(title) < 8 or url in seen or parsed.path in {"", "/"}:
            continue
        try:
            validate_public_url_syntax(url)
        except ValueError:
            continue
        seen.add(url)
        items.append(
            DiscoveredItem(
                title=title[:500],
                url=url,
                raw_metadata={"adapter": "html"},
            )
        )
        if len(items) >= limit:
            break
    return items


class PublicFeedLinks(HTMLParser):
    """Only publisher-advertised alternate feeds; never guess URL paths."""
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        kind = str(attributes.get("type") or "").lower().split(";")[0].strip()
        if tag.lower() == "link" and "alternate" in str(attributes.get("rel") or "").lower().split() and kind in {"application/rss+xml", "application/atom+xml", "application/feed+json"}:
            try:
                url = validate_public_url_syntax(urljoin(self.base_url, str(attributes.get("href") or "")))
                if attributes.get("href"):
                    pair = (url, "json" if kind == "application/feed+json" else "rss")
                    if pair not in self.links:
                        self.links.append(pair)
            except ValueError:
                pass


class PublicPublisherLinks(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href or len(self.links) >= 500:
            return
        try:
            self.links.append(validate_public_url_syntax(urljoin(self.base_url, href)))
        except ValueError:
            pass


class SourceFetcher:
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

    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str] | None = None,
        *,
        allowed_credential_hosts: frozenset[str] = frozenset(),
    ) -> httpx.Response:
        current = validate_public_url_syntax(url)
        for _ in range(MAX_REDIRECTS + 1):
            if headers and "Authorization" in headers:
                # Checked on every hop: a redirect must never carry the
                # credential to another host.
                parsed = urlparse(current)
                if parsed.scheme != "https" or (parsed.hostname or "").lower().rstrip(".") not in allowed_credential_hosts:
                    raise FetchFailure("connector credential cannot be sent to this host")
            await self.resolver(current)
            response = await client.get(current, headers=headers or {})
            if response.status_code not in REDIRECT_STATUS_CODES:
                return response
            location = response.headers.get("location")
            if not location:
                raise FetchFailure("redirect response did not include Location")
            current = validate_public_url_syntax(urljoin(current, location))
        raise FetchFailure("source exceeded the redirect limit")

    def _connector_headers(self, source: SourceSpec) -> dict[str, str]:
        """Resolve a connector credential from server settings only.

        A source may carry a reference (for example
        ``MARKET_INTELLIGENCE_X_SOURCE_BEARER_TOKEN``), but never a token.
        Unknown references are rejected rather than falling back to a
        delivery credential.
        """
        private = source.adapter.endswith("_private")
        spec = CONNECTOR_CREDENTIALS.get(source.adapter)
        if spec is None:
            return {}
        try:
            validate_connector_binding(source.adapter, source.credential_ref, source.fetch_url, self.settings)
        except ValueError as exc:
            raise FetchFailure(str(exc)) from None
        secret = getattr(self.settings, spec[0], None)
        if secret is None:
            raise FetchFailure("connector credential is not configured on the server")
        if private and source.access_policy != "private_authenticated":
            raise FetchFailure("private connector requires private_authenticated access policy")
        # Settings normally expose ``SecretStr`` values.  A few integration
        # tests and embedding callers provide a plain string via a validated
        # model copy; accepting both keeps the connector boundary typed while
        # never persisting or logging the resolved value.
        token = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        if not token.strip():
            raise FetchFailure("connector credential is not configured on the server")
        return {"Authorization": f"Bearer {token}"}

    async def _robots_allowed(
        self,
        client: httpx.AsyncClient,
        source: SourceSpec,
    ) -> tuple[bool, str]:
        if source.robots_policy == "disabled":
            return True, "disabled"
        parsed = urlparse(source.fetch_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = await self._request(client, robots_url)
        except (httpx.HTTPError, OSError, ValueError, FetchFailure):
            return True, "unavailable"
        if response.status_code != 200:
            return True, f"unavailable:{response.status_code}"
        if len(response.content) > 512_000:
            return True, "unavailable:too_large"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        allowed = parser.can_fetch(self.settings.fetch_user_agent, source.fetch_url)
        return allowed, "allowed" if allowed else "denied"

    async def publisher_links(self, reference_url: str) -> list[str]:
        """Corroborate an official homepage linked by a real search result."""
        url = validate_public_url_syntax(reference_url)
        source = SourceSpec(source_key="REFERENCE", name="Publisher reference", homepage_url=url, fetch_url=url, adapter="html", max_retries=0)
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, headers={"User-Agent": self.settings.fetch_user_agent}, transport=self.transport) as client:
            allowed, _ = await self._robots_allowed(client, source)
            if not allowed:
                return []
            response = await self._request(client, url)
            if response.status_code != 200 or len(response.content) > 2_000_000:
                return []
            parser = PublicPublisherLinks(str(response.url))
            parser.feed(response.text)
            return parser.links

    async def discover_feeds(self, homepage: str) -> list[tuple[str, str]]:
        homepage = validate_public_url_syntax(homepage)
        source = SourceSpec(source_key="DISCOVER", name="Feed discovery", homepage_url=homepage, fetch_url=homepage, adapter="html", max_retries=0)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, headers={"User-Agent": self.settings.fetch_user_agent}, transport=self.transport) as client:
            allowed, _ = await self._robots_allowed(client, source)
            if not allowed:
                return []
            response = await self._request(client, homepage)
            if response.status_code != 200 or len(response.content) > 2_000_000:
                return []
            parser = PublicFeedLinks(str(response.url))
            parser.feed(response.text)
            return parser.links[:3]

    async def fetch(self, source: SourceSpec) -> FetchResult:
        headers: dict[str, str] = self._connector_headers(source)
        if source.etag:
            headers["If-None-Match"] = source.etag
        if source.last_modified:
            headers["If-Modified-Since"] = source.last_modified
        timeout = min(source.request_timeout_seconds, self.settings.fetch_timeout_seconds)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            headers={"User-Agent": self.settings.fetch_user_agent},
            transport=self.transport,
        ) as client:
            allowed, robots_status = await self._robots_allowed(client, source)
            if not allowed:
                return FetchResult(
                    status="robots_denied",
                    items=(),
                    attempts=0,
                    status_code=None,
                    response_url=source.fetch_url,
                    robots_status=robots_status,
                )
            last_error: Exception | None = None
            attempts = source.max_retries + 1
            for attempt in range(1, attempts + 1):
                try:
                    response = await self._request(client, source.fetch_url, headers, allowed_credential_hosts=credential_hosts(source.adapter, self.settings))
                    # X's public API resolves a handle to an immutable user ID
                    # before the timeline endpoint can be called.  Keep this
                    # two-step exchange server-side so the back-office only
                    # stores the public handle and never asks users for an ID.
                    if source.adapter == "x_public" and response.status_code < 400:
                        response.raise_for_status()
                        try:
                            profile = response.json()
                        except ValueError as exc:
                            raise FetchFailure("X public profile response is not valid JSON", attempts=attempt) from exc
                        user_id = profile.get("data", {}).get("id") if isinstance(profile, dict) and isinstance(profile.get("data"), dict) else None
                        if not user_id or not re.fullmatch(r"\d{1,32}", str(user_id)):
                            raise FetchFailure("X public profile did not return a valid user id", attempts=attempt)
                        timeline_url = f"https://api.x.com/2/users/{user_id}/tweets?tweet.fields=created_at&max_results=100"
                        response = await self._request(client, timeline_url, headers, allowed_credential_hosts=credential_hosts(source.adapter, self.settings))
                    if response.status_code in TRANSIENT_STATUS_CODES and attempt < attempts:
                        await self.sleeper(min(2 ** (attempt - 1), 4))
                        continue
                    if response.status_code == 304:
                        return FetchResult(
                            status="not_modified",
                            items=(),
                            attempts=attempt,
                            status_code=304,
                            response_url=str(response.url),
                            etag=response.headers.get("etag") or source.etag,
                            last_modified=(
                                response.headers.get("last-modified")
                                or source.last_modified
                            ),
                            robots_status=robots_status,
                        )
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    if length and int(length) > self.settings.fetch_max_bytes:
                        raise FetchFailure("source response exceeds the byte limit")
                    if len(response.content) > self.settings.fetch_max_bytes:
                        raise FetchFailure("source response exceeds the byte limit")
                    if source.adapter in {"rss"}:
                        items = parse_feed(
                            response.content,
                            str(response.url),
                            self.settings.fetch_max_items_per_source,
                        )
                    elif source.adapter == "json":
                        items = parse_json_feed(
                            response.content,
                            str(response.url),
                            self.settings.fetch_max_items_per_source,
                        )
                    elif source.adapter == "telegram_public":
                        items = parse_telegram_public(
                            response.content,
                            str(response.url),
                            self.settings.fetch_max_items_per_source,
                        )
                    elif source.adapter == "html":
                        items = parse_html_listing(
                            response.content,
                            str(response.url),
                            self.settings.fetch_max_items_per_source,
                            source.item_url_pattern,
                            source.item_title_class_pattern,
                        )
                    elif source.adapter in {"instagram_public", "instagram_private", "x_public", "x_private", "telegram_private"}:
                        items = parse_social_json(
                            response.content,
                            str(response.url),
                            source.adapter,
                            self.settings.fetch_max_items_per_source,
                        )
                    else:
                        raise FetchFailure(f"unsupported adapter: {source.adapter}")
                    # A successful HTTP response with no extractable content
                    # is not a healthy source.  Keep the transport result
                    # distinguishable from a hard failure while allowing the
                    # ingestion layer to mark the source as degraded and show
                    # an actionable extraction error in the back-office.
                    fetch_status = "degraded" if not items else "succeeded"
                    return FetchResult(
                        status=fetch_status,
                        items=tuple(items),
                        attempts=attempt,
                        status_code=response.status_code,
                        response_url=str(response.url),
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        robots_status=robots_status,
                    )
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    last_error = exc
                    if attempt < attempts:
                        await self.sleeper(min(2 ** (attempt - 1), 4))
                        continue
                    break
                except httpx.HTTPStatusError as exc:
                    raise FetchFailure(
                        f"HTTP {exc.response.status_code} from source",
                        status_code=exc.response.status_code,
                        attempts=attempt,
                    ) from exc
                except (ET.ParseError, json.JSONDecodeError, ValueError) as exc:
                    raise FetchFailure(
                        f"invalid {source.adapter} response: {exc}",
                        status_code=response.status_code,
                        attempts=attempt,
                    ) from exc
            raise FetchFailure(
                f"source request failed: {type(last_error).__name__}: {last_error}",
                attempts=attempts,
            ) from last_error
