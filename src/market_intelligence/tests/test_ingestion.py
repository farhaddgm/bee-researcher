import os
import unittest


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.ingestion_service import run_sources_independently  # noqa: E402


class IsolationBoundaryTest(unittest.IsolatedAsyncioTestCase):
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
