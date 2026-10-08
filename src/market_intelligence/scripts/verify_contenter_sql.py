"""Real SQL behavior against an isolated DB; no real provider, Telegram or Contenter calls."""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select
from app import contenter, admin
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminUser, AssistantWorkspace, ContenterBusinessSnapshot, ContenterBusinessLink, BusinessProfile


def profile(business_id="business-a", text="First version"):
    return contenter.normalize_export({"schemaVersion":1,"business":{"id":business_id,"name":"Business A","status":"ACTIVE"},
        "sections":[{"key":key,"content":text if key=="OVERVIEW" else ""} for key in contenter.SECTION_KEYS],
        "facts":[],"terms":[],"notes":[],"references":[],"assets":[]},business_id)


async def main():
    cfg=get_settings()
    if cfg.environment!="test" or cfg.postgres_db!="assistant_test" or cfg.openai_ready or cfg.telegram_ready:
        raise RuntimeError("This test refuses production or configured external providers")
    aid,other=uuid.uuid4(),uuid.uuid4()
    try:
        async with SessionLocal() as session:
            owner=(await session.scalars(select(AdminUser).where(AdminUser.email==admin.owner_email()))).one()
            session.add_all([AssistantWorkspace(id=aid,slug="contenter-"+str(aid),name="Contenter fixture",business_name="",status="active",config={"active_business_id":None}),
                             AssistantWorkspace(id=other,slug="contenter-"+str(other),name="Other fixture",business_name="",status="active",config={})])
            await session.commit()
        access=AsyncMock(return_value=owner)
        with patch.object(contenter,"_user",new=access), patch.object(contenter,"get_settings",return_value=cfg), patch.object(contenter.ContenterClient,"export",new=AsyncMock(return_value=profile())):
            result=await contenter.set_link(aid,contenter.LinkRequest(business_id="business-a"),"test-session")
            assert result["linked"] and result["version"]==1 and result["ai_usage_enabled"] is False
            # No change => no version duplication, including concurrent manual syncs.
            await asyncio.gather(contenter.sync_link(aid,cfg),contenter.sync_link(aid,cfg))
            assert (await contenter.link_view(aid,cfg))["version"]==1
        async with SessionLocal() as session:
            workspace=await session.get(AssistantWorkspace,aid)
            assert workspace.config=={"active_business_id":None},"Step 4 was implicitly activated"
            assert list((await session.scalars(select(BusinessProfile).where(BusinessProfile.assistant_id==aid))).all())==[]
        with patch.object(contenter.ContenterClient,"export",new=AsyncMock(return_value=profile(text="Second version"))):
            await contenter.sync_link(aid,cfg)
        result=await contenter.link_view(aid,cfg)
        assert result["version"]==2 and result["profile"]["sections"][0]["content"]=="Second version"
        assert (await contenter.link_view(other,cfg))["linked"] is False,"Snapshot leaked to another workspace"
        with patch.object(contenter.ContenterClient,"export",new=AsyncMock(side_effect=contenter.ContenterError("unreachable"))):
            await contenter.sync_link(aid,cfg)
        result=await contenter.link_view(aid,cfg)
        assert result["state"]=="stale" and result["profile"] is not None
        with patch.object(contenter.ContenterClient,"export",new=AsyncMock(side_effect=contenter.ContenterError("access_revoked"))):
            await contenter.sync_link(aid,cfg)
        result=await contenter.link_view(aid,cfg)
        assert result["state"]=="access_revoked" and result["profile"] is None and result["open_url"] is None
        with patch.object(contenter,"_user",new=access), patch.object(contenter,"get_settings",return_value=cfg):
            assert (await contenter.versions(aid,"test-session"))["items"]==[]
            await contenter.unlink(aid,"test-session")
            assert (await contenter.link_view(aid,cfg))["linked"] is False
            with patch.object(contenter.ContenterClient,"export",new=AsyncMock(return_value=profile("business-b"))):
                result=await contenter.set_link(aid,contenter.LinkRequest(business_id="business-b"),"test-session")
            assert result["version"]==3,"Version IDs were reused after unlink"
            assert len((await contenter.versions(aid,"test-session"))["items"])==1,"Old business history leaked to the new link"
        # A delayed response must not resurrect a link after unlinking.
        started,finish=asyncio.Event(),asyncio.Event()
        async def delayed(_):
            started.set();await finish.wait();return profile("business-b","Late content")
        with patch.object(contenter.ContenterClient,"export",new=AsyncMock(side_effect=delayed)),patch.object(contenter,"_user",new=access):
            pending=asyncio.create_task(contenter.sync_link(aid,cfg))
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                await contenter.unlink(aid,"test-session");finish.set();await asyncio.wait_for(pending, timeout=10)
            finally:
                finish.set()
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
        assert (await contenter.link_view(aid,cfg))["linked"] is False
        async with SessionLocal() as session:
            snapshots=(await session.scalars(select(ContenterBusinessSnapshot).where(ContenterBusinessSnapshot.assistant_id==aid).order_by(ContenterBusinessSnapshot.version))).all()
            assert [x.version for x in snapshots]==[1,2,3]
        print("Contenter SQL integration passed: link/sync/hash/history, concurrent sync, transient outage, revocation, workspace isolation, relink/unlink race, no AI/profile mutation.")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id.in_([aid,other])))
            await session.commit()
        await engine.dispose()


asyncio.run(main())
