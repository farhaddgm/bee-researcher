from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx
from app.public_network import PublicHTTPTransport

from app.config import Settings
from app.fetchers import FetchFailure, SourceFetcher, resolve_public_destination, validate_public_url_syntax


@dataclass(frozen=True, slots=True)
class DiscoveredSourceCandidate:
    name: str
    homepage_url: str
    fetch_url: str
    adapter: str
    discovery_path: str
    authority: str = "exploratory"


class _FeedLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        rel = values.get("rel", "").lower()
        type_value = values.get("type", "").lower()
        href = values.get("href", "").strip()
        if href and ("alternate" in rel or type_value in {"application/rss+xml", "application/atom+xml", "application/json"}):
            self.links.append((href, type_value, rel))


def extract_feed_candidates(html: str, homepage_url: str, *, limit: int = 10) -> list[DiscoveredSourceCandidate]:
    """Find same-domain RSS/Atom/JSON feed declarations without auto-approval."""
    validate_public_url_syntax(homepage_url)
    parser = _FeedLinkParser()
    parser.feed(html[:500_000])
    homepage = urlparse(homepage_url)
    found: dict[str, DiscoveredSourceCandidate] = {}
    for raw_href, type_value, rel in parser.links:
        candidate = urljoin(homepage_url, raw_href)
        try:
            candidate = validate_public_url_syntax(candidate)
        except ValueError:
            continue
        parsed = urlparse(candidate)
        if parsed.hostname != homepage.hostname:
            continue
        if type_value == "application/json" or candidate.lower().endswith(".json"):
            adapter = "json"
        elif "atom" in type_value or "atom" in rel:
            adapter = "rss"
        else:
            adapter = "rss"
        key = candidate.rstrip("/").lower()
        found.setdefault(
            key,
            DiscoveredSourceCandidate(
                name=f"Discovered feed: {parsed.path or parsed.netloc}",
                homepage_url=homepage_url,
                fetch_url=candidate,
                adapter=adapter,
                discovery_path="domain_discovery",
            ),
        )
        if len(found) >= limit:
            break
    return list(found.values())


async def discover_from_homepages(
    homepages: list[str],
    settings: Settings,
    *,
    resolver: Callable[[str], Awaitable[None]] = resolve_public_destination,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DiscoveredSourceCandidate]:
    candidates: list[DiscoveredSourceCandidate] = []
    seen: set[str] = set()
    # Reuse the ingestion fetcher's bounded redirect + DNS validation. A
    # discovery homepage is untrusted input; httpx's default redirect
    # behaviour would otherwise allow a public URL to hop into an internal
    # destination after the initial validation.
    fetcher = SourceFetcher(settings, transport=transport, resolver=resolver)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.fetch_timeout_seconds),
        follow_redirects=False,
        transport=transport or PublicHTTPTransport(), trust_env=False,
        headers={"User-Agent": settings.fetch_user_agent},
    ) as client:
        for homepage in homepages[:10]:
            try:
                homepage = validate_public_url_syntax(homepage)
                response = await fetcher._request(client, homepage)
                if len(response.content) > settings.fetch_max_bytes:
                    raise FetchFailure("discovery response exceeded the configured size limit")
                response.raise_for_status()
                resolved_homepage = str(response.url)
                for candidate in extract_feed_candidates(response.text, resolved_homepage):
                    if candidate.fetch_url not in seen:
                        seen.add(candidate.fetch_url)
                        candidates.append(candidate)
            except (FetchFailure, ValueError, httpx.HTTPError):
                continue
    return candidates[:20]


def candidate_source_key(url: str) -> str:
    return f"BC-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]}"
