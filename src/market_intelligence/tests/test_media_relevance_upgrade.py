import json
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.ai_relevance import classify_articles, relevance_context_hash, relevance_decision
from app.admin import _SOURCE_DRAFT_SCHEMA, _SOURCE_SUGGESTIONS_SCHEMA, AssistantRuntimeSettingsUpdate, _verify_source_draft, _catalog_draft
from app.fetchers import FetchFailure
from types import SimpleNamespace
from app.config import Settings
from app.fetchers import PublicFeedLinks, PublicPublisherLinks
from app.media_discovery import DiscoveryUnavailable, discover_media, grounded_url, publisher_host, publisher_identity
from app.openai_client import AIProviderError, OpenAIClient
from app.relevance import lexical_topic_score
from app import media_discovery, openai_client
import time


def settings(**overrides):
    return Settings(postgres_db="test", postgres_user="test", postgres_password="test", redis_password="test", _env_file=None, **overrides)


class DiscoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_identical_searches_share_evidence_and_release_locks(self):
        client = OpenAIClient(settings(openai_api_key="concurrent-fixture", external_analysis_approved=True))
        async def search(query):
            await asyncio.sleep(.01)
            return {"urls": ["https://example.org/"], "text": "actual evidence"}
        with patch.object(client, "search_web", new=AsyncMock(side_effect=search)) as provider:
            results = await asyncio.gather(*(media_discovery._cached_web_search(client, "concurrent query") for _ in range(8)))
            self.assertEqual(1, provider.await_count)
            self.assertEqual(7, sum(bool(r.get("cached")) for r in results))
        self.assertEqual({}, media_discovery._SEARCH_LOCKS)

    async def test_failed_search_is_not_cached_and_releases_lock(self):
        client = OpenAIClient(settings(openai_api_key="failure-fixture", external_analysis_approved=True))
        with patch.object(client, "search_web", new=AsyncMock(side_effect=AIProviderError("provider_quota_exhausted"))) as provider:
            for _ in range(2):
                with self.assertRaises(AIProviderError):
                    await media_discovery._cached_web_search(client, "failure query")
            self.assertEqual(2, provider.await_count)
        self.assertEqual({}, media_discovery._SEARCH_LOCKS)

    async def test_search_cache_is_copy_safe_and_exclusions_have_separate_entries(self):
        client = OpenAIClient(settings(openai_api_key="cache-fixture", external_analysis_approved=True))
        with patch.object(client, "search_web", new=AsyncMock(return_value={"text": "actual evidence", "urls": ["https://example.org/"], "provider": "fixture"})) as search:
            first = await media_discovery._cached_web_search(client, "unique cache test query")
            first["urls"].clear()
            second = await media_discovery._cached_web_search(client, "unique cache test query")
            self.assertEqual(["https://example.org/"], second["urls"])
            self.assertTrue(second["cached"])
            self.assertEqual(1, search.await_count)
            await media_discovery._cached_web_search(client, "unique cache test query -site:example.org")
            self.assertEqual(2, search.await_count)

    async def test_quota_cooldown_blocks_calls_and_expires_without_claiming_healthy(self):
        client = OpenAIClient(settings(openai_api_key="cooldown-fixture", external_analysis_approved=True))
        with patch.dict(openai_client._PROVIDER_COOLDOWNS, {client._provider_key(): (time.monotonic() + 60, "provider_quota_exhausted")}):
            self.assertEqual("cooldown", client.provider_health()["state"])
            with self.assertRaises(AIProviderError):
                await client._post("/responses", {})
            with patch("app.openai_client.time.monotonic", return_value=time.monotonic() + 120):
                self.assertEqual("not_checked", client.provider_health()["state"])

    async def test_exhausted_api_credits_are_actionable_and_not_retried(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota", "message": "secret must never escape"}})
        client = OpenAIClient(settings(openai_api_key="test", external_analysis_approved=True), transport=httpx.MockTransport(handler))
        with self.assertRaises(AIProviderError) as error:
            await client.draft_json(system_prompt="fixture", user_payload={}, schema_name="fixture", schema={})
        self.assertEqual("provider_quota_exhausted", error.exception.code)
        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(1, len(calls))

    async def test_provider_outage_is_not_a_false_no_media_result(self):
        result = await _verify_source_draft({"provider_status": "provider_quota_exhausted", "match_status": "uncertain"})
        self.assertEqual("provider_unavailable", result["status"])
        self.assertEqual("provider_quota_exhausted", result["provider_status"])

    async def test_explicit_telegram_url_does_not_need_ai_or_lose_channel_path(self):
        with patch("app.admin.discover_media", new=AsyncMock(side_effect=AssertionError("no provider needed"))):
            result = await _catalog_draft("source", "https://t.me/s/specific_channel", "")
        self.assertEqual("https://t.me/s/specific_channel", result["fetch_url"])
        self.assertEqual("telegram_public", result["adapter"])

    def test_strict_source_schema_requires_every_property(self):
        self.assertEqual(set(_SOURCE_DRAFT_SCHEMA["properties"]), set(_SOURCE_DRAFT_SCHEMA["required"]))
        self.assertEqual(10, _SOURCE_SUGGESTIONS_SCHEMA["properties"]["suggestions"]["maxItems"])

    def test_evidence_and_public_url_boundaries(self):
        self.assertTrue(grounded_url("https://example.com", ["https://news.example.com/news"]))
        self.assertFalse(grounded_url("https://evil-example.com", ["https://example.com/news"]))
        for url in ["http://localhost", "http://127.0.0.1", "file:///etc/passwd", "javascript:alert(1)"]:
            self.assertFalse(publisher_host(url))

    def test_shared_platforms_are_distinct_publishers_not_one_host(self):
        self.assertEqual(publisher_identity("https://t.me/s/channelA/20"), publisher_identity("https://t.me/channelA"))
        self.assertTrue(grounded_url("https://t.me/channelA", ["https://t.me/s/channelA/20"]))
        self.assertFalse(grounded_url("https://t.me/channelA", ["https://t.me/s/channelB/20"]))
        self.assertFalse(grounded_url("https://medium.com/@alice", ["https://medium.com/@bob/story"]))
        self.assertFalse(grounded_url("https://youtube.com/channel/UCalpha", ["https://youtube.com/channel/UCbeta/videos"]))
        self.assertNotEqual(publisher_identity("https://youtube.com/channel/UCalpha"), publisher_identity("https://youtube.com/channel/UCAlpha"))
        self.assertTrue(grounded_url("https://youtube.com/@news", ["https://www.youtube.com/@News/videos"]))
        self.assertEqual("", publisher_identity("https://youtube.com/watch?v=unverified"))

    async def test_broken_first_feed_falls_through_to_next_verified_connector(self):
        draft = {"name": "News", "homepage_url": "https://example.org/", "fetch_url": "https://example.org/", "adapter": "html", "match_status": "match"}
        good = SimpleNamespace(status="succeeded", items=["actual item"], response_url="https://example.org/good-feed")
        fetch = AsyncMock(side_effect=[FetchFailure("obsolete", status_code=404), good])
        with patch("app.admin.SourceFetcher.discover_feeds", new=AsyncMock(return_value=[("https://example.org/old-feed", "rss"), ("https://example.org/good-feed", "rss")])), patch("app.admin.SourceFetcher.fetch", new=fetch):
            result = await _verify_source_draft(draft)
        self.assertEqual("ready", result["status"])
        self.assertEqual("https://example.org/good-feed", draft["fetch_url"])
        self.assertEqual(2, fetch.await_count)

    async def test_readable_homepage_survives_unusable_feeds(self):
        draft = {"name": "News", "homepage_url": "https://example.org/", "fetch_url": "https://example.org/", "adapter": "html", "match_status": "match"}
        empty = SimpleNamespace(status="succeeded", items=[], response_url="https://example.org/feed")
        good = SimpleNamespace(status="succeeded", items=["article"], response_url="https://example.org/")
        with patch("app.admin.SourceFetcher.discover_feeds", new=AsyncMock(return_value=[("https://example.org/feed", "rss")])), patch("app.admin.SourceFetcher.fetch", new=AsyncMock(side_effect=[empty, good])):
            result = await _verify_source_draft(draft)
        self.assertEqual("ready", result["status"])
        self.assertEqual("html", draft["adapter"])

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
        with patch("app.media_discovery.SourceFetcher.publisher_links", new=AsyncMock(return_value=[])):
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
    def test_explanation_uses_live_ai_decision_not_combined_score(self):
        import inspect
        from app.admin import publication_explanation
        self.assertIn('_article_decisions', inspect.getsource(publication_explanation))
        self.assertNotIn('item.combined_score', inspect.getsource(publication_explanation))

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
        client.draft_json.return_value = {"scores": [{"article_id": "a1", "topic_key": "AI", "score": .92, "reason": "New AI model", "confidence": .9, "evidence": ["AI model released"], "excluded": False}]}
        result = await classify_articles(client, articles=[{"id": "a1", "title": "A new model", "text": "AI model released"}], topics=[{"topic_key": "AI", "definition": "هوش مصنوعی"}], business={}, mission="AI news")
        self.assertEqual(.92, result[("a1", "AI")][0])
        self.assertEqual({}, client.draft_json.call_args.kwargs["user_payload"]["optional_business"])

    async def test_fabricated_quotes_and_invalid_confidence_fail_closed(self):
        client = AsyncMock()
        row = {"article_id": "a1", "topic_key": "AI", "score": .8, "reason": "Facts", "confidence": .9, "evidence": ["AI model"], "excluded": False}
        for change in [{"evidence": ["invented news"]}, {"evidence": []}, {"confidence": float("nan")}, {"confidence": True}, {"reason": ""}, {"excluded": "false"}]:
            client.draft_json.return_value = {"scores": [{**row, **change}]}
            with self.assertRaises(RuntimeError):
                await classify_articles(client, articles=[{"id": "a1", "title": "AI model", "text": "real facts"}], topics=[{"topic_key": "AI"}], business={}, mission="")

    def test_per_topic_threshold_not_highest_raw_score_determines_winner(self):
        rows = [{"valid": True, "score": .8, "threshold": .95, "confidence": .9, "topic_key": "A"},
                {"valid": True, "score": .65, "threshold": .6, "confidence": .9, "topic_key": "B"}]
        result = relevance_decision(rows, topic_count=2)
        self.assertTrue(result["publishable"])
        self.assertEqual("B", result["relevance_topic"])
        self.assertEqual(.65, result["relevance_score"])

    def test_decision_boundaries_pending_partial_excluded_and_low_confidence(self):
        base = {"valid": True, "score": .6, "threshold": .6, "confidence": .9}
        self.assertEqual("selected", relevance_decision([base], topic_count=1)["relevance_state"])
        self.assertEqual("borderline", relevance_decision([{**base, "score": .5}], topic_count=1)["relevance_state"])
        self.assertEqual("rejected", relevance_decision([{**base, "score": .49}], topic_count=1)["relevance_state"])
        for changes in [{"confidence": .3}, {}]:
            self.assertEqual("borderline", relevance_decision([{**base, **changes}], topic_count=1, incomplete=not changes)["relevance_state"])
        self.assertEqual("pending", relevance_decision([base], topic_count=2)["relevance_state"])
        self.assertEqual("pending", relevance_decision([{**base, "valid": False}], topic_count=1)["relevance_state"])
        excluded = relevance_decision([{**base, "excluded": True}], topic_count=1)
        self.assertEqual("rejected", excluded["relevance_state"])
        self.assertFalse(excluded["can_approve"])

    async def test_partial_duplicate_unknown_or_nan_scores_fail_closed(self):
        client = AsyncMock()
        row = {"article_id": "a1", "topic_key": "AI", "score": .8, "reason": "Evidence"}
        for rows in [[], [row, row], [{**row, "article_id": "other"}], [{**row, "score": float("nan")}], [{**row, "score": True}]]:
            client.draft_json.return_value = {"scores": rows}
            with self.assertRaises(RuntimeError):
                await classify_articles(client, articles=[{"id": "a1", "title": "news", "text": "facts"}], topics=[{"topic_key": "AI"}], business={}, mission="")
