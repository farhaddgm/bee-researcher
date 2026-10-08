import os
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.ingestion_service import run_sources_independently  # noqa: E402
from app import ingestion_service as ingestion  # noqa: E402
from app.fetchers import FetchResult, DiscoveredItem, SourceSpec  # noqa: E402
from app.config import get_settings  # noqa: E402


class Session:
    def __init__(self, source):
        self.source = source
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, *args, **kwargs):
        return self.source

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass


class IsolationBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_health_probe_cannot_acknowledge_or_delay_unstored_content(self):
        now = datetime.now(timezone.utc)
        source = SimpleNamespace(assistant_id=uuid.uuid4(), rate_limit_seconds=120, next_allowed_at=now, etag='"stored"', last_modified="old", consecutive_failures=0)
        session = Session(source)
        result = FetchResult("succeeded", (DiscoveredItem("A new headline", "https://example.org/new"),), 1, 200, "https://example.org/rss", etag='"unstored"', last_modified="new")
        with patch.object(ingestion, "SessionLocal", return_value=session):
            await ingestion._record_result(uuid.uuid4(), now, result, status="succeeded", update_ingestion_state=False)
        self.assertEqual('"stored"', source.etag)
        self.assertEqual("old", source.last_modified)
        self.assertEqual(now, source.next_allowed_at)
        self.assertEqual("healthy", source.health_status)

    async def test_health_probe_reads_full_content_and_lock_is_per_source(self):
        source = SimpleNamespace(id=uuid.uuid4(), assistant_id=uuid.uuid4(), source_key="same-key", enabled=True, next_allowed_at=None)
        spec = SourceSpec("same-key", "Feed", "https://example.com", "https://example.com/rss", "rss", etag='"old"', last_modified="old")
        redis = SimpleNamespace(set=AsyncMock(return_value=True), eval=AsyncMock(), aclose=AsyncMock())
        fetcher = SimpleNamespace(fetch=AsyncMock(return_value=FetchResult("succeeded", (DiscoveredItem("New headline", "https://example.com/new"),), 1, 200, spec.fetch_url)))
        with patch.object(ingestion, "SessionLocal", return_value=Session(source)), patch.object(ingestion, "_source_spec", return_value=spec), patch.object(ingestion.Redis, "from_url", return_value=redis), patch.object(ingestion, "SourceFetcher", return_value=fetcher), patch.object(ingestion, "_record_result", new=AsyncMock()) as record, patch.object(ingestion, "_store_items", new=AsyncMock()) as store:
            await ingestion._ingest_source(source.id, settings=get_settings(), force=True, store_items=False)
        sent = fetcher.fetch.call_args.args[0]
        self.assertIsNone(sent.etag)
        self.assertIsNone(sent.last_modified)
        self.assertIn(source.id.hex, redis.set.call_args.args[0])
        self.assertFalse(record.call_args.kwargs["update_ingestion_state"])
        store.assert_not_called()

    async def test_one_source_failure_does_not_stop_healthy_peers(self):
        visited: list[str] = []

        async def handler(source: str) -> str:
            visited.append(source)
            if source == "broken":
                raise RuntimeError("source unavailable")
            return f"ok:{source}"

        results = await run_sources_independently(
            ["first", "broken", "last"],
            handler,
            concurrency=3,
            on_error=lambda source, exc: f"failed:{source}:{type(exc).__name__}",
        )
        self.assertEqual(
            ["ok:first", "failed:broken:RuntimeError", "ok:last"],
            results,
        )
        self.assertEqual({"first", "broken", "last"}, set(visited))


if __name__ == "__main__":
    unittest.main()
