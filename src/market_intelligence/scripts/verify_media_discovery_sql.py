"""Real isolated DB approval flow; synthetic providers, never production."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app import admin
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminUser, AssistantWorkspace, BusinessProfile, Source


async def main():
    cfg = get_settings()
    if cfg.environment != "test" or cfg.postgres_db != "assistant_test" or cfg.openai_ready or cfg.telegram_ready:
        raise RuntimeError("Media SQL test refuses production or configured external providers")
    aid = uuid.uuid4()
    try:
        async with SessionLocal() as session:
            owner = (await session.scalars(select(AdminUser).where(AdminUser.email == admin.owner_email()))).one()
            session.add(AssistantWorkspace(id=aid, slug="discovery-" + str(aid), name="Discovery fixture", business_name="", description="Public media", status="active", config={"active_business_id": None}))
            await session.commit()
            session.add(BusinessProfile(assistant_id=aid, business_name="Not selected", description="Must not silently activate", products_services="", target_customers="", markets="", output_tone="", source_revision="fixture"))
            await session.commit()
        context = await admin._assistant_media_context(aid)
        assert context["business"]["description"] == "", "Explicit no-business selection silently activated a profile"
        candidates = [{"name": "Channel " + n, "homepage_url": "https://t.me/" + n, "evidence": ["https://t.me/s/" + n + "/10"], "confidence": .9} for n in ("alpha", "beta")]
        with patch.object(admin, "_source_suggestions", new=AsyncMock(return_value={"suggestions": candidates, "draft_source": "fixture", "provider_status": "succeeded"})):
            result = await admin.create_source_suggestion(aid, admin.CatalogDraftRequest(name="人工知能"), owner)
        assert result["count"] == 2, "Shared platform channels collapsed to one publisher"
        alpha, beta = result["suggestions"]
        readable = SimpleNamespace(status="succeeded", items=["synthetic public post"], response_url="https://t.me/s/alpha")
        with patch.object(admin, "_catalog_draft", new=AsyncMock(side_effect=AssertionError("approval must not re-search a selected name"))), patch.object(admin.SourceFetcher, "fetch", new=AsyncMock(return_value=readable)):
            approved = await admin.decide_source_suggestion(aid, uuid.UUID(alpha["id"]), approve=True, user=owner)
        assert approved["status"] == "approved" and approved["removed"], "Approved card was retained"
        async with SessionLocal() as session:
            source = (await session.scalars(select(Source).where(Source.assistant_id == aid))).one()
            assert source.homepage_url == "https://t.me/alpha" and source.adapter == "telegram_public", "Approval silently changed the publisher or connector"
        rejected = await admin.decide_source_suggestion(aid, uuid.UUID(beta["id"]), approve=False, user=owner)
        assert rejected["removed"], "Rejected card was retained"
        refresh = [candidates[0], {"name": "Channel gamma", "homepage_url": "https://t.me/gamma", "evidence": ["https://t.me/s/gamma/1"], "confidence": .9}]
        with patch.object(admin, "_source_suggestions", new=AsyncMock(return_value={"suggestions": refresh})) as provider:
            result = await admin.create_source_suggestion(aid, admin.CatalogDraftRequest(name="人工知能", page=1), owner)
        assert result["count"] == 1 and result["suggestions"][0]["name"] == "Channel gamma", "Refresh repeated an approved publisher"
        assert "https://t.me/beta" in provider.call_args.kwargs["exclude"], "Refresh forgot rejected results"
        async with SessionLocal() as session:
            item = await session.get(AssistantWorkspace, aid)
            config = dict(item.config)
            config["source_suggestions"] = [{"id": str(uuid.uuid4()), "status": "pending", "name": "RSS fallback", "draft": {"name": "RSS fallback", "homepage_url": "https://example.org/", "fetch_url": "https://example.org/", "adapter": "html"}}]
            suggestion_id = uuid.UUID(config["source_suggestions"][0]["id"])
            item.config = config
            await session.commit()
        with patch.object(admin.SourceFetcher, "discover_feeds", new=AsyncMock(return_value=[("https://example.org/feed", "rss")])), patch.object(admin.SourceFetcher, "fetch", new=AsyncMock(return_value=readable)):
            await admin.decide_source_suggestion(aid, suggestion_id, approve=True, user=owner)
        async with SessionLocal() as session:
            source = (await session.scalars(select(Source).where(Source.assistant_id == aid, Source.name == "RSS fallback"))).one()
            assert source.adapter == "rss" and source.fetch_url == "https://example.org/feed", "Old draft replaced the actually verified connector"
        print("Media SQL integration passed: scoped suggestions, distinct channels, exact publisher approval, readable connector, accept/reject cleanup, refresh history; zero real provider or Telegram calls.")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id == aid))
            await session.commit()
        await engine.dispose()


asyncio.run(main())
