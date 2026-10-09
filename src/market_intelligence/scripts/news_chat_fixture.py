"""Isolated E2E app, synthetic accounts and models. Never a production entrypoint."""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings

settings = get_settings()
if settings.environment != "test" or settings.postgres_db != "news_chat_test" or settings.scheduler_enabled:
    raise RuntimeError("Fresh isolated news_chat_test database and disabled scheduler required")

from app import admin
from app.database import SessionLocal, engine
from app.main import app
from app.models import AdminUser, AssistantMember, AssistantWorkspace, Source, SourceItem, NormalizedArticle, ArticleAnalysis, Publication
from app.news_chat import providers
from app.news_chat.models import ChatPolicy
from app.news_chat.schemas import ModelSpec, Policy

PROJECT = uuid.UUID('10000000-0000-4000-8000-000000000001')
PRIVATE_PROJECT = uuid.UUID('10000000-0000-4000-8000-000000000002')
NEWS = uuid.UUID('20000000-0000-4000-8000-000000000001')
PRIVATE_NEWS = uuid.UUID('20000000-0000-4000-8000-000000000002')
PREVIEW = uuid.UUID('20000000-0000-4000-8000-000000000003')
PASSWORD = 'synthetic violet herons cross mountain lakes'


async def seed():
    async with SessionLocal() as s:
        if await s.get(AssistantWorkspace, PROJECT):
            return
        for aid, name in [(PROJECT,'Synthetic news study'),(PRIVATE_PROJECT,'Private synthetic project')]:
            s.add(AssistantWorkspace(id=aid, name=name, slug='synthetic-'+str(aid)[-1], business_name='', status='active',config={}))
        password_hash = await admin.hash_password_async(PASSWORD)
        users=[]
        for n, name, role, grant, project in [(1,'chat-owner','admin',True,PROJECT),(2,'chat-reader','viewer',True,PROJECT),(3,'chat-other','viewer',True,PRIVATE_PROJECT),(4,'chat-no-grant','viewer',False,PROJECT),(5,'chat-admin','admin',False,PROJECT)]:
            u=AdminUser(id=uuid.UUID(f'30000000-0000-4000-8000-00000000000{n}'),username=name,email=name+'@gmail.com',display_name=name,role=role,active=True,password_hash=password_hash,login_method='both',preferences={'user_portal_access':{'enabled':True,'feedback_enabled':False},'news_chat_enabled':grant})
            s.add(u);users.append((u,project))
        await s.flush()
        for u,project in users:
            s.add(AssistantMember(assistant_id=project,user_id=u.id,role=u.role))
        for n,aid,pid,pubstatus in [(1,PROJECT,NEWS,'published'),(2,PRIVATE_PROJECT,PRIVATE_NEWS,'published'),(3,PROJECT,PREVIEW,'preview')]:
            source=Source(assistant_id=aid,source_key=f'T{n:03}',name='Synthetic source',homepage_url='https://synthetic.invalid',fetch_url='https://synthetic.invalid/rss',adapter='rss')
            s.add(source);await s.flush()
            item=SourceItem(assistant_id=aid,source_id=source.id,fingerprint=str(pid),title='Synthetic report',url='https://synthetic.invalid/'+str(n))
            s.add(item);await s.flush()
            article=NormalizedArticle(assistant_id=aid,source_item_id=item.id,canonical_url=item.url,title=item.title,normalized_text='INTERNAL FULL ORIGINAL NEVER SENT',extraction_status='complete',extraction_method='fixture')
            s.add(article);await s.flush()
            analysis=ArticleAnalysis(assistant_id=aid,article_id=article.id,status='succeeded',headline='Fixture',news_summary='Internal hidden summary',business_connection='INTERNAL BUSINESS SECRET',opportunity='',risk='',suggested_action='',time_horizon='short',confidence=1,model='fixture')
            s.add(analysis);await s.flush()
            s.add(Publication(id=pid,assistant_id=aid,analysis_id=analysis.id,idempotency_key=str(pid),status=pubstatus,message_text='Published synthetic headline\nA verified fixture paragraph about batteries.\nA second published paragraph. <script>not executed</script>',published_at=datetime.now(timezone.utc)))
        models=[ModelSpec(provider=p,model_id='fixture-v1',label=p+' fixture model',input_usd='1',output_usd='3',enabled=True,verified=True,price_reference='Synthetic test price, 2026-10-09') for p in ('openai','anthropic','google')]
        policy=Policy(enabled=True,models=models,projects={str(a):{'enabled':True,'model_keys':[m.key for m in models]} for a in (PROJECT,PRIVATE_PROJECT)})
        row=await s.get(ChatPolicy,1);row.config=policy.model_dump(mode='json')
        await s.commit()


async def fake_stream(settings, model, messages):
    # Deliberately check the real server's prompt boundary, not a mock HTTP UI.
    data='\n'.join(m['content'] for m in messages)
    if 'INTERNAL BUSINESS SECRET' in data or 'INTERNAL FULL ORIGINAL' in data:
        raise RuntimeError('Private analysis entered a chat prompt')
    if model.provider != 'openai' and 'PRIVATE_OPENAI_HISTORY' in data:
        raise RuntimeError('Private history was transferred to a different provider')
    if messages[-1]['content']=='FAIL':
        raise providers.ProviderError('provider_failed')
    if messages[-1]['content']=='HANG':
        await asyncio.sleep(60)
    answer='Synthetic answer grounded in the selected report [report-1].'
    for piece in answer.split(' '):
        await asyncio.sleep(0.15 if messages[-1]['content']=='SLOW' else 0.035)
        yield {'text':piece+' '}
    yield {'usage':{'input_tokens':120,'output_tokens':25},'done':True}


async def prepare():
    try:
        await seed()
    finally:
        # Close on the SAME loop before Uvicorn starts its different one.
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(prepare())
    providers.stream=fake_stream
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8010,log_level='warning')
