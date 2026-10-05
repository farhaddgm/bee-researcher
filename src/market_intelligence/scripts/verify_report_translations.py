"""Real PostgreSQL tests of scoped translation repair; no external calls."""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app import pipeline_service as pipeline
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import ArticleAnalysis, AssistantWorkspace, NormalizedArticle, Publication, Source, SourceItem
from app.openai_client import StructuredAnalysis
from app.report_language import LANGUAGE_REVISION, analysis_text, language_issues


async def main():
    config = get_settings()
    if config.environment != "test" or config.postgres_db != "assistant_test" or config.openai_ready or config.telegram_ready:
        raise RuntimeError("Requires isolated test DB and disabled external providers")
    ids = [uuid.uuid4(), uuid.uuid4()]
    cfg = config.model_copy(update={"external_analysis_approved": True, "openai_api_key": "fixture-not-a-real-key"})
    original_title = "Google announced a new model"
    original_text = "Google announced a new language model. It supports new reasoning tasks."
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            for aid in ids:
                session.add(AssistantWorkspace(id=aid, slug="translation-fixture-" + str(aid), name="ترجمه", business_name="", status="active", config={"active_business_id": None}))
            await session.flush()
            for index in range(5):
                aid = ids[int(index == 4)]
                sid, iid, nid, analysis_id = (uuid.uuid4() for _ in range(4))
                session.add(Source(id=sid, assistant_id=aid, source_key="tr-" + str(index), name="TechCrunch", homepage_url="https://example.org", fetch_url="https://example.org/feed", adapter="rss", language="en", output_language="fa", region="global"))
                await session.flush()
                session.add(SourceItem(id=iid, assistant_id=aid, source_id=sid, fingerprint=str(iid), title=original_title, url="https://example.org/" + str(iid), published_at=now))
                await session.flush()
                session.add(NormalizedArticle(id=nid, assistant_id=aid, source_item_id=iid, canonical_url="https://example.org/" + str(iid), title=original_title, normalized_text=original_text, language="en", published_at=now, extraction_status="complete", extraction_method="fixture"))
                await session.flush()
                session.add(ArticleAnalysis(id=analysis_id, assistant_id=aid, article_id=nid, status="fallback", headline=original_title, news_summary=original_text, business_connection="این خبر بر مشتریان بانکی تأثیر دارد.", opportunity="", risk="", suggested_action="", time_horizon="نامشخص", confidence=.4, facts=[original_text], inferences=["مشتریان بانکی"], citations=[{"url": "https://example.org/" + str(iid)}], topic_scores={"AI": .91}, model="deterministic-fallback"))
                await session.flush()
                session.add(Publication(id=uuid.uuid4(), assistant_id=aid, analysis_id=analysis_id, idempotency_key=str(analysis_id), status="published" if index == 3 else "preview", message_text="legacy mixed report", audit={"immutable_fixture": True}))
            await session.commit()
        dry = await pipeline.repair_report_translations(cfg, assistant_id=ids[0])
        assert dry["candidates"] == 3 and dry["translated"] == 0

        async def translate(*, reports, output_language):
            assert len(reports) == 3 and output_language == "fa", "Repair wasn't a bounded workspace batch"
            assert all("بانکی" not in str(fields) for fields in reports.values()), "Invented fallback banking claims entered translation"
            return StructuredAnalysis(payload={"reports": [{"report_id": key, "headline": "گوگل مدل جدیدی معرفی کرد", "news_summary": "گوگل مدل زبانی تازه‌ای معرفی کرد. این مدل از وظایف استدلالی جدید پشتیبانی می‌کند.", "business_connection": "تحلیل تکمیلی هنوز آماده نیست.", "opportunity": "", "risk": "", "suggested_action": "تحلیل تکمیلی هنوز آماده نیست.", "time_horizon": "نامشخص", "facts": ["گوگل مدل زبانی تازه‌ای معرفی کرد."], "inferences": [], "_report_language": {"output_language": "fa", "language_revision": LANGUAGE_REVISION}} for key in reports]}, model="fixture", input_tokens=100, output_tokens=50, estimated_cost_usd=.001)
        with patch.object(pipeline.OpenAIClient, "translate_reports", side_effect=translate) as translator, patch.object(pipeline.TelegramClient, "send_analysis", new=AsyncMock(side_effect=AssertionError("Repair sent Telegram"))):
            applied = await pipeline.repair_report_translations(cfg, assistant_id=ids[0], apply=True)
            assert applied["translated"] == 3 and applied["failed"] == 0 and translator.await_count == 1
        async with SessionLocal() as session:
            analyses = (await session.scalars(select(ArticleAnalysis).where(ArticleAnalysis.assistant_id == ids[0]))).all()
            publications = (await session.scalars(select(Publication).where(Publication.assistant_id == ids[0]))).all()
            assert sum(a.input_tokens for a in analyses) == 100 and sum(a.output_tokens for a in analyses) == 50
            for article in (await session.scalars(select(NormalizedArticle).where(NormalizedArticle.assistant_id.in_(ids)))).all():
                assert article.title == original_title and article.normalized_text == original_text
            for analysis in analyses:
                assert analysis.topic_scores == {"AI": .91} and analysis.confidence == .4 and analysis.status == "fallback"
            for publication in publications:
                if publication.status == "published":
                    assert publication.message_text == "legacy mixed report"
                else:
                    assert "گوگل مدل جدیدی معرفی کرد" in publication.message_text and "Google announced" not in publication.message_text
            other = (await session.scalars(select(Publication).where(Publication.assistant_id == ids[1]))).one()
            assert other.message_text == "legacy mixed report", "Another workspace was changed"
            assert not language_issues(analysis_text(next(a for a in analyses if a.headline.startswith("گوگل"))), "fa")
        again = await pipeline.repair_report_translations(cfg, assistant_id=ids[0], apply=True)
        assert again["candidates"] == 0, "Repair is not idempotent"
        with patch.object(pipeline.OpenAIClient, "translate_reports", new=AsyncMock(side_effect=RuntimeError("fixture provider outage"))):
            failed = await pipeline.repair_report_translations(cfg, assistant_id=ids[1], apply=True)
            assert failed["failed"] == 1 and failed["translated"] == 0
        async with SessionLocal() as session:
            other = (await session.scalars(select(Publication).where(Publication.assistant_id == ids[1]))).one()
            assert other.message_text == "legacy mixed report", "Provider failure erased evidence"
        print("Translation SQL integration passed: full fields, bounded batch, original evidence, workspace isolation, no Telegram, unchanged scores/status, exact token accounting, idempotency, retryable provider failure")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id.in_(ids)))
            await session.commit()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
