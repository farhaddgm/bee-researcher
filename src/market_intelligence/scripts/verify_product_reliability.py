"""SQL product regression; isolated DB only, mock AI, never send Telegram."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app import pipeline_service as p
from app.ai_relevance import classify_articles
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import ArticleAnalysis, ArticleTopic, AssistantWorkspace, BusinessProfile, NormalizedArticle, Publication, Source, SourceItem, Topic
from app.openai_client import StructuredAnalysis
from app.product_status import operations_status


async def main():
    cfg=get_settings()
    if cfg.environment!="test" or cfg.postgres_db!="assistant_test" or cfg.openai_ready or cfg.telegram_ready:
        raise RuntimeError("This regression requires the isolated test DB and disabled external providers")
    paid=cfg.model_copy(update={"external_analysis_approved":True,"openai_api_key":SecretStr("not-a-real-key")})
    aids=[uuid.uuid4(),uuid.uuid4()]
    articles=[];reports=[];pubs=[]
    now=datetime.now(timezone.utc)
    try:
        async with SessionLocal() as db:
            for index,aid in enumerate(aids):
                config={"runtime":{"analysis_model":"gpt-6-luna","timezone":"Pacific/Honolulu","relevance_threshold":0}}
                if index==0:config["active_business_id"]=None
                db.add(AssistantWorkspace(id=aid,slug="product-fixture-"+str(aid),name="General AI" if index==0 else "Business B",business_name="",description="Independent project",status="active",config=config))
            await db.flush()
            # Backoffice/legacy seeds assign small profile IDs explicitly; do not
            # trust an unadvanced SERIAL sequence in a populated test database.
            profile_id=int(await db.scalar(select(func.max(BusinessProfile.id))) or 0)+1
            db.add(BusinessProfile(id=profile_id,assistant_id=aids[1],business_name="Isolated business B",description="Only B context",products_services="B product",target_customers="B customers",markets="B market",revenue_model="",strategic_goals="",competitors=[],sensitivities=[],output_language="fa",output_tone="short",source_revision="fixture"))
            for index,aid in enumerate(aids):
                sid=uuid.uuid4()
                db.add(Source(id=sid,assistant_id=aid,source_key="product",name="Fixture source",homepage_url="https://example.org",fetch_url="https://example.org/rss",adapter="rss",language="en",output_language="fa",region="global"))
                db.add(Topic(id=uuid.uuid4(),assistant_id=aid,topic_key="AI",name="AI",definition="AI model launches",positive_terms=["model"],negative_terms=[],threshold=.7,source_revision="fixture"))
                await db.flush()
                for title in (["model launch","model rejected","model pending","model published"] if index==0 else ["model B launch"]):
                    iid,nid,rid,pid=uuid.uuid4(),uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
                    articles.append(nid);reports.append(rid);pubs.append(pid)
                    db.add(SourceItem(id=iid,assistant_id=aid,source_id=sid,fingerprint=str(iid),title=title,url="https://example.org/"+str(iid),published_at=now))
                    await db.flush()
                    db.add(NormalizedArticle(id=nid,assistant_id=aid,source_item_id=iid,title=title,normalized_text=title,canonical_url="https://example.org/"+str(iid),language="en",published_at=now,extraction_status="complete",extraction_method="fixture"))
                    await db.flush()
                    db.add(ArticleAnalysis(id=rid,assistant_id=aid,article_id=nid,status="fallback",headline=title,news_summary=title,business_connection="",opportunity="",risk="",suggested_action="",time_horizon="",confidence=.4,facts=[title],inferences=[],citations=[],topic_scores={},model="deterministic-fallback",created_at=now))
                    await db.flush()
                    db.add(Publication(id=pid,assistant_id=aid,analysis_id=rid,idempotency_key=str(pid),status="published" if "published" in title else "preview",message_text="immutable published receipt" if "published" in title else "old preview",audit={}))
            await db.commit()

        async def classify(client,*,articles,topics,business,mission,max_input_chars=6000):
            transport=AsyncMock()
            transport.draft_json.return_value={"scores":[
                {"article_id":a["id"],"topic_key":t["topic_key"],
                 "score":.02 if "rejected" in a["title"] else .91,
                 "reason":"Verified fixture evidence","confidence":.9,
                 "evidence":[f"a{index}-title-0"],"excluded":False}
                for index,a in enumerate(articles) for t in topics
            ]}
            return await classify_articles(transport,articles=articles,topics=topics,
                                           business=business,mission=mission,max_input_chars=max_input_chars)
        with patch.object(p,"classify_articles",side_effect=classify):
            for aid in aids:
                result=await p.score_pending_articles(paid,limit=20,assistant_id=aid)
                assert result["semantic"]=="succeeded",f"Isolated classifier failed: {result['semantic']}"
        async with SessionLocal() as db:
            await db.execute(delete(ArticleTopic).where(ArticleTopic.article_id==articles[2]))
            await db.commit()
        metrics=await p.pipeline_metrics(assistant_id=aids[0])
        assert metrics["pending_ai_articles"]==1,"Metrics use deployment model instead of workspace model"
        triage=await p.list_relevance_assessments(assistant_id=aids[0],limit=1,state="pending")
        assert triage["total"]==1 and triage["articles"][0]["id"]==str(articles[2])
        assert (await p.list_relevance_assessments(assistant_id=aids[0],query="%"))["total"]==0,"Search wildcard was not literal"
        first=await p.list_relevance_assessments(assistant_id=aids[0],limit=1)
        second=await p.list_relevance_assessments(assistant_id=aids[0],limit=1,offset=1)
        assert first["articles"][0]["id"]!=second["articles"][0]["id"],"Pagination returned a duplicate article"

        effective=await p.settings_for_assistant(paid,aids[0])
        attempt=await p._reserve_relevance_budget(effective,aids[0],100,job_type="analysis_model",article_id=articles[0])
        assert attempt is not None
        assert await p._reserve_relevance_budget(effective,aids[0],100,job_type="analysis_model",article_id=articles[0]) is None,"Concurrent duplicate paid analysis was reserved"
        await p._finish_job(attempt,status="failed",result={"input_chars":100,"model":effective.analysis_model},error="provider_quota_exhausted")
        status=await operations_status(assistant_id=aids[0])
        assert status["model"]=="gpt-6-luna" and status["timezone"]=="Pacific/Honolulu"
        assert status["budgets"]["analysis_model"]["used_requests"]==1
        assert status["provider"]["state"]=="not_configured","Missing approval must not be called healthy"
        before=await p._model_budget(effective,assistant_id=aids[0])
        with patch.object(p.OpenAIClient,"provider_health",return_value={"state":"cooldown","code":"provider_quota_exhausted"}),patch.object(p.OpenAIClient,"analyze",new=AsyncMock(side_effect=AssertionError("Cooldown called AI"))):
            await p.reanalyze_fallback_articles(paid,assistant_id=aids[0],limit=5)
        assert await p._model_budget(effective,assistant_id=aids[0])==before,"Cooldown consumed a fictitious model request"

        async def analyze(**kwargs):
            profile=kwargs["business_profile"]
            if kwargs["article_title"]=="model B launch":assert profile["business_name"]=="Isolated business B"
            else:assert profile["business_name"]=="General AI" and "Only B context" not in str(profile)
            return StructuredAnalysis(payload={"headline":"معرفی مدل جدید","news_summary":"مدل جدیدی معرفی شد.","business_connection":"ارتباط با موضوع بررسی شد.","opportunity":"","risk":"","suggested_action":"خبر بررسی شود.","time_horizon":"نامشخص","confidence":.9,"facts":["مدل تازه معرفی شد."],"inferences":[],"topic_scores":[{"topic_key":"AI","score":.91,"reason":"خبر مدل"}],"_report_language":{"output_language":"fa"}},model="gpt-6-luna",input_tokens=10,output_tokens=10,estimated_cost_usd=0)
        with patch.object(p.OpenAIClient,"analyze",side_effect=analyze) as ai,patch.object(p.TelegramClient,"send_analysis",new=AsyncMock(side_effect=AssertionError("Recovery published"))):
            repaired=await p.reanalyze_fallback_articles(paid,assistant_id=aids[0],limit=5)
            assert repaired["succeeded"]==1 and ai.await_count==1,"Rejected, pending or published items entered AI recovery"
            repaired_b=await p.reanalyze_fallback_articles(paid,assistant_id=aids[1],limit=5)
            assert repaired_b["succeeded"]==1 and ai.await_count==2
        async with SessionLocal() as db:
            sent=await db.get(Publication,pubs[3]);sent_report=await db.get(ArticleAnalysis,reports[3])
            assert sent.message_text=="immutable published receipt" and sent_report.headline=="model published"
            translated=await db.get(ArticleAnalysis,reports[0]);translated.status="fallback";await db.commit()
        regen=await p.regenerate_fallback_analyses(limit=20,assistant_id=aids[0])
        assert regen["translations_preserved"]>=1
        async with SessionLocal() as db:
            assert (await db.get(ArticleAnalysis,reports[0])).headline=="معرفی مدل جدید","Full translation was overwritten"
            assert (await db.get(ArticleAnalysis,reports[3])).headline=="model published","Published analysis was mutated"
        report_end=now+timedelta(seconds=5)
        ra=await p.generate_weekly_report(now=report_end,assistant_id=aids[0]);rb=await p.generate_weekly_report(now=report_end,assistant_id=aids[1])
        assert ra["report_id"]!=rb["report_id"],"Weekly report identity crossed projects"
        assert (await p.generate_weekly_report(now=report_end,assistant_id=aids[0]))["report_id"]==ra["report_id"],"Weekly report retry returned a nonexistent ID"
        assert rb["trends"]==[{"topic":"AI","articles":1}],"Weekly trend ignores current AI evidence"
        print("Product SQL passed: workspace recovery, optional business, model/timezone metrics, honest status, budget duplicate/cooldown guards, translation/send immutability, decision filters, weekly isolation/idempotency")
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id.in_(aids)))
            await db.commit()
        await engine.dispose()


if __name__=="__main__":asyncio.run(main())
