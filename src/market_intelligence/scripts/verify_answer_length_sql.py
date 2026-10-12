"""Real SQL: personal defaults, frozen prompts, idempotency and native usage."""
import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from sqlalchemy import delete
from app import admin
from app.answer_length import AnswerLength
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser
from app.news_chat import api, service
from app.news_chat.models import ChatConversation, ChatGeneration
from app.news_chat.schemas import Question, Start
from scripts.news_chat_fixture import fake_stream

settings = get_settings()
if settings.environment != 'test' or settings.postgres_db != 'news_chat_test':
    raise RuntimeError('Isolated synthetic database required')


async def main():
    uid = uuid.UUID('30000000-0000-4000-8000-000000000014')
    pid = uuid.UUID('20000000-0000-4000-8000-000000000001')
    token = 'synthetic-answer-length-session'
    digest = hashlib.sha256(token.encode()).hexdigest()
    ranges = {'short': {'min': 230, 'max': 510}, 'medium': {'min': 710, 'max': 1510}, 'long': {'min': 1710, 'max': 4310}}
    async with SessionLocal() as s:
        user = await s.get(AdminUser, uid)
        original = dict(user.preferences)
        s.add(AdminSession(user_id=uid, token_hash=digest, portal='user', mfa_verified=True,
                           expires_at=service.now()+timedelta(minutes=30), created_at=service.now()))
        await s.commit()
    try:
        await admin.update_reader_preferences(admin.ReaderPreferencesUpdate(chat={
            'response_length': 'short', 'length_characters': ranges, 'language': 'en'}), user)
        async with SessionLocal() as s:
            user = await s.get(AdminUser, uid)
        created = await api.start(pid, Start(model_key='openai:fixture-v1'), token=token)
        cid = uuid.UUID(created['id'])
        common = dict(model_key='openai:fixture-v1', language='en', context_version=created['context']['version'])
        q = Question(**common, question='EXPECT_LENGTH_short', idempotency_key='sql-length-default-fixture')
        first = await service.send(cid, q, user, token)
        gid = uuid.UUID(first['id'])
        # Change account defaults while the request is still queued. Neither
        # the generated prompt nor an omitted-field retry may use new defaults.
        await admin.update_reader_preferences(admin.ReaderPreferencesUpdate(chat={
            'response_length': 'long', 'length_characters': ranges, 'language': 'en'}), user)
        async with SessionLocal() as s:
            user = await s.get(AdminUser, uid)
            queued = await s.get(ChatGeneration, gid)
            assert queued.status == 'queued'
            assert queued.usage['answer_length'] == AnswerLength(mode='short', characters=ranges).model_dump()
        assert (await service.send(cid, q, user, token))['id'] == first['id']
        try:
            await service.send(cid, q.model_copy(update={'response_length': 'long'}), user, token)
        except HTTPException as exc:
            assert exc.status_code == 409 and exc.detail == 'idempotency_conflict'
        else:
            raise AssertionError('Different length reused the same request key')
        with patch('app.news_chat.service.providers.stream', fake_stream):
            await service.generate(gid)
            for mode in ('medium', 'long', 'auto'):
                override = Question(**common, question='EXPECT_LENGTH_'+mode,
                                    idempotency_key='sql-length-'+mode+'-fixture', response_length=mode,
                                    length_characters=ranges)
                response = await service.send(cid, override, user, token)
                await service.generate(uuid.UUID(response['id']))
            async with SessionLocal() as s:
                g = await s.get(ChatGeneration, gid)
                assert g.status == 'completed', (g.status, g.error_code)
                assert (g.input_tokens, g.output_tokens) == (120, 25)
                assert g.reserved_tokens >= g.input_tokens + g.output_tokens
                assert g.usage['answer_length']['mode'] == 'short'
                stored = await s.get(AdminUser, uid)
                assert admin._reader_preferences_from_user(stored)['chat']['response_length'] == 'long'
        print('Answer length SQL passed: saved personal ranges, default admission, queued preference change, frozen provider prompt, four modes, idempotent retry/conflict and native token settlement.')
    finally:
        async with SessionLocal() as s:
            stored = await s.get(AdminUser, uid)
            stored.preferences = original
            await s.execute(delete(ChatConversation).where(ChatConversation.user_id == uid))
            await s.execute(delete(ChatGeneration).where(ChatGeneration.user_id == uid))
            await s.execute(delete(AdminSession).where(AdminSession.token_hash == digest))
            await s.commit()
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
