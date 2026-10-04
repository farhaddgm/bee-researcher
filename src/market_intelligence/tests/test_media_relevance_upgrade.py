import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.ai_relevance import classify_articles, relevance_context_hash
from app.admin import _SOURCE_DRAFT_SCHEMA, _SOURCE_SUGGESTIONS_SCHEMA, AssistantRuntimeSettingsUpdate
from app.config import Settings
from app.fetchers import PublicFeedLinks, PublicPublisherLinks
from app.media_discovery import DiscoveryUnavailable, discover_media, grounded_url, publisher_host
from app.openai_client import OpenAIClient
from app.relevance import lexical_topic_score


def settings(**overrides):
    return Settings(postgres_db="test", postgres_user="test", postgres_password="test", redis_password="test", _env_file=None, **overrides)


class DiscoveryTest(unittest.IsolatedAsyncioTestCase):
    def test_strict_source_schema_requires_every_property(self):
        self.assertEqual(set(_SOURCE_DRAFT_SCHEMA["properties"]), set(_SOURCE_DRAFT_SCHEMA["required"]))
        self.assertEqual(10, _SOURCE_SUGGESTIONS_SCHEMA["properties"]["suggestions"]["maxItems"])

    def test_evidence_and_public_url_boundaries(self):
        self.assertTrue(grounded_url("https://example.com", ["https://news.example.com/news"]))
        self.assertFalse(grounded_url("https://evil-example.com", ["https://example.com/news"]))
        for url in ["http://localhost", "http://127.0.0.1", "file:///etc/passwd", "javascript:alert(1)"]:
            self.assertFalse(publisher_host(url))

    async def test_provider_unavailable_is_not_no_results(self):
        with self.assertRaises(DiscoveryUnavailable):
            await discover_media(settings(), name="朝日新聞", instruction="", schema=_SOURCE_DRAFT_SCHEMA)

    async def test_multilingual_refresh_excludes_duplicates_and_ungrounded_urls(self):
        client = AsyncMock()
        client.configured = True
        client.search_web.return_value = {"text": "news", "urls": ["https://old.example.com/", "https://new.example.com/story"], "provider": "openai_web_search"}
        client.draft_json.return_value = {"suggestions": [
            {"name": "old", "homepage_url": "https://old.example.com/"},
            {"name": "新しい新聞", "homepage_url": "https://new.example.com/"},
            {"name": "fabricated", "homepage_url": "https://fake.example.org/"},
        ], "alternatives": [], "message": ""}
        result = await discover_media(settings(), name="人工知能", instruction="", schema=_SOURCE_SUGGESTIONS_SCHEMA, suggestions=True, exclude=["https://old.example.com/"], page=1, client=client)
        self.assertEqual(["新しい新聞"], [r["name"] for r in result["suggestions"]])
        query = client.search_web.call_args.args[0]
        self.assertIn("人工知能", query)
        self.assertIn("-site:old.example.com", query)
        self.assertEqual(["https://new.example.com/story"], result["suggestions"][0]["evidence"])

    async def test_unverified_feed_is_not_invented(self):
        client = AsyncMock(configured=True)
        client.search_web.return_value = {"text": "publisher", "urls": ["https://example.com/"], "provider": "openai_web_search"}
        client.draft_json.return_value = {"homepage_url": "https://example.com/", "fetch_url": "https://example.com/made-up-feed", "adapter": "rss"}
        result = await discover_media(settings(), name="publisher", instruction="", schema=_SOURCE_DRAFT_SCHEMA, client=client)
        self.assertEqual("html", result["adapter"])
        self.assertEqual("https://example.com/", result["fetch_url"])

    def test_feed_discovery_uses_only_actual_safe_alternate_links(self):
        parser = PublicFeedLinks("https://news.example.org/")
        parser.feed('<link rel="alternate" type="application/rss+xml" href="/rss.xml"><link rel="alternate" type="application/rss+xml" href="http://localhost/private"><a href="/guessed-feed">RSS</a>')
        self.assertEqual([("https://news.example.org/rss.xml", "rss")], parser.links)
        links = PublicPublisherLinks("https://reference.example.org/about")
        links.feed('<a href="https://publisher.example.org/">Official site</a><a href="javascript:alert(1)">Bad</a>')
        self.assertEqual(["https://publisher.example.org/"], links.links)

    async def test_search_reference_can_verify_a_real_official_outbound_link(self):
        client = AsyncMock(configured=True)
        client.search_web.return_value = {"text": "The Publisher official website", "urls": ["https://reference.example.org/about"], "provider": "openai_web_search"}
        client.draft_json.return_value = {"homepage_url": "https://publisher.example.org/", "fetch_url": "https://publisher.example.org/feed", "adapter": "rss", "match_status": "match", "alternatives": ["Invented typo"]}
        with patch("app.media_discovery.SourceFetcher.publisher_links", new=AsyncMock(return_value=["https://publisher.example.org/"])):
            result = await discover_media(settings(), name="The Publisher", instruction="", schema=_SOURCE_DRAFT_SCHEMA, client=client)
        self.assertEqual("https://publisher.example.org/", result["homepage_url"])
        self.assertEqual([], result["alternatives"])
        self.assertEqual(["https://reference.example.org/about"], result["publisher_evidence"])

    async def test_reference_without_official_link_cannot_validate_model_guess(self):
        client = AsyncMock(configured=True)
        client.search_web.return_value = {"text": "news", "urls": ["https://reference.example.org/"], "provider": "openai_web_search"}
        client.draft_json.return_value = {"homepage_url": "https://fabricated.example.org/", "fetch_url": "https://fabricated.example.org/rss", "match_status": "match"}
        with patch("app.media_discovery.SourceFetcher.publisher_links", new=AsyncMock(return_value=[])):
            result = await discover_media(settings(), name="News", instruction="", schema=_SOURCE_DRAFT_SCHEMA, client=client)
        self.assertEqual("", result["homepage_url"])
        self.assertEqual("uncertain", result["match_status"])

    async def test_web_search_requires_a_real_tool_call_and_citations(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual("required", body["tool_choice"])
            self.assertEqual("web_search", body["tools"][0]["type"])
            return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "invented"}]}]})
        client = OpenAIClient(settings(openai_api_key="test", external_analysis_approved=True), transport=httpx.MockTransport(handler))
        with self.assertRaises(RuntimeError):
            await client.search_web("media")


