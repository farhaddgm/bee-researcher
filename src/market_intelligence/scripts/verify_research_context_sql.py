"""Real isolated SQL + deterministic AI contract; refuses live/provider-enabled DBs."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import delete, func, select
from app import admin, contenter, pipeline_service as pipeline, research_context as context
from app.business_context import ContextError, full_article_hash
from app.config import get_settings
from app.openai_client import StructuredAnalysis
from app.telegram_delivery import TelegramPermissionStatus
from app.database import SessionLocal, engine
from app.models import (AdminUser, AssistantWorkspace, BusinessProfile, Topic, Source, SourceItem,
    NormalizedArticle, ProjectResearchContext, ResearchContextPreview, ContenterBusinessLink,
    ContenterBusinessSnapshot, NewsBusinessAssessment, ArticleAnalysis, Publication)


class DeterministicAI:
    configured = True
    business_score = .9
    calls = 0

    def __init__(self, *_): pass
    def provider_health(self): return {"state":"healthy","code":None}

    async def analyze(self, **kwargs):
        assert kwargs["business_profile"]["research_brief"]["claims"]==[],"Private business facts leaked to public report generation"
        assert kwargs["output_language"]=="fa"
        return StructuredAnalysis(payload={"headline":"پیشرفت فناوری باتری خودرو","news_summary":"فناوری باتری خودرو در تولید بهبود یافته است.",
            "business_connection":"این خبر با موضوع فناوری باتری مرتبط است.","opportunity":"بررسی فرصت‌های فناوری باتری پیشنهاد می‌شود.",
            "risk":"اطلاعات بیشتری برای ارزیابی ریسک لازم است.","suggested_action":"منبع اصلی خبر را مرور کنید.","time_horizon":"کوتاه‌مدت",
            "confidence":.9,"facts":["بهبود تولید باتری در خبر گزارش شده است."],"inferences":["بررسی تحولات این فناوری می‌تواند مفید باشد."],
            "topic_scores":[{"topic_key":"T-battery","score":.92}],"_report_language":{"output_language":"fa"}},
            model=get_settings().analysis_model,input_tokens=100,output_tokens=200,estimated_cost_usd=0)

    async def draft_json(self, *, user_payload, schema_name, **_):
        type(self).calls += 1
        articles=user_payload["articles"]
        if schema_name=="article_relevance":
            return {"scores":[{"article_id":a["article_id"],"topic_key":t["topic_key"],"score":.92,"confidence":.95,
                "reason":"Direct battery technology coverage.","excluded":False,"evidence":["Vehicle battery technology"]}
                for a in articles for t in user_payload["approved_topics"]]}
        if schema_name=="news_business_relationship":
            return {"assessments":[{"article_id":a["article_id"],"score":type(self).business_score,"confidence":.95,
                "relation":"technology","reason":"Battery suppliers are affected.","article_evidence":["Vehicle battery technology"],
                "business_evidence":["section:OVERVIEW"],"impact":"positive","urgency":"short_term"} for a in articles]}
        raise AssertionError(schema_name)


class NoNetworkTelegram:
    sends = 0
    def __init__(self, *_): pass
    async def check_permissions(self):
        return TelegramPermissionStatus(True,"synthetic","administrator",True,True,True)
    async def send_analysis(self, message, **_):
        assert "Battery systems" not in message and "Vehicle manufacturers" not in message
        type(self).sends += 1
        return [12345]


async def expect_error(code, action):
    try: await action()
    except ContextError as exc: assert exc.code==code,(exc.code,code)
    else: raise AssertionError("Expected "+code)


async def create_preview(aid, actor, request, cfg):
    with patch("app.openai_client.OpenAIClient",DeterministicAI),patch.object(pipeline,"OpenAIClient",DeterministicAI):
        result=await context.save_preview(aid,actor,request,cfg)
    return result


async def activate(aid,actor,preview,cfg):
    async with SessionLocal() as session:
        record=await context.activate_preview(session,aid,actor,uuid.UUID(preview["preview_id"]),cfg)
        await session.commit()
        return record.generation


async def main():
    cfg=get_settings()
    if cfg.environment!="test" or cfg.postgres_db!="assistant_test" or cfg.openai_ready or cfg.telegram_ready or cfg.scheduler_enabled:
        raise RuntimeError("Refusing non-isolated environment or configured external providers")
    aid,other,actor,article_id,topic_id,source_id,item_id=[uuid.uuid4() for _ in range(7)]
    try:
        async with SessionLocal() as session:
            user=await session.scalar(select(AdminUser).where(AdminUser.email==admin.owner_email()))
            if not user:
                user=AdminUser(id=actor,username="owner",email=admin.owner_email(),role="admin",password_hash=admin._hash_password(cfg.admin_bootstrap_password.get_secret_value()))
                session.add(user)
            actor=user.id
            session.add_all([AssistantWorkspace(id=aid,slug="context-"+str(aid),name="Synthetic batteries",business_name="",status="active",description="Technology news",config={"active_business_id":None}),
                            AssistantWorkspace(id=other,slug="context-"+str(other),name="Other project",business_name="",status="active",config={"active_business_id":None})])
            await session.flush()
            local_id=int(await session.scalar(select(func.max(BusinessProfile.id))) or 0)+1
            session.add(BusinessProfile(id=local_id,assistant_id=aid,business_name="Acme",description="Acme produces battery technology.",products_services="Battery systems",
                target_customers="Vehicle manufacturers",markets="Europe",output_language="fa",output_tone="Neutral",source_revision="fixture"))
            session.add(Topic(id=topic_id,assistant_id=aid,topic_key="T-battery",name="Batteries",definition="Vehicle batteries",threshold=.5,source_revision="fixture"))
            session.add(Source(id=source_id,assistant_id=aid,source_key="S-fixture",name="Test source",homepage_url="https://example.test",fetch_url="https://example.test/feed",adapter="rss"))
            await session.flush()
            session.add(SourceItem(id=item_id,assistant_id=aid,source_id=source_id,fingerprint="a"*64,title="Vehicle battery technology",url="https://example.test/news"))
            await session.flush()
            session.add(NormalizedArticle(id=article_id,assistant_id=aid,source_item_id=item_id,title="Vehicle battery technology",canonical_url="https://example.test/news",
                normalized_text="Vehicle battery technology improves manufacturing.",extraction_status="complete",extraction_method="fixture",content_hash="a"*64))
            await session.commit()
        # Compiling and sampling is read-only for news and project configuration.
        request=context.PreviewRequest(source="local",mode="focused",local_business_id=local_id,consent_ai=True,rollout="shadow")
        preview=await create_preview(aid,actor,request,cfg)
        assert preview["result"]["live_ready"] and preview["result"]["evaluated"]==1,preview
        async with SessionLocal() as session:
            assert await session.get(ProjectResearchContext,aid) is None
            assert await session.scalar(select(func.count(NewsBusinessAssessment.id)).where(NewsBusinessAssessment.assistant_id==aid))==0
            assert await session.scalar(select(func.count(ArticleAnalysis.id)).where(ArticleAnalysis.assistant_id==aid))==0
            assert await session.scalar(select(func.count(Publication.id)).where(Publication.assistant_id==aid))==0
            assert (await session.get(AssistantWorkspace,aid)).config=={"active_business_id":None}
        await activate(aid,actor,preview,cfg)
        # A one-time actor/project-bound preview cannot be replayed or borrowed.
        async def replay():
            async with SessionLocal() as s:await context.activate_preview(s,aid,actor,uuid.UUID(preview["preview_id"]),cfg)
        await expect_error("preview_expired_or_used",replay)
        second=await create_preview(aid,actor,request,cfg)
        async def foreign():
            async with SessionLocal() as s:await context.activate_preview(s,other,actor,uuid.UUID(second["preview_id"]),cfg)
        await expect_error("preview_missing",foreign)
        async def other_actor():
            async with SessionLocal() as s:await context.activate_preview(s,aid,uuid.uuid4(),uuid.UUID(second["preview_id"]),cfg)
        await expect_error("preview_missing",other_actor)
        async with SessionLocal() as s:
            topic=await s.get(Topic,topic_id);topic.threshold=.6;await s.commit()
        async def changed():
            async with SessionLocal() as s:await context.activate_preview(s,aid,actor,uuid.UUID(second["preview_id"]),cfg)
        await expect_error("preview_configuration_changed",changed)
        # Shadow stores business diagnostics but keeps the original topic selection.
        with patch.object(pipeline,"OpenAIClient",DeterministicAI):
            await pipeline.score_pending_articles(cfg,limit=10,assistant_id=aid)
        async with SessionLocal() as s:
            article=await s.get(NormalizedArticle,article_id)
            decision=(await pipeline._article_decisions(s,[article],cfg))[article_id]
            assert decision["publishable"] and decision["business_shadow"]
        live_request=request.model_copy(update={"rollout":"live"})
        live=await create_preview(aid,actor,live_request,cfg)
        generation=await activate(aid,actor,live,cfg)
        with patch.object(pipeline,"OpenAIClient",DeterministicAI):
            result=await pipeline.score_pending_articles(cfg,limit=10,assistant_id=aid)
        async with SessionLocal() as s:
            article=await s.get(NormalizedArticle,article_id)
            decision=(await pipeline._article_decisions(s,[article],cfg))[article_id]
            assert decision["publishable"] and decision["business_gate_passed"],decision
            approved=await context.resolve_context(s,aid,cfg)
            assert approved.record.generation==generation
            assert await context.resolve_context(s,other,cfg) is None
            assert approved.provenance(article,cfg.analysis_model)["content_hash"]==full_article_hash(article.title,article.normalized_text)
        with patch.object(pipeline,"OpenAIClient",DeterministicAI):
            analyzed=await pipeline.analyze_pending_articles(cfg,limit=10,assistant_id=aid)
        assert analyzed["succeeded"]==1,analyzed
        await pipeline.create_publication_previews(cfg,limit=10,assistant_id=aid)
        async with SessionLocal() as s:
            analysis=await s.scalar(select(ArticleAnalysis).where(ArticleAnalysis.assistant_id==aid))
            assert analysis.research_provenance["generation"]==str(generation)
            publication=await s.scalar(select(Publication).where(Publication.assistant_id==aid))
            publication_id=publication.id
            analysis.research_provenance={};await s.commit()
        # Final delivery must reject an old report even when both relevance scores passed.
        try:await pipeline.publish_publication(publication_id)
        except RuntimeError as exc:assert "approved research context" in str(exc),str(exc)
        else:raise AssertionError("Stale report was publishable")
        with patch.object(pipeline,"OpenAIClient",DeterministicAI):
            repaired=await pipeline.analyze_pending_articles(cfg,limit=10,assistant_id=aid)
        assert repaired["succeeded"]==1,repaired
        with patch.object(pipeline,"TelegramClient",NoNetworkTelegram):
            sent=await pipeline.publish_publication(publication_id)
            repeat=await pipeline.publish_publication(publication_id)
        assert sent["status"]=="published" and repeat["idempotent"] and NoNetworkTelegram.sends==1
        # Switching to a new shadow proposal must retain the previous LIVE policy.
        shadow_proposal=await create_preview(aid,actor,request.model_copy(update={"business_threshold":.99}),cfg)
        await activate(aid,actor,shadow_proposal,cfg)
        async with SessionLocal() as s:
            actual=await context.resolve_context(s,aid,cfg)
            proposed=await context.resolve_context(s,aid,cfg,shadow=True)
            assert actual.live and actual.record.generation==generation and actual.record.business_threshold==.5
            assert not proposed.live and proposed.record.business_threshold==.99
        assert (await context.view_context(aid,cfg))["shadow_pending"]
        # Source text changes invalidate both T and B, even after the old 6000-char prefix.
        async with SessionLocal() as s:
            article=await s.get(NormalizedArticle,article_id);article.normalized_text+=" changed tail";await s.commit()
        async with SessionLocal() as s:
            article=await s.get(NormalizedArticle,article_id)
            assert not (await pipeline._article_decisions(s,[article],cfg))[article_id]["publishable"]
        # Changed/removed local business cannot silently fall back to another profile.
        async with SessionLocal() as s:
            local=await s.get(BusinessProfile,local_id);local.description="Changed approved description.";await s.commit()
        async with SessionLocal() as s:
            effective=await context.resolve_context(s,aid,cfg);assert effective.state=="business_changed" and effective.profile is None
        # External pinned snapshots: sync is not approval; relinking revokes old context.
        payload=contenter.normalize_export({"schemaVersion":1,"business":{"id":"biz-fixture","name":"Acme","status":"ACTIVE"},
            "sections":[{"key":key,"content":"Acme produces battery technology." if key=="OVERVIEW" else "","source":"ADMIN"} for key in contenter.SECTION_KEYS],
            "facts":[{"id":"fact-fixture","label":"Product","value":"Battery technology","source":"ADMIN","verified":True,"isActive":True,"validUntil":None}],
            "terms":[],"notes":[],"references":[],"assets":[]},"biz-fixture")
        async with SessionLocal() as s:
            s.add(ContenterBusinessLink(assistant_id=aid,external_business_id="biz-fixture",business_name="Acme",generation=uuid.uuid4(),state="healthy",version=1,last_success_at=datetime.now(timezone.utc)))
            s.add(ContenterBusinessSnapshot(assistant_id=aid,external_business_id="biz-fixture",version=1,content_hash=contenter.export_hash(payload),payload=payload));await s.commit()
        remote=context.PreviewRequest(source="contenter",mode="focused",rollout="live",consent_ai=True)
        preview=await create_preview(aid,actor,remote,cfg);await activate(aid,actor,preview,cfg)
        async with SessionLocal() as s:
            link=await s.get(ContenterBusinessLink,aid);link.version=2
            newer={**payload,"sections":[{**x,"content":"New approved battery research."} if x["key"]=="OVERVIEW" else x for x in payload["sections"]]}
            s.add(ContenterBusinessSnapshot(assistant_id=aid,external_business_id="biz-fixture",version=2,content_hash=contenter.export_hash(newer),payload=newer));await s.commit()
        view=await context.view_context(aid,cfg)
        assert view["active"]["snapshot_version"]==1 and view["active"]["latest_version"]==2
        assert "New approved" not in str(view["active"]["brief"])
        assert view["active"]["state"]=="ready",view
        # A withdrawn fact must stop use of the old pinned claim, not just new approvals.
        async with SessionLocal() as s:
            link=await s.get(ContenterBusinessLink,aid);link.version=3
            withdrawn={**newer,"facts":[{**x,"verified":False} for x in newer["facts"]]}
            s.add(ContenterBusinessSnapshot(assistant_id=aid,external_business_id="biz-fixture",version=3,content_hash=contenter.export_hash(withdrawn),payload=withdrawn));await s.commit()
        async with SessionLocal() as s:
            effective=await context.resolve_context(s,aid,cfg)
            assert effective.state=="business_facts_withdrawn" and effective.profile is None
        async with SessionLocal() as s:
            link=await s.get(ContenterBusinessLink,aid);link.state="access_revoked";await s.commit()
        assert (await context.view_context(aid,cfg))["active"]["brief"] is None
        async with SessionLocal() as s:
            assert (await context.resolve_context(s,aid,cfg)).profile is None
            link=await s.get(ContenterBusinessLink,aid);link.state="healthy";link.generation=uuid.uuid4();await s.commit()
        assert (await context.view_context(aid,cfg))["active"]["state"]=="business_link_changed"
        # Provider outages never activate live settings and never fabricate a model score.
        offline=await create_preview(other,actor,context.PreviewRequest(rollout="live"),cfg)
        async def no_evaluation():
            async with SessionLocal() as s:await context.activate_preview(s,other,actor,uuid.UUID(offline["preview_id"]),cfg)
        await expect_error("evaluated_preview_required",no_evaluation)
        print("Research context SQL passed: real migrations, AI preview, actor/project binding, replay and topic-change rejection, shadow/live scores, report provenance repair, private-fact protection, one idempotent synthetic delivery, full-text invalidation, local changes, pinned versions, withdrawn facts, revocation and relink protection.")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id.in_([aid,other])))
            await session.commit()
        await engine.dispose()


asyncio.run(main())
