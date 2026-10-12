"""Attach existing saved work to monitoring; no AI, network or account changes."""
import asyncio
import uuid
from sqlalchemy import select
from app import admin
from app.database import SessionLocal, engine
from app.models import AdminUser, Publication
from app.news_chat.models import ChatConversation
from app.reader_research.models import ResearchRecord
from app.reader_tools.corrections import dependency_versions, retain_report_history


async def backfill():
    attached = 0
    async with SessionLocal() as s:
        users = list((await s.scalars(select(AdminUser).where(AdminUser.active.is_(True)))).all())
    for user in users:
        if not admin.user_portal_access_allowed(user):
            continue
        aids = {uuid.UUID(row['id']) for row in (await admin.reader_assistants(user))['assistants']}
        if not aids:
            continue
        references = []
        async with SessionLocal() as s:
            records = list((await s.scalars(select(ResearchRecord).where(ResearchRecord.user_id == user.id,
                ResearchRecord.assistant_id.in_(aids)))).all())
            for row in records:
                references.append((row.assistant_id, row.publication_ids, None))
            memories = list((await s.scalars(select(ChatConversation).where(ChatConversation.user_id == user.id,
                ChatConversation.assistant_id.in_(aids), ChatConversation.saved_at.is_not(None),
                ChatConversation.deleted_at.is_(None)))).all())
            for row in memories:
                references.append((row.assistant_id, row.context.get('source_ids') or [str(row.publication_id)],
                    row.context if row.context.get('scope') in {'published_report', 'selected_research'} else None))
        for aid, ids, context in references:
            async with SessionLocal() as s:
                valid = list((await s.scalars(select(Publication.id).where(Publication.assistant_id == aid,
                    Publication.status == 'published', Publication.id.in_([uuid.UUID(v) for v in ids])))).all())
                if len(valid) != len(ids):
                    continue
                await dependency_versions(s, user, aid, valid)
                if context:
                    await retain_report_history(s, context, valid)
                await s.commit()
                attached += len(valid)
    return {'references_processed': attached, 'account_grants_changed': False, 'ai_calls': 0, 'external_messages': 0}


if __name__ == '__main__':
    async def main():
        import json
        try:
            print(json.dumps(await backfill()))
        finally:
            await engine.dispose()
    asyncio.run(main())