class RelevanceTest(unittest.IsolatedAsyncioTestCase):
    def test_ai_news_is_not_capped_by_financial_vocabulary(self):
        value, positive, _ = lexical_topic_score(title="ChatGPT launches new AI model", text="ChatGPT introduces a new model. ChatGPT can code.", positive_terms=["ChatGPT"], negative_terms=[])
        self.assertGreater(value, 0.4)
        self.assertTrue(positive)

    def test_project_threshold_is_validated(self):
        self.assertEqual(0.2, AssistantRuntimeSettingsUpdate(relevance_threshold=0.2).relevance_threshold)
        for bad in [-1, 1.1]:
            with self.assertRaises(ValueError):
                AssistantRuntimeSettingsUpdate(relevance_threshold=bad)

    def test_config_changes_invalidate_old_ai_evidence(self):
        self.assertNotEqual(relevance_context_hash({"threshold": .2}), relevance_context_hash({"threshold": .8}))

    async def test_semantic_cross_language_score_uses_optional_business(self):
        client = AsyncMock()
        client.draft_json.return_value = {"scores": [{"article_id": "a1", "topic_key": "AI", "score": .92, "reason": "New AI model"}]}
        result = await classify_articles(client, articles=[{"id": "a1", "title": "A new model", "text": "AI model released"}], topics=[{"topic_key": "AI", "definition": "هوش مصنوعی"}], business={}, mission="AI news")
        self.assertEqual(.92, result[("a1", "AI")][0])
        self.assertEqual({}, client.draft_json.call_args.kwargs["user_payload"]["optional_business"])

    async def test_partial_duplicate_unknown_or_nan_scores_fail_closed(self):
        client = AsyncMock()
        row = {"article_id": "a1", "topic_key": "AI", "score": .8, "reason": "Evidence"}
        for rows in [[], [row, row], [{**row, "article_id": "other"}], [{**row, "score": float("nan")}], [{**row, "score": True}]]:
            client.draft_json.return_value = {"scores": rows}
            with self.assertRaises(RuntimeError):
                await classify_articles(client, articles=[{"id": "a1", "title": "news", "text": "facts"}], topics=[{"topic_key": "AI"}], business={}, mission="")
