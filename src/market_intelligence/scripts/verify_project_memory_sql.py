"""Saved-memory admission, ACL, cursor and retention against an isolated DB."""
import asyncio
import hashlib
from pathlib import Path
import sys
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser, AssistantMember
from app.news_chat import api, service as svc
from app.news_chat.models import ChatConversation, ChatGeneration

settings = get_settings()
if settings.environment != "test" or settings.postgres_db != "news_chat_test":
    raise RuntimeError("Synthetic database required")


async def verify():
    aid = uuid.UUID("10000000-0000-4000-8000-000000000001")
    pid = uuid.UUID("20000000-0000-4000-8000-000000000001")
    uid = uuid.uuid4()
    other_uid = uuid.uuid4()
    token = "synthetic-memory-sql-session"
    old = svc.now() - timedelta(days=100)
    ids = sorted(uuid.uuid4() for _ in range(35))
    generations = []
    async with SessionLocal() as s:
        user = AdminUser(id=uid, username="memory-sql", email="memory-sql@gmail.com", display_name="Synthetic memory",
                         password_hash="synthetic-unused", active=True, role="viewer", preferences={"user_portal_access": {"enabled": True}, "news_chat_enabled": True})
        s.add(user)
        other = AdminUser(id=other_uid, username="memory-sql-other", email="memory-sql-other@gmail.com", display_name="Other synthetic reader",
                          password_hash="synthetic-unused", active=True, role="viewer", preferences={"user_portal_access": {"enabled": True}, "news_chat_enabled": True})
        s.add(other)
        await s.flush()
        s.add(AssistantMember(assistant_id=aid, user_id=uid, role="viewer"))
        s.add(AssistantMember(assistant_id=aid, user_id=other_uid, role="viewer"))
        s.add(AdminSession(user_id=uid, token_hash=hashlib.sha256(token.encode()).hexdigest(), portal="user", mfa_verified=True, created_at=svc.now(), expires_at=svc.now()+timedelta(minutes=30)))
        empty = ChatConversation(user_id=uid, assistant_id=aid, publication_id=pid, provider="openai", context={"version": "a"*64, "segments": []})
        s.add(empty)
        for cid in ids:
            s.add(ChatConversation(id=cid, user_id=uid, assistant_id=aid, publication_id=pid, provider="openai", created_at=old,
                                   saved_at=old, context={"version": "a"*64, "segments": [{"id": "report-0", "text": "Saved synthetic report"}]}))
        await s.flush()
        model = (await svc.policy(s)).models[0].model_dump(mode="json")
        for cid in ids:
            g = ChatGeneration(conversation_id=cid, user_id=uid, assistant_id=aid, idempotency_key=str(cid), session_hash="", question="Saved old question", answer="Saved old answer", language="fa", model=model, citations=[], status="completed", cancel_requested=False, reserved_usd=0, actual_usd=0, usage={}, created_at=old, finished_at=old, deadline=old)
            s.add(g)
            generations.append(g)
        await s.commit()
        empty_id = empty.id
    try:
        try:
            await api.save_memory(empty_id, token=token)
        except HTTPException as e:
            assert e.status_code == 409
        else:
            raise AssertionError("Empty conversation entered memory")
        # Saving an active temporary window removes its expiry/session lease.
        async with SessionLocal() as s:
            c = await s.get(ChatConversation, ids[-1])
            c.context = {**c.context, "_ephemeral": True, "_session_hash": hashlib.sha256(token.encode()).hexdigest(), "_expires_at": (svc.now()+timedelta(minutes=1)).isoformat()}
            await s.commit()
        first = await api.save_memory(ids[-1], token=token)
        second = await api.save_memory(ids[-1], token=token)
        assert first["saved_at"] == second["saved_at"], "Repeated save changed memory ordering"
        assert (await api.heartbeat(ids[-1], token=token))["status"] == "saved"
        async with SessionLocal() as s:
            c = await s.get(ChatConversation, ids[-1])
            assert not c.context.get("_ephemeral") and "_session_hash" not in c.context
            await svc.close_window(s, ids[-1], pid, user)
        assert (await api.messages(ids[-1], token=token))["messages"][0]["answer"] == "Saved old answer", "Closing erased an explicit save"

        seen = []
        before = None
        while True:
            page = await api.project_memory(aid, before=before, token=token)
            seen.extend(uuid.UUID(m["id"]) for m in page["memories"])
            if not page["older_before"]:
                break
            before = uuid.UUID(page["older_before"])
            assert len(seen) <= 35
        assert seen == list(reversed(ids)), "Equal-timestamp memory pagination lost or repeated a thread"
        try:
            await api.project_memory(aid, before=empty_id, token=token)
        except HTTPException as e:
            assert e.status_code == 404
        else:
            raise AssertionError("Unrelated memory cursor accepted")
        async with SessionLocal() as s:
            same_project_other_user = await s.get(AdminUser, other_uid)
        with patch.object(api.admin, "current_reader", new=AsyncMock(return_value=same_project_other_user)):
            others = (await api.project_memory(aid, token=token))["memories"]
            assert not {uuid.UUID(m["id"]) for m in others}.intersection(ids), "Another user saw private memory"
            for action in (api.save_memory, api.unsave_memory):
                try:
                    await action(ids[0], token=token)
                except HTTPException as e:
                    assert e.status_code == 404
                else:
                    raise AssertionError("Another user changed private memory")
        try:
            await api.project_memory(uuid.UUID("10000000-0000-4000-8000-000000000002"), token=token)
        except HTTPException as e:
            assert e.status_code == 404
        else:
            raise AssertionError("Private project memory became accessible")
        async with SessionLocal() as s:
            await s.execute(update(AdminSession).where(AdminSession.user_id == uid).values(expires_at=svc.now()-timedelta(minutes=1)))
            await s.commit()
        await svc.maintenance_once()
        async with SessionLocal() as s:
            await s.execute(update(AdminSession).where(AdminSession.user_id == uid).values(expires_at=svc.now()+timedelta(minutes=30)))
            await s.commit()
            rows = (await s.scalars(select(ChatGeneration).where(ChatGeneration.user_id == uid))).all()
            assert len(rows) == 35 and all(r.answer == "Saved old answer" for r in rows), "Retention erased saved memory"
        await api.unsave_memory(ids[0], token=token)
        await svc.maintenance_once()
        async with SessionLocal() as s:
            assert await s.get(ChatConversation, ids[0]) is None
            row = await s.get(ChatGeneration, generations[0].id)
            assert row.answer == row.question == "" and row.conversation_id is None
        await api.remove(ids[1], token=token)
        async with SessionLocal() as s:
            row = await s.get(ChatGeneration, generations[1].id)
            assert row.answer == row.question == "", "Explicit deletion retained saved text"
        print("Project memory SQL passed: complete-answer admission, idempotent save, 35 timestamp-tied threads, cursor validation, private user/project ACL, retention exemption, unsave retention and deletion erase.")
    finally:
        async with SessionLocal() as s:
            await s.delete(await s.get(AdminUser, uid))
            await s.delete(await s.get(AdminUser, other_uid))
            await s.commit()


if __name__ == "__main__":
    async def main():
        try:
            await verify()
        finally:
            await engine.dispose()
    asyncio.run(main())
