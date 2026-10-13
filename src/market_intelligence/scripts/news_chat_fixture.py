"""Isolated E2E app, synthetic accounts and models. Never a production entrypoint."""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
import sys
import json

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
from app.news_chat.models import ChatConversation, ChatGeneration, ChatPolicy
from app.news_chat.context import context_for
from app.news_chat.schemas import ModelSpec, Policy
from scripts import news_voice_fixture

PROJECT = uuid.UUID('10000000-0000-4000-8000-000000000001')
PRIVATE_PROJECT = uuid.UUID('10000000-0000-4000-8000-000000000002')
NEWS = uuid.UUID('20000000-0000-4000-8000-000000000001')
PRIVATE_NEWS = uuid.UUID('20000000-0000-4000-8000-000000000002')
PREVIEW = uuid.UUID('20000000-0000-4000-8000-000000000003')
PASSWORD = 'synthetic violet herons cross mountain lakes'
VOICE_CONTINUE=asyncio.Event()


@app.post('/_voice_fixture/continue')
async def continue_voice_fixture():
    # This module refuses production and is never its entrypoint.
    VOICE_CONTINUE.set()
    return {'synthetic_fixture':True}


async def seed():
    async with SessionLocal() as s:
        if await s.get(AssistantWorkspace, PROJECT):
            return
        for aid, name in [(PROJECT,'Synthetic news study'),(PRIVATE_PROJECT,'Private synthetic project')]:
            s.add(AssistantWorkspace(id=aid, name=name, slug='synthetic-'+str(aid)[-1], business_name='', status='active',config={}))
        research_project=uuid.UUID('10000000-0000-4000-8000-000000000003')
        s.add(AssistantWorkspace(id=research_project,name='Synthetic research workspace',slug='synthetic-research',business_name='',status='active',config={}))
        password_hash = await admin.hash_password_async(PASSWORD)
        users=[]
        for n, name, role, grant, project in [(1,'chat-owner','admin',True,PROJECT),(2,'chat-reader','viewer',True,PROJECT),(3,'chat-other','viewer',True,PRIVATE_PROJECT),(4,'chat-no-grant','viewer',False,PROJECT),(5,'chat-admin','admin',False,PROJECT),(6,'chat-insights','viewer',True,PROJECT),(9,'voice-reader','viewer',True,PROJECT)]:
            u=AdminUser(id=uuid.UUID(f'30000000-0000-4000-8000-00000000000{n}'),username=name,email=name+'@gmail.com',display_name=name,role=role,active=True,password_hash=password_hash,login_method='both',preferences={'user_portal_access':{'enabled':True,'feedback_enabled':False},'news_chat_enabled':grant})
            s.add(u);users.append((u,project))
        await s.flush()
        for u,project in users:
            s.add(AssistantMember(assistant_id=project,user_id=u.id,role=u.role))
        for n,name in [(7,'research-reader'),(8,'research-peer'),(10,'tools-reader'),(11,'tools-peer')]:
            u=AdminUser(id=uuid.UUID(f'30000000-0000-4000-8000-{n:012d}'),username=name,email=name+'@gmail.com',display_name=name,role='viewer',active=True,password_hash=password_hash,login_method='both',preferences={'user_portal_access':{'enabled':True},'news_chat_enabled':True})
            s.add(u);await s.flush();s.add(AssistantMember(assistant_id=research_project,user_id=u.id,role='viewer'))
        # Dedicated actors keep quota tests independent of earlier grant-revocation probes.
        for n,name,grant in [(12,'quota-reader',True),(13,'quota-no-grant',False),(14,'length-reader',True)]:
            u=AdminUser(id=uuid.UUID(f'30000000-0000-4000-8000-{n:012d}'),username=name,email=name+'@gmail.com',display_name=name,role='viewer',active=True,password_hash=password_hash,login_method='both',preferences={'user_portal_access':{'enabled':True},'news_chat_enabled':grant})
            s.add(u);await s.flush();s.add(AssistantMember(assistant_id=PROJECT,user_id=u.id,role='viewer'))
        for n,aid,pid,pubstatus in [(1,PROJECT,NEWS,'published'),(2,PRIVATE_PROJECT,PRIVATE_NEWS,'published'),(3,PROJECT,PREVIEW,'preview')]:
            source=Source(assistant_id=aid,source_key=f'T{n:03}',name='Synthetic source',homepage_url='https://synthetic.invalid',fetch_url='https://synthetic.invalid/rss',adapter='rss')
            s.add(source);await s.flush()
            item=SourceItem(assistant_id=aid,source_id=source.id,fingerprint=str(pid),title='Synthetic report',url='https://synthetic.invalid/'+str(n))
            s.add(item);await s.flush()
            article=NormalizedArticle(assistant_id=aid,source_item_id=item.id,canonical_url=item.url,title=item.title,normalized_text='INTERNAL FULL ORIGINAL NEVER SENT',extraction_status='complete',extraction_method='fixture')
            s.add(article);await s.flush()
            analysis=ArticleAnalysis(assistant_id=aid,article_id=article.id,status='succeeded',headline='Fixture',news_summary='Internal hidden summary',business_connection='INTERNAL BUSINESS SECRET',opportunity='',risk='',suggested_action='',time_horizon='short',confidence=1,model='fixture')
            s.add(analysis);await s.flush()
            s.add(Publication(id=pid,assistant_id=aid,analysis_id=analysis.id,idempotency_key=str(pid),status=pubstatus,message_text='🔍 <b>Opportunity:</b> PREGENERATED_FIRST_BLOCK_HIDDEN\n\nPublished synthetic headline\nA verified fixture paragraph about batteries.\nA second published paragraph. <script>not executed</script>\nLiteral tag: &lt;img src=&quot;https://tracker.invalid/leak&quot; onerror=&quot;window.literalInjected=true&quot;&gt; and A &amp; B.\n\n🔍 <b>Opportunity:</b> PREGENERATED_OPPORTUNITY_HIDDEN\n\n⚠️ <b>Risk:</b> PREGENERATED_RISK_HIDDEN\n\n🔗 <b>Source:</b> Synthetic source',published_at=datetime.now(timezone.utc)))
        from datetime import timedelta
        for n in range(1,9):
            pid=uuid.UUID(f'40000000-0000-4000-8000-00000000000{n}')
            source=Source(assistant_id=research_project,source_key=f'R{n:03}',name='Synthetic research source '+str(n%2),homepage_url='https://synthetic.invalid',fetch_url='https://synthetic.invalid/'+str(n),adapter='rss');s.add(source);await s.flush()
            item=SourceItem(assistant_id=research_project,source_id=source.id,fingerprint=str(pid),title='Battery research '+str(n),url='https://synthetic.invalid/research/'+str(n));s.add(item);await s.flush()
            article=NormalizedArticle(assistant_id=research_project,source_item_id=item.id,canonical_url=item.url,title=item.title,normalized_text='INTERNAL FULL ORIGINAL NEVER SENT',extraction_status='complete',extraction_method='fixture');s.add(article);await s.flush()
            analysis=ArticleAnalysis(assistant_id=research_project,article_id=article.id,status='succeeded',headline=item.title,news_summary='Internal hidden summary',business_connection='INTERNAL BUSINESS SECRET',opportunity='',risk='',suggested_action='',time_horizon='short',confidence=1,model='fixture');s.add(analysis);await s.flush()
            text='Battery research '+str(1 if n==8 else n)+'\nPublished battery report evidence '+str(1 if n==8 else n)+'.'
            s.add(Publication(id=pid,assistant_id=research_project,analysis_id=analysis.id,idempotency_key=str(pid),status='published',message_text=text,published_at=datetime.now(timezone.utc)-timedelta(hours=n if n<7 else n*24)))
        models=[ModelSpec(provider=p,model_id='fixture-v1',label=p+' fixture model',input_usd='1',output_usd='3',enabled=True,verified=True,price_reference='Synthetic test price, 2026-10-09') for p in ('openai','anthropic','google')]
        policy=Policy(enabled=True,models=models)
        row=await s.get(ChatPolicy,1);row.config=policy.model_dump(mode='json')
        for n,uid,answer in [(1,7,'SELECTED_MEMORY_CANARY: review battery evidence'),(2,7,'UNSELECTED_PERSONAL_MEMORY_CANARY'),(3,8,'PEER_MEMORY_CANARY')]:
            old=datetime.now(timezone.utc)-timedelta(days=20)
            conversation=ChatConversation(id=uuid.UUID(f'50000000-0000-4000-8000-00000000000{n}'),user_id=uuid.UUID(f'30000000-0000-4000-8000-00000000000{uid}'),assistant_id=research_project,publication_id=uuid.UUID('40000000-0000-4000-8000-000000000001'),provider='openai',context=context_for('Battery research 1\nPublished battery report evidence 1.',None),created_at=old,saved_at=old)
            s.add(conversation);await s.flush()
            s.add(ChatGeneration(conversation_id=conversation.id,user_id=conversation.user_id,assistant_id=research_project,idempotency_key=str(conversation.id),session_hash='',question='Private saved question '+str(n),answer=answer,language='en',model=models[0].model_dump(mode='json'),citations=[],status='completed',cancel_requested=False,reserved_usd=0,actual_usd=0,usage={},created_at=old,finished_at=old,deadline=old))
        await s.commit()


