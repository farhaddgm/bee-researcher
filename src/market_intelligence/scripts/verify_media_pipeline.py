"""Mandatory isolated PostgreSQL regression for AI selection and delivery gates.

No external provider or Telegram call is made. Refuse production databases.
Run after `alembic upgrade head`, with PYTHONPATH=src/market_intelligence.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import ArticleAnalysis, ArticleTopic, AssistantWorkspace, NormalizedArticle, Publication, Source, SourceItem, Topic
from app.openai_client import StructuredAnalysis
from app import pipeline_service as pipeline


async def main():
    config = get_settings()
    if config.environment != "test" or config.postgres_db != "assistant_test" or config.openai_ready or config.telegram_ready:
        raise RuntimeError("Integration test requires the isolated test database with real external providers disabled")
    ids = [uuid.uuid4(), uuid.uuid4()]
    article_ids = []
    cfg = config.model_copy(update={"external_analysis_approved": True, "openai_api_key": "fixture-not-a-real-key"})
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            for index, aid in enumerate(ids):
                session.add(AssistantWorkspace(id=aid, slug="pipeline-fixture-" + str(aid), name="AI" if index == 0 else "Sports", description="Isolated regression fixture", business_name="", status="active", config={"active_business_id": None, "runtime": {"relevance_threshold": .7}}))
            await session.flush()
            for index, aid in enumerate(ids):
                sid = uuid.uuid4()
                session.add(Source(id=sid, assistant_id=aid, source_key="fixture", name="Public fixture", homepage_url="https://example.org", fetch_url="https://example.org/feed", adapter="rss", language="en", region="global"))
                session.add(Topic(id=uuid.uuid4(), assistant_id=aid, topic_key="AI" if index == 0 else "SPORT", name="هوش مصنوعی" if index == 0 else "Sports", definition="Artificial intelligence news" if index == 0 else "Football news", positive_terms=["ChatGPT"] if index == 0 else ["football"], negative_terms=["sponsored"], threshold=.6, source_revision="fixture"))
                await session.flush()
                texts = ["New language model launch announced", "Unrelated football results", "Sponsored new language model"] if index == 0 else ["New language model launch announced"]
                for text in texts:
                    iid, article_id = uuid.uuid4(), uuid.uuid4()
                    article_ids.append(article_id)
                    session.add(SourceItem(id=iid, assistant_id=aid, source_id=sid, fingerprint=str(iid), title=text, url="https://example.org/" + str(iid), published_at=now))
                    await session.flush()
                    session.add(NormalizedArticle(id=article_id, assistant_id=aid, source_item_id=iid, canonical_url="https://example.org/" + str(iid), title=text, normalized_text=text, language="en", published_at=now, extraction_status="complete", extraction_method="fixture"))
            await session.commit()

        async def classify(_client, *, articles, topics, business, mission):
            assert not business, "A business-free workspace received a foreign business profile"
            assert len(topics) == 1, "Topics leaked across workspaces"
            return {(a["id"], t["topic_key"]): (.92 if "model" in a["text"].lower() else .03, "Fixture factual evidence") for a in articles for t in topics}

        with patch.object(pipeline, "classify_articles", side_effect=classify):
            await pipeline.score_pending_articles(cfg, limit=10, assistant_id=ids[0])
            await pipeline.score_pending_articles(cfg, limit=10, assistant_id=ids[1])
        async with SessionLocal() as session:
            rows = (await session.scalars(select(ArticleTopic).where(ArticleTopic.assistant_id.in_(ids)))).all()
            assert len(rows) == 4, "Missing or cross-project scores"
            primary = {r.article_id: r for r in rows if r.assistant_id == ids[0]}
            assert primary[article_ids[0]].selected and primary[article_ids[0]].ai_score == .92, "Cross-language AI news was excluded by the lexical filter"
            assert not primary[article_ids[1]].selected, "Unrelated news was selected"
            assert not primary[article_ids[2]].selected, "An approved negative term was ignored"
            hashes = [r.context_hash for r in rows]
            assert all(hashes) and hashes[0] != hashes[-1], "Project contexts share a scorer cache"

        good_analysis = StructuredAnalysis(payload={"headline": "Model launch", "news_summary": "A new model was announced.", "business_connection": "No business is configured.", "opportunity": "", "risk": "", "suggested_action": "Review the release", "time_horizon": "نامشخص", "confidence": .9, "facts": ["A model was announced"], "inferences": [], "topic_scores": [{"topic_key": "AI", "score": .92, "reason": "Model news"}]}, model=cfg.analysis_model, input_tokens=10, output_tokens=10, estimated_cost_usd=0)
        with patch.object(pipeline.OpenAIClient, "analyze", new=AsyncMock(return_value=good_analysis)) as model:
            result = await pipeline.analyze_pending_articles(cfg, limit=10, assistant_id=ids[0])
            assert result["model_calls"] == 1 and model.await_count == 1, "Negative/unrelated news consumed analysis calls"
        await pipeline.create_publication_previews(cfg, limit=10, assistant_id=ids[0])
        async with SessionLocal() as session:
            publication = (await session.scalars(select(Publication).where(Publication.assistant_id == ids[0]))).one()
            publication_id = publication.id
        with patch.object(pipeline, "_send_claimed_publication", new=AsyncMock(return_value={"status": "fixture-delivery"})) as send:
            assert (await pipeline.publish_publication(publication_id))["status"] == "fixture-delivery"
            assert send.await_count == 1
            async with SessionLocal() as session:
                row = await session.get(Publication, publication_id)
                row.status = "preview"
                workspace = await session.get(AssistantWorkspace, ids[0])
                workspace.config = {**workspace.config, "runtime": {"relevance_threshold": .95}}
                await session.commit()
            try:
                await pipeline.publish_publication(publication_id)
                raise AssertionError("A stale/below-threshold score reached delivery")
            except RuntimeError as error:
                assert "current AI relevance" in str(error)
            assert send.await_count == 1, "Delivery occurred despite an invalidated score"

        # An outage leaves review-only scores, retryable next run. Failed
        # attempts are reserved and counted, not refunded into an infinite loop.
        async with SessionLocal() as session:
            workspace = await session.get(AssistantWorkspace, ids[0])
            workspace.config = {**workspace.config, "runtime": {"relevance_threshold": .7}}
            await session.commit()
        with patch.object(pipeline, "classify_articles", new=AsyncMock(side_effect=RuntimeError("fixture outage"))):
            await pipeline.score_pending_articles(cfg, limit=10, rescore=True, assistant_id=ids[0])
        async with SessionLocal() as session:
            rows = (await session.scalars(select(ArticleTopic).where(ArticleTopic.assistant_id == ids[0]))).all()
            assert all(not r.selected and r.ai_score is None for r in rows), "Provider failure fell back to automatic publication"
        with patch.object(pipeline, "classify_articles", side_effect=classify):
            await pipeline.score_pending_articles(cfg, limit=10, assistant_id=ids[0])
        async with SessionLocal() as session:
            score = (await session.scalars(select(ArticleTopic).where(ArticleTopic.article_id == article_ids[0]))).one()
            assert score.selected, "AI-pending article was not retried"
            analysis = (await session.scalars(select(ArticleAnalysis).where(ArticleAnalysis.article_id == article_ids[0]))).one()
            analysis.status = "fallback"
            await session.commit()
        with patch.object(pipeline.OpenAIClient, "analyze", new=AsyncMock(return_value=good_analysis)):
            await pipeline.analyze_pending_articles(cfg, limit=10, assistant_id=ids[0])
        async with SessionLocal() as session:
            analysis = (await session.scalars(select(ArticleAnalysis).where(ArticleAnalysis.article_id == article_ids[0]))).one()
            assert analysis.status == "succeeded", "Temporary fallback was never upgraded after recovery"
        count, _ = await pipeline._model_budget(cfg, assistant_id=ids[0])
        assert count == 2, "Request ledger double-counted successful analysis"
        for _ in range(2):
            result = await pipeline._reserve_relevance_budget(cfg.model_copy(update={"model_daily_request_cap": 3}), ids[0], 100, job_type="analysis_model")
            if result:
                await pipeline._finish_job(result, status="failed", result={"input_chars": 100})
        count, _ = await pipeline._model_budget(cfg, assistant_id=ids[0])
        assert count == 3, "Failed API attempts escaped the daily budget"
        assert await pipeline._reserve_relevance_budget(cfg.model_copy(update={"model_daily_request_cap": 3}), ids[0], 100, job_type="analysis_model") is None
        # A realistic topic×article matrix used to exceed asyncpg's 32767
        # bound-parameter ceiling. Exercise the chunked write with real SQL.
        async with SessionLocal() as session:
            sid = (await session.scalars(select(Source.id).where(Source.assistant_id == ids[0]))).one()
            for n in range(15):
                session.add(Topic(id=uuid.uuid4(), assistant_id=ids[0], topic_key=f"BULK-{n}", name=f"Bulk topic {n}", definition="Fixture bulk topic", threshold=.7, positive_terms=["model"], negative_terms=[], source_revision="fixture"))
            for n in range(180):
                iid = uuid.uuid4()
                session.add(SourceItem(id=iid, assistant_id=ids[0], source_id=sid, fingerprint=str(iid), title=f"Bulk model {n}", url="https://example.org/" + str(iid), published_at=now))
                await session.flush()
                session.add(NormalizedArticle(id=uuid.uuid4(), assistant_id=ids[0], source_item_id=iid, title=f"Bulk model {n}", normalized_text="Model news", canonical_url="https://example.org/" + str(iid), published_at=now, extraction_status="complete", extraction_method="fixture"))
            await session.commit()
        bulk = await pipeline.score_pending_articles(config, limit=200, rescore=True, assistant_id=ids[0])
        assert bulk["scores"] == 183 * 16, "Large score matrix was truncated or failed to persist"
        print("Pipeline SQL integration passed: workspace isolation, optional business, multilingual AI selection, negative terms, live thresholds, stale delivery gate, outage retry, fallback recovery, failed-call budget.")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id.in_(ids)))
            await session.commit()
        await engine.dispose()


asyncio.run(main())
