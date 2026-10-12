import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from app.news_chat.context import prompt, validate_citations
from app.news_chat.schemas import ResearchStart
from app.reader_research.schemas import Profile, Record, Weights
from app.reader_research.service import feed_signals, project, trends


class ResearchSchemaTests(unittest.TestCase):
    def test_invalid_or_unbounded_profiles_are_refused(self):
        for change in ({'weights': {'freshness': 0, 'relevance': 0, 'interests': 0}},
                       {'interests': ['']}, {'business_context': 'x' * 2001},
                       {'muted_terms': ['x'] * 31}, {'other_user_id': str(uuid.uuid4())}):
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                Profile(**change)

    def test_sources_and_memory_are_explicit_bounded_and_distinct(self):
        data={'model_key':'openai:synthetic'}
        empty=ResearchStart(**data)
        self.assertEqual([],empty.memory_ids)
        self.assertFalse(empty.include_business)
        for change in ({'source_ids':[uuid.uuid4()]*2},{'memory_ids':[uuid.uuid4() for _ in range(6)]}):
            with self.assertRaises(ValidationError):ResearchStart(**data,**change)

    def test_shared_results_require_sources_and_tracking_requires_term(self):
        for data in ({'kind':'shared','title':'Result','body':'Text'},
                     {'kind':'watch','title':'Company'}, {'kind':'decision','title':' '}):
            with self.assertRaises(ValidationError):Record(**data)
        r=Record(kind='shared',title='Selected result',body='Publicly shared result',publication_ids=[uuid.uuid4()])
        self.assertEqual('shared',r.kind)

    def test_dates_are_not_guessed_and_naive_seen_times_are_refused(self):
        r=Record(kind='action',title='Review evidence')
        self.assertIsNone(r.attributes.due_on)
        self.assertEqual('',r.attributes.assignee)
        with self.assertRaises(ValidationError):
            Record(kind='topic',title='Track',attributes={'term':'company','reviewed_at':'2026-10-11T00:00:00'})


class ResearchSignalsTests(unittest.TestCase):
    def setUp(self):self.at=datetime(2026,10,11,12,tzinfo=timezone.utc)
    def row(self,id,text,hours=0):return {'id':id,'title':text,'text':text,'source':'Synthetic','published_at':(self.at-timedelta(hours=hours)).isoformat(),'relevance':.8}

    def test_muting_is_personal_explainable_and_reversible(self):
        rows=[self.row('1','Battery research'),self.row('2','Sports report')]
        profile=Profile(muted_terms=['sports'],interests=['Battery'])
        result=feed_signals(rows,profile,self.at)
        self.assertFalse(result[0]['hidden']);self.assertTrue(result[1]['hidden'])
        self.assertEqual(['sports'],result[1]['muted_terms'])
        self.assertFalse(any(row['hidden'] for row in feed_signals(rows,Profile(),self.at)))
        self.assertNotIn('hidden',rows[0], 'Signals mutated the published report')

    def test_identical_reports_do_not_become_independent_trend_evidence(self):
        rows=[self.row('1','Battery innovation'),self.row('2','Battery innovation')]
        self.assertEqual([],trends(rows))
        result=feed_signals(rows,Profile(hide_duplicates=True),self.at)
        self.assertEqual('1',result[1]['duplicate_of'])
        restored=feed_signals(rows,Profile(hide_duplicates=False),self.at)
        self.assertFalse(restored[1]['hidden'])

    def test_priority_respects_user_weights_and_explains_each_component(self):
        rows=[self.row('1','Older battery research',72),self.row('2','Fresh sports report')]
        scores=feed_signals(rows,Profile(interests=['battery'],weights=Weights(freshness=0,relevance=0,interests=100)),self.at)
        self.assertGreater(scores[0]['priority']['score'],scores[1]['priority']['score'])
        self.assertEqual(.5,scores[0]['priority']['freshness'])
        self.assertEqual(['battery'],scores[0]['priority']['matched_interests'])

    def test_different_source_footers_do_not_inflate_trend_evidence(self):
        rows=[self.row('1','Battery evidence\nSame published facts.\n🔗 Source: First'),
              self.row('2','Battery evidence\nSame published facts.\n🔗 Source: Second')]
        self.assertEqual([],trends(rows))
        self.assertTrue(feed_signals(rows,Profile(hide_duplicates=True),self.at)[1]['hidden'])

    def test_multi_source_citations_preserve_publication_and_memory_scope(self):
        context={'version':'a'*64,'scope':'selected_research','complete':True,'segments':[
            {'id':'report-0','text':'Source A','publication_id':'P','scope':'published_report'},
            {'id':'report-1','text':'Prior selected memory','memory_id':'M','scope':'selected_private_memory'}]}
        answer,citations,bad=validate_citations('[report-0] [report-1] [report-999]',context)
        self.assertTrue(bad);self.assertNotIn('999',answer)
        self.assertEqual('P',citations[0]['publication_id']);self.assertEqual('M',citations[1]['memory_id'])
        self.assertEqual('selected_private_memory',citations[1]['scope'])
        for intent in ['compare','verify','impact','timeline','action_draft']:
            system=prompt(context,'Question','fa',[],None,24000,intent)[0]['content']
            self.assertIn('not independent evidence',system)
            self.assertIn('unverified data',system)
            self.assertIn('You have access only to supplied selections',system)


class ResearchAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_acl_is_checked_without_owner_shortcuts(self):
        aid=uuid.uuid4();user=SimpleNamespace(id=uuid.uuid4())
        with patch('app.reader_research.service.admin.reader_assistants',AsyncMock(return_value={'assistants':[]})):
            with self.assertRaises(HTTPException) as caught:await project(user,aid)
            self.assertEqual(404,caught.exception.status_code)
        with patch('app.reader_research.service.admin.reader_assistants',AsyncMock(return_value={'assistants':[{'id':str(aid)}]})):
            await project(user,aid)
