import json
import os
import unittest

import httpx


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.config import Settings  # noqa: E402
from app.fetchers import (  # noqa: E402
    SourceFetcher,
    SourceSpec,
    item_fingerprint,
    parse_feed,
    parse_html_listing,
    parse_json_feed,
    parse_telegram_public,
    parse_social_json,
    FetchFailure,
    validate_public_url_syntax,
)
from app.bee_cfo.discovery import discover_from_homepages  # noqa: E402


RSS = """<?xml version='1.0' encoding='UTF-8'?>
<rss><channel><item><title>خبر بانکي تازه</title>
<link>https://example.com/news/1#section</link>
<description>شرح خبر</description>
<pubDate>Sun, 10 Aug 2026 08:00:00 GMT</pubDate>
</item></channel></rss>""".encode("utf-8")


def settings() -> Settings:
    return Settings(
        postgres_db="assistant_test",
        postgres_user="assistant_test",
        postgres_password="secret",
        redis_password="secret",
        _env_file=None,
    )


async def allow_test_destination(_: str) -> None:
    return None


async def no_sleep(_: float) -> None:
    return None


class ParserTest(unittest.TestCase):
    def test_rss_atom_json_and_html_adapters(self):
        rss = parse_feed(RSS, "https://example.com/feed")
        self.assertEqual("خبر بانکي تازه", rss[0].title)
        self.assertEqual("https://example.com/news/1", rss[0].url)

        payload = json.dumps(
            {
                "items": [
                    {
                        "title": "JSON banking news",
                        "url": "/news/2",
                        "summary": "summary",
                        "date_published": "2026-08-10T08:00:00Z",
                    }
                ]
            }
        ).encode()
        parsed_json = parse_json_feed(payload, "https://example.com/api")
        self.assertEqual("https://example.com/news/2", parsed_json[0].url)

        parsed_html = parse_html_listing(
            b"<a href='/loan'>Navigation link</a>"
            b"<a href='/123-news'><div class='headline'>"
            b"A meaningful banking headline</div>Excerpt</a>",
            "https://example.com/",
            item_url_pattern=r"^/[0-9]+-",
            item_title_class_pattern=r"(^|\s)headline(\s|$)",
        )
        self.assertEqual("A meaningful banking headline", parsed_html[0].title)
        self.assertEqual("https://example.com/123-news", parsed_html[0].url)

    def test_feed_parser_rejects_dtd_and_external_entity_payloads(self):
        payload = b'''<?xml version="1.0"?>
        <!DOCTYPE rss [<!ENTITY local SYSTEM "file:///etc/passwd">]>
        <rss><channel><item><title>&local;</title>
        <link>https://example.com/news/1</link></item></channel></rss>'''
        with self.assertRaisesRegex(ValueError, "DOCTYPE"):
            parse_feed(payload, "https://example.com/feed")

        payload_with_late_doctype = (
            b" " * 4097
            + b'''<!DOCTYPE rss [<!ENTITY expansion "unsafe">]><rss>&expansion;</rss>'''
        )
        with self.assertRaisesRegex(ValueError, "Unsafe XML"):
            parse_feed(payload_with_late_doctype, "https://example.com/feed")

    def test_url_safety_and_stable_fingerprint(self):
        for url in (
            "http://127.0.0.1/feed",
            "http://localhost/feed",
            "https://user:pass@example.com/feed",
            "https://example.com/feed?access_token=secret",
            "file:///tmp/feed",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url_syntax(url)
        self.assertEqual(
            item_fingerprint("A", "https://EXAMPLE.com/news/#fragment"),
            item_fingerprint("B", "https://example.com/news"),
        )

    def test_social_payloads_are_minimal_and_normalized(self):
        payload = json.dumps({"data": [{"id": "42", "text": "X banking update", "created_at": "2026-08-10T08:00:00Z"}]}).encode()
        items = parse_social_json(payload, "https://api.example.com/v2", "x_public")
        self.assertEqual("X banking update", items[0].title)
        self.assertEqual("x_public", items[0].raw_metadata["adapter"])
        self.assertNotIn("token", json.dumps(items[0].raw_metadata).lower())

    def test_instagram_business_discovery_payload_is_normalized(self):
        payload = json.dumps({
            "business_discovery": {
                "id": "private-account-id",
                "media": {"data": [{
                    "id": "99",
                    "caption": "Public fintech update",
                    "permalink": "https://www.instagram.com/p/abc/",
                    "timestamp": "2026-08-10T08:00:00Z",
                }]},
            },
            "access_token": "must-not-leak",
        }).encode()
        items = parse_social_json(payload, "https://graph.facebook.com/v21.0/me", "instagram_public")
        self.assertEqual(1, len(items))
        self.assertEqual("Public fintech update", items[0].title)
        self.assertEqual("instagram_public", items[0].raw_metadata["adapter"])
        self.assertNotIn("private-account-id", json.dumps(items[0].raw_metadata))

    def test_telegram_public_parser_extracts_posts_and_skips_media_only(self):
        content = b'''<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="channel/123">
          <div class="tgme_widget_message_text">Bank payment update &amp; details</div>
          <a class="tgme_widget_message_date" href="https://t.me/channel/123"><time datetime="2026-08-30T10:00:00+00:00"></time></a>
        </div></div>
        <div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="channel/124">
          <div class="tgme_widget_message_photo_wrap"><img alt="photo"></div>
          <a class="tgme_widget_message_date" href="https://t.me/channel/124"><time datetime="2026-08-30T11:00:00+00:00"></time></a>
        </div></div>'''
        items = parse_telegram_public(content, "https://t.me/s/channel", limit=20)
        self.assertEqual(1, len(items))
        self.assertEqual("Bank payment update & details", items[0].title)
        self.assertEqual("https://t.me/channel/123", items[0].url)
        self.assertEqual("123", items[0].raw_metadata["telegram_message_id"])
        self.assertEqual("telegram_public", items[0].raw_metadata["adapter"])


class FetcherTest(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_does_not_follow_redirects_into_private_addresses(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://127.0.0.1/internal"})

        result = await discover_from_homepages(
            ["https://example.com/"],
            settings(),
            resolver=allow_test_destination,
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual([], result)
        self.assertEqual(["https://example.com/"], calls)

    async def test_authenticated_connector_requires_server_credential_reference(self):
        fetcher = SourceFetcher(settings(), resolver=allow_test_destination)
        with self.assertRaises(FetchFailure) as ctx:
            await fetcher.fetch(SourceSpec(
                source_key="S-X", name="X", homepage_url="https://api.example.com",
                fetch_url="https://api.example.com/v2", adapter="x_public",
                credential_ref="X_SOURCE_BEARER_TOKEN",
            ))
        self.assertNotIn("secret", str(ctx.exception).lower())

    async def test_x_public_resolves_handle_then_fetches_timeline(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            if request.url.path.endswith("/by/username/example"):
                return httpx.Response(200, json={"data": {"id": "123"}})
            if request.url.path.endswith("/users/123/tweets"):
                return httpx.Response(200, json={"data": [{"id": "7", "text": "Public update", "created_at": "2026-08-10T08:00:00Z"}]})
            return httpx.Response(404)

        configured = settings().model_copy(update={"x_source_bearer_token": "server-token"})
        fetcher = SourceFetcher(configured, transport=httpx.MockTransport(handler), resolver=allow_test_destination)
        result = await fetcher.fetch(SourceSpec(
            source_key="S-X", name="X", homepage_url="https://x.com/example",
            fetch_url="https://api.x.com/2/users/by/username/example", adapter="x_public",
            credential_ref="X_SOURCE_BEARER_TOKEN",
        ))
        self.assertEqual("succeeded", result.status)
        self.assertEqual("Public update", result.items[0].title)
        self.assertEqual(3, len(calls))
        self.assertIn("/users/123/tweets", calls[-1])

    async def test_conditional_fetch_retries_transient_failure(self):
        feed_calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal feed_calls
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            feed_calls += 1
            self.assertEqual('"cursor"', request.headers.get("if-none-match"))
            if feed_calls == 1:
                return httpx.Response(503, text="temporary")
            return httpx.Response(
                200,
                content=RSS,
                headers={"content-type": "application/rss+xml", "etag": '"next"'},
            )

        fetcher = SourceFetcher(
            settings(),
            transport=httpx.MockTransport(handler),
            resolver=allow_test_destination,
            sleeper=no_sleep,
        )
        result = await fetcher.fetch(
            SourceSpec(
                source_key="S-TEST",
                name="Test",
                homepage_url="https://example.com/",
                fetch_url="https://example.com/feed",
                adapter="rss",
                etag='"cursor"',
                max_retries=1,
            )
        )
        self.assertEqual("succeeded", result.status)
        self.assertEqual(2, result.attempts)
        self.assertEqual('"next"', result.etag)
        self.assertEqual(1, len(result.items))

    async def test_robots_denial_stops_source_fetch(self):
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, text="User-agent: *\nDisallow: /feed\n")

        fetcher = SourceFetcher(
            settings(),
            transport=httpx.MockTransport(handler),
            resolver=allow_test_destination,
        )
        result = await fetcher.fetch(
            SourceSpec(
                source_key="S-TEST",
                name="Test",
                homepage_url="https://example.com/",
                fetch_url="https://example.com/feed",
                adapter="rss",
            )
        )
        self.assertEqual("robots_denied", result.status)
        self.assertEqual(["/robots.txt"], paths)

    async def test_successful_http_without_extractable_items_is_degraded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            return httpx.Response(200, text='<html><body><h1>no feed items</h1></body></html>')

        fetcher = SourceFetcher(
            settings(),
            transport=httpx.MockTransport(handler),
            resolver=allow_test_destination,
        )
        result = await fetcher.fetch(SourceSpec(
            source_key="S-EMPTY", name="Empty", homepage_url="https://example.com/",
            fetch_url="https://example.com/feed", adapter="html",
        ))
        self.assertEqual("degraded", result.status)
        self.assertEqual((), result.items)


if __name__ == "__main__":
    unittest.main()
