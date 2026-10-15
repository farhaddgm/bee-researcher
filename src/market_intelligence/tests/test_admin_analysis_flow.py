import ast
import json
import re
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai_relevance import article_digest, relevance_decision
from app.analysis_policy import AnalysisPolicy, owner_access, policy_values
from app.article_extraction import extract_article_document
from app.business_context import compile_brief, local_export
from app.business_knowledge_ai import suggest_knowledge
from app.config import Settings
from app.fetchers import parse_json_feed, parse_feed
from app.pipeline_service import review_queue_eligible
from app.publisher_dates import latest_publisher_date
from app.research_context import ConfigureRequest, configure_context


APP = Path(__file__).resolve().parents[1] / 'app'


class DatesAndDecisionTests(unittest.TestCase):
    def settings(self):
        return Settings(postgres_db='test', postgres_user='test', postgres_password='test', redis_password='test', _env_file=None)

    def test_latest_publisher_date_handles_iso_rfc_and_missing_without_now(self):
        self.assertIsNone(latest_publisher_date(None, '', 'unknown'))
        self.assertEqual(datetime(2026, 10, 14, 14, tzinfo=timezone.utc), latest_publisher_date('2026-10-14T10:00:00Z', 'Wed, 14 Oct 2026 14:00:00 GMT'))

    def test_atom_modified_beats_first_published(self):
        xml=b'<feed><entry><title>Publisher update</title><link href="https://example.org/a"/><published>2026-10-12T10:00:00Z</published><updated>2026-10-14T18:00:00Z</updated></entry></feed>'
        self.assertEqual(14, parse_feed(xml,'https://example.org')[0].published_at.day)

    def test_json_feed_modified_beats_original(self):
        data={'items':[{'title':'Updated news','url':'https://example.org/a','date_published':'2026-10-12T10:00:00Z','date_modified':'2026-10-14T18:00:00Z'}]}
        self.assertEqual(14,parse_json_feed(json.dumps(data).encode(),'https://example.org')[0].published_at.day)

    def test_article_modified_beats_feed_date_without_using_crawl_date(self):
        html=b'<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-10-12T10:00:00Z","dateModified":"2026-10-14T18:00:00Z"}</script><article><p>A genuine factual article has enough text for extraction.</p></article>'
        result=extract_article_document(html,'https://example.org/a',fallback_title='Example',fallback_published_at=None,settings=self.settings())
        self.assertEqual(14,result.published_at.day)
        undated=extract_article_document(b'<article><p>This is an undated publisher article with factual reporting.</p></article>','https://example.org/a',fallback_title='Example',fallback_published_at=None,settings=self.settings())
        self.assertIsNone(undated.published_at)

    def decision(self,score,**policy):
        return relevance_decision([{'valid':True,'topic_key':'loan','threshold':.35,'score':score,'confidence':.9,'excluded':False}],topic_count=1,**policy)

    def test_wepod_threshold_examples_and_inclusive_review_boundary(self):
        self.assertEqual('rejected',self.decision(.249)['relevance_state'])
        self.assertTrue(self.decision(.25)['can_approve'])
        self.assertFalse(self.decision(.349)['publishable'])
        self.assertTrue(self.decision(.35)['publishable'])
        self.assertFalse(review_queue_eligible(self.decision(.249)))
        self.assertTrue(review_queue_eligible(self.decision(.25)))

    def test_changing_threshold_does_not_change_the_supplied_ai_score(self):
        rows=[{'valid':True,'threshold':.35,'score':.4,'confidence':.9,'excluded':False}]
        self.assertTrue(relevance_decision(rows,topic_count=1)['publishable'])
        rows[0]['threshold']=.45
        result=relevance_decision(rows,topic_count=1)
        self.assertEqual(.4,result['relevance_score']);self.assertTrue(result['can_approve'])

    def test_low_confidence_unrelated_news_never_leaks_into_main_table(self):
        result=relevance_decision([{'valid':True,'threshold':.35,'score':.01,'confidence':.1,'excluded':False}],topic_count=1)
        self.assertEqual('rejected',result['relevance_state']);self.assertFalse(review_queue_eligible(result))

    def test_custom_margin_and_confidence_are_enforced(self):
        self.assertEqual('rejected',self.decision(.25,review_margin=.05)['relevance_state'])
        self.assertFalse(self.decision(.8,min_confidence=.95)['publishable'])
        self.assertFalse(self.decision(.2)['publishable'])

    def test_content_tail_invalidates_reusable_evidence(self):
        self.assertNotEqual(article_digest('title','a'*6000+'one',False),article_digest('title','a'*6000+'two',False))

    def test_local_profile_includes_revenue_and_sensitivities(self):
        p=SimpleNamespace(id=1,business_name='Fixture',description='Description',products_services='Product',markets='Market',target_customers='Customers',competitors=[],strategic_goals='Growth',revenue_model='Subscription',sensitivities=['Confidential plans'])
        brief=compile_brief(local_export(p),source='local')
        text='\n'.join(c['text'] for c in brief['claims'])
        self.assertIn('Subscription',text);self.assertIn('Confidential plans',text)

    def test_policy_defaults_are_bounded_and_cannot_store_credentials(self):
        self.assertEqual(.10,AnalysisPolicy().relevance_review_margin)
        self.assertEqual({},policy_values({}))
        for params in ({'relevance_review_margin':.3},{'relevance_batch_size':0},{'relevance_min_confidence':float('nan')},{'api_key':'secret'}):
            with self.assertRaises(ValidationError):AnalysisPolicy(**params)

    def test_scope_copy_pagination_and_locale_contracts(self):
        code=(APP/'admin_ui_modules/04-Independent.js').read_text()
        self.assertIn(r'\/operations\/status',code)
        self.assertNotIn('fmtDate(x.article_published_at||x.created_at)',code)
        shell=(APP/'admin_ui_modules/shell.html').read_text()
        self.assertIn('id="publicationPager" class="publication-pager"',shell)
        code=(APP/'admin_analysis_tools.js').read_text()
        catalogs=re.findall(r'^    ([a-z]{2}):(\[.*\]),?$',code,re.MULTILINE)
        self.assertEqual(8,len(catalogs))
        for lang,values in catalogs:self.assertEqual(36,len(ast.literal_eval(values)),lang)


class PermissionsAndSuggestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_admin_cannot_create_a_project_with_an_owner_policy(self):
        from app.admin import AssistantRequest, create_assistant
        with self.assertRaises(HTTPException) as error:
            await create_assistant(AssistantRequest(name='Fixture',slug='fixture',business_name='',config={'analysis_policy':AnalysisPolicy().model_dump()}),SimpleNamespace(role='admin',email='other@example.org'))
        self.assertEqual(403,error.exception.status_code)

    async def test_portal_only_delivery_does_not_require_telegram_or_send_twice(self):
        from app.pipeline_service import _send_claimed_publication
        settings=Settings(postgres_db='test',postgres_user='test',postgres_password='test',redis_password='test',telegram_channel_id=None,telegram_observer_channel_id=None,_env_file=None)
        with patch('app.pipeline_service.settings_for_assistant',AsyncMock(return_value=settings)),patch('app.pipeline_service._record_delivery',AsyncMock()) as record,patch('app.pipeline_service.TelegramClient') as telegram:
            result=await _send_claimed_publication(uuid.uuid4(),settings=settings,assistant_id=uuid.uuid4(),analysis_id=uuid.uuid4(),message_text='Approved report',image_url=None,observer_message_context=None)
            self.assertEqual(['user_portal'],result['destinations']);record.assert_awaited_once();telegram.assert_not_called()

    async def test_knowledge_suggestions_are_claim_bound_and_never_saved_implicitly(self):
        from app.business_context import CompiledBusinessProfile
        from app.business_knowledge_ai import FIELDS
        profile=CompiledBusinessProfile('Fixture',{'business_name':'Fixture','business_id':'b','revision':'fixture','claims':[{'id':'section:OVERVIEW','text':'Makes batteries'}], 'semantic_hash':'a'*64,'input_chars':15,'ready':True})
        session=AsyncMock();manager=AsyncMock();manager.__aenter__.return_value=session
        client=SimpleNamespace(configured=True,draft_json=AsyncMock())
        values={key:[] for key in FIELDS};values['products_services']=[{'text':'Batteries','claim_ids':['section:OVERVIEW']}]
        with patch('app.pipeline_service.settings_for_assistant',AsyncMock(return_value=SimpleNamespace(analysis_model='gpt-6-luna'))),patch('app.business_knowledge_ai.SessionLocal',return_value=manager),patch('app.research_context.resolve_context',AsyncMock(return_value=None)),patch('app.pipeline_service._profile_for_assistant',AsyncMock(return_value=profile)),patch('app.pipeline_service._reserve_relevance_budget',AsyncMock(return_value=uuid.uuid4())),patch('app.pipeline_service._finish_job',AsyncMock()) as finish,patch('app.business_knowledge_ai.OpenAIClient',return_value=client):
            client.draft_json.return_value=values
            result=await suggest_knowledge(uuid.uuid4(),'fa')
            self.assertFalse(result['saved']);self.assertEqual(['Batteries'],result['knowledge']['products_services']);session.commit.assert_not_awaited()
            values['products_services'][0]['claim_ids']=['invented']
            with self.assertRaises(HTTPException) as error:await suggest_knowledge(uuid.uuid4(),'fa')
            self.assertEqual(502,error.exception.status_code)
            self.assertEqual('failed',finish.await_args.kwargs['status']);session.commit.assert_not_awaited()

    async def test_nonowner_cannot_read_or_save_analyzer_controls(self):
        with patch('app.admin.current_admin',AsyncMock(return_value=SimpleNamespace(role='viewer',email='nobody@example.org'))),patch('app.admin._require_assistant_access',AsyncMock()) as access:
            with self.assertRaises(HTTPException) as error:await owner_access(None,uuid.uuid4())
            self.assertEqual(403,error.exception.status_code);access.assert_not_awaited()

    async def test_focused_mode_cannot_bypass_ai_comparison_gate(self):
        with patch('app.research_context.authorize',AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))),patch('app.research_context.candidate',AsyncMock()) as candidate:
            with self.assertRaises(HTTPException) as error:await configure_context(uuid.uuid4(),ConfigureRequest(mode='focused',confirmed=True),None)
            self.assertEqual(409,error.exception.status_code);candidate.assert_not_awaited()

    async def test_no_business_does_not_spend_budget_or_call_ai(self):
        session=AsyncMock();manager=AsyncMock();manager.__aenter__.return_value=session
        with patch('app.pipeline_service.settings_for_assistant',AsyncMock(return_value=SimpleNamespace())),patch('app.business_knowledge_ai.SessionLocal',return_value=manager),patch('app.research_context.resolve_context',AsyncMock(return_value=None)),patch('app.pipeline_service._profile_for_assistant',AsyncMock(return_value=None)),patch('app.pipeline_service._reserve_relevance_budget',AsyncMock()) as reserve,patch('app.business_knowledge_ai.OpenAIClient') as client:
            with self.assertRaises(HTTPException) as error:await suggest_knowledge(uuid.uuid4(),'fa')
            self.assertEqual('business_profile_required',error.exception.detail);reserve.assert_not_awaited();client.assert_not_called()
