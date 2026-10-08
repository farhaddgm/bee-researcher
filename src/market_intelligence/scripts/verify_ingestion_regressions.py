"""Real DB/Redis regression for probe caching and cross-workspace ingestion.

Synthetic feeds only. Refuses production databases and external providers.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.database import SessionLocal, engine
from app.fetchers import DiscoveredItem, FetchResult
from app.models import AssistantWorkspace, Source, SourceItem, Topic
from app import ingestion_service as ingestion


async def main():
    cfg = get_settings()
    if cfg.environment != "test" or cfg.postgres_db != "assistant_test" or cfg.openai_ready or cfg.telegram_ready:
        raise RuntimeError("Only the isolated test database with external providers disabled is allowed")
    aids, sids = [uuid.uuid4(), uuid.uuid4()], [uuid.uuid4(), uuid.uuid4()]
    result = FetchResult("succeeded", (DiscoveredItem("Synthetic common headline", "https://example.org/common-news", published_at=datetime.now(timezone.utc)),), 1, 200, "https://example.org/feed", etag='"new-data"', last_modified="Mon, 05 Oct 2026 05:00:00 GMT")
    try:
        async with SessionLocal() as session:
            for aid in aids:
                session.add(AssistantWorkspace(id=aid, slug="ingestion-regression-"+aid.hex, name="Fixture", business_name="", status="draft", config={}))
            await session.flush()
            for aid, sid in zip(aids, sids):
                session.add(Source(id=sid, assistant_id=aid, source_key="SAME-SOURCE", name="Fixture", homepage_url="https://example.org", fetch_url="https://example.org/feed", adapter="rss", language="en", region="global", etag='"old-data"'))
            await session.commit()
        fetch = AsyncMock(return_value=result)
        with patch.object(ingestion.SourceFetcher, "fetch", new=fetch):
            await ingestion._ingest_source(sids[0], settings=cfg, force=True, store_items=False)
            assert fetch.call_args.args[0].etag is None, "Health probe sent ingestion cache validators"
            async with SessionLocal() as session:
                source = await session.get(Source, sids[0])
                assert source.etag == '"old-data"' and source.next_allowed_at is None, "Health probe acknowledged or delayed unstored content"
                assert (await session.scalar(select(func.count(SourceItem.id)).where(SourceItem.assistant_id.in_(aids)))) == 0

            # Keep both fetches in flight to detect a shared source-key lock.
            entered = 0
            both_entered = asyncio.Event()

            async def concurrent_feed(spec):
                nonlocal entered
                entered += 1
                if entered == 2:
                    both_entered.set()
                await asyncio.wait_for(both_entered.wait(), timeout=5)
                return result

            fetch.side_effect = concurrent_feed
            runs = await asyncio.gather(*(ingestion._ingest_source(sid, settings=cfg, force=True) for sid in sids))
            assert all(run.status == "succeeded" and run.items_inserted == 1 for run in runs), "Common media collided across assistants"
            fetch.side_effect = None
            again = await ingestion._ingest_source(sids[0], settings=cfg, force=True)
            assert again.items_inserted == 0, "Within-workspace deduplication stopped working"
            async with SessionLocal() as session:
                rows = (await session.execute(select(SourceItem.assistant_id, func.count(SourceItem.id)).where(SourceItem.assistant_id.in_(aids)).group_by(SourceItem.assistant_id))).all()
                assert dict(rows) == {aids[0]: 1, aids[1]: 1}
                source = await session.get(Source, sids[0])
                assert source.etag == '"new-data"', "Stored ingestion did not acknowledge its cache"
                session.add(Topic(id=uuid.uuid4(),assistant_id=aids[0],topic_key="CURRENT",name="Current response",definition="Fixture",positive_terms=["currenttextmarker"],negative_terms=[],threshold=.1,source_revision="fixture"))
                await session.commit()
            fetch.return_value=FetchResult("succeeded",(DiscoveredItem("Synthetic common headline","https://example.org/common-news",excerpt="currenttextmarker",published_at=datetime.now(timezone.utc)),),1,200,"https://example.org/feed")
            probe=await ingestion.run_source_probe(sids[0],assistant_id=aids[0],settings=cfg)
            assert probe["score_kind"]=="lexical_diagnostic" and probe["ai_state"]=="pending" and probe["no_ai_request"]
            assert "currenttextmarker" in probe["top_results"][0]["matched_terms"],"Probe used an old stored excerpt instead of the fetched text"
            fetch.return_value=FetchResult("succeeded",(),1,200,"https://example.org/feed")
            empty=await ingestion.run_source_probe(sids[0],assistant_id=aids[0],settings=cfg)
            assert empty["status"]=="degraded" and empty["texts_extractable"]==0 and not empty["top_results"],"Old stored news made an empty live response look healthy"
        print("Ingestion SQL/Redis regression passed: probe cache isolation, concurrent shared media, per-workspace deduplication")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id.in_(aids)))
            await session.commit()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