async def fake_stream(settings, model, messages):
    # Deliberately check the real server's prompt boundary, not a mock HTTP UI.
    data='\n'.join(m['content'] for m in messages)
    if 'INTERNAL BUSINESS SECRET' in data or 'INTERNAL FULL ORIGINAL' in data:
        raise RuntimeError('Private analysis entered a chat prompt')
    if 'PREGENERATED_' in data:
        raise RuntimeError('Hidden opportunity/risk analysis entered the news chat')
    if 'PEER_MEMORY_CANARY' in data or 'UNSELECTED_PERSONAL_MEMORY_CANARY' in data:
        raise RuntimeError('Unselected private memory entered prompt')
    if 'EXPECT_SELECTED_MEMORY' in messages[-1]['content'] and 'SELECTED_MEMORY_CANARY' not in data:
        raise RuntimeError('Explicitly selected memory was omitted')
    if 'EXPECT_BUSINESS' in messages[-1]['content'] and 'USER_BUSINESS_CANARY' not in data:
        raise RuntimeError('Explicitly selected business context was omitted')
    if 'EXPECT_NO_PRIVATE_CONTEXT' in messages[-1]['content'] and ('SELECTED_MEMORY_CANARY' in data or 'USER_BUSINESS_CANARY' in data):
        raise RuntimeError('Private context was sent without current selection')
    if 'DETAIL_FOLLOW_UP' in data and not any(m['role'] == 'assistant' and 'Synthetic answer' in m['content'] for m in messages[:-1]):
        raise RuntimeError('Follow-up lost the same-news analysis conversation')
    if model.provider != 'openai' and 'PRIVATE_OPENAI_HISTORY' in data:
        raise RuntimeError('Private history was transferred to a different provider')
    if messages[-1]['content']=='FAIL':
        raise providers.ProviderError('provider_failed')
    if messages[-1]['content']=='HANG':
        await asyncio.sleep(60)
    if messages[-1]['content'].startswith('EXPECT_LENGTH_'):
        mode=messages[-1]['content'].removeprefix('EXPECT_LENGTH_')
        interval={'short':'230-510','medium':'710-1510','long':'1710-4310'}.get(mode)
        if (interval and interval+' characters' not in messages[0]['content']) or (mode=='auto' and 'Choose the answer length yourself' not in messages[0]['content']):
            raise RuntimeError('Selected answer length was not sent to provider')
    answer='Synthetic answer grounded in the selected report [report-1].'
    if 'Prepare a meeting brief' in messages[0]['content']:
        meta=json.loads(messages[-1]['content']);duration=int(meta['duration_minutes']);a=duration//3;b=a;c=duration-a-b
        answer=f"Duration: {duration} minutes.\nObjective: {meta['objective']}\nAgenda: evidence {a} minutes; key questions {b} minutes; decisions {c} minutes.\nKey question: What independent evidence is missing? [report-0]\nDecision needed: whether to run a small validation experiment.\nAction checklist: confirm evidence before assigning work."
    elif 'Act as a rigorous constructive critic' in messages[0]['content']:
        if 'User-selected analysis to critique' not in messages[-1]['content']:
            raise RuntimeError('Critique lost its explicit target')
        answer='Assumption: the reported result generalizes. [report-0]\nCounterargument: applicability is uncertain. No contradictory evidence was supplied.\nHypothetical objection: sample selection could change the conclusion.\nEvidence needed: independent replication.\nRevised conclusion: treat the result as provisional.'
    elif 'Compare the explicitly selected report and captured public-source or published-report revisions' in messages[0]['content']:
        if 'PUBLIC_CORRECTION_CANARY' not in data:
            raise RuntimeError('Correction analysis lost its explicitly selected public capture')
        import re
        sid=re.search(r'\[(report-\d+)\] \(selected_public_source_revision;',data)
        if not sid:
            raise RuntimeError('Public correction citation missing')
        answer='The source now states a corrected value of 25 ['+sid.group(1)+']. The earlier inference needs review; decisions were not automatically updated. [report-0]'
    elif 'Return a draft action in JSON' in messages[0]['content']:

        answer=json.dumps({'title':'Review battery evidence','description':'Review the selected published evidence [report-1].','assignee':'','due_on':None})
    elif 'Produce a Markdown comparison table' in messages[0]['content']:
        answer='| Claim | Agreement | Differences | Evidence | Unknown |\n| --- | --- | --- | --- | --- |\n| Batteries | Reports concern batteries | Different report dates | [report-0] [report-2] | Independent verification unavailable |'
    progressive=messages[-1]['content']=='Edited question from genuine microphone capture'
    if progressive:VOICE_CONTINUE.clear()
    if progressive:answer='First synthetic sentence grounded in the report [report-1]. Final synthetic sentence.'
    for piece in answer.split(' '):
        # Fast progressive tokens deliberately leave the end of the sentence
        # inside the persistence throttle before the provider goes silent.
        await asyncio.sleep(0 if progressive else 0.15 if messages[-1]['content']=='SLOW' else 0.035)
        if progressive and piece=='Final':await asyncio.wait_for(VOICE_CONTINUE.wait(),30)
        yield {'text':piece+' '}
    yield {'usage':{'input_tokens':120,'output_tokens':25},'done':True}


async def prepare():
    try:
        await seed()
        news_voice_fixture.configure()
        await news_voice_fixture.seed()
    finally:
        # Close on the SAME loop before Uvicorn starts its different one.
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(prepare())
    from app.reader_tools import corrections as correction_service
    from app.article_extraction import ArticleDocument
    class PublicCorrectionFixture:
        def __init__(self, settings):
            if settings.environment!='test':
                raise RuntimeError('Synthetic correction fixture only')
        async def fetch(self, **kwargs):
            if not kwargs['url'].startswith('https://synthetic.invalid/') or kwargs['robots_policy']!='respect':
                raise RuntimeError('Unexpected correction fixture source')
            return ArticleDocument(url=kwargs['url'],canonical_url=kwargs['url'],title='Correction: battery study',author=None,
                published_at=None,language='en',text='PUBLIC_CORRECTION_CANARY: The source corrected the reported figure to 25.',
                raw_html=None,extraction_status='complete',extraction_method='fixture',quality_score=1,content_hash=None,
                provenance={'fixture':True})
    correction_service.ArticleFetcher=PublicCorrectionFixture
    providers.stream=fake_stream
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8010,log_level='warning')
