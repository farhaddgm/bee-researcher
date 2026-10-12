import unittest
import uuid
from pydantic import ValidationError
from app.news_chat.context import prompt
from app.news_chat.schemas import Question, ResearchStart
from app.reader_research.schemas import Record
from app.reader_tools.corrections import fingerprint, source_notice
from app.reader_tools.schemas import ExpertCreate, Reply, RequestState


class ReaderToolsContracts(unittest.TestCase):
    def question(self, **changes):
        return Question(model_key='openai:fixture', question='Review this analysis', context_version='a'*64,
                        idempotency_key='reader-tool-request-0001', **changes)

    def test_critic_has_one_explicit_target_and_no_implicit_private_analysis(self):
        for change in ({'intent':'critique'}, {'intent':'critique','target_generation_id':uuid.uuid4(),'analysis_text':'analysis'},
                       {'intent':'question','analysis_text':'private text'}, {'intent':'meeting','target_generation_id':uuid.uuid4()}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.question(**change)
        self.assertEqual('critique',self.question(intent='critique',target_generation_id=uuid.uuid4()).intent)
        self.assertEqual('Selected analysis',self.question(intent='critique',analysis_text='Selected analysis').analysis_text)

    def test_expert_cannot_forge_author_or_ai_origin_or_send_without_sources(self):
        base={'id':uuid.uuid4(),'assignee_id':uuid.uuid4(),'title':'Evidence question','question':'Which evidence supports this?',
              'publication_ids':[uuid.uuid4()]}
        for change in ({'publication_ids':[]},{'publication_ids':[uuid.uuid4()]*2},{'requester_id':uuid.uuid4()},
                       {'question':' '},{'excerpt':'x'*6001}):
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                ExpertCreate(**{**base,**change})
        for change in ({'author_id':uuid.uuid4()},{'kind':'ai'},{'body':' '}):
            with self.assertRaises(ValidationError):
                Reply(**{'id':uuid.uuid4(),'version':1,'body':'My human reply',**change})
        with self.assertRaises(ValidationError):
            RequestState(version=1,status='answered')

    def test_meeting_requires_evidence_and_preserves_editable_real_times(self):
        base={'kind':'meeting','title':'Product review','body':'Review evidence and decide next steps','publication_ids':[uuid.uuid4()]}
        for change in ({'publication_ids':[]},{'body':' '},{'attributes':{'duration_minutes':181}},
                       {'attributes':{'meeting_at':'2026-10-12T12:00:00'}}):
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                Record(**{**base,**change})
        row=Record(**base,attributes={'duration_minutes':45,'meeting_at':'2026-10-12T12:00:00+03:30'})
        self.assertEqual(45,row.attributes.duration_minutes)
        self.assertEqual(12600,row.attributes.meeting_at.utcoffset().total_seconds())

    def test_revision_selection_is_bounded_and_unique(self):
        base={'model_key':'openai:fixture'}
        for ids in ([uuid.uuid4()]*2,[uuid.uuid4() for _ in range(6)]):
            with self.assertRaises(ValidationError):
                ResearchStart(**base,revision_ids=ids)

    def test_changed_page_is_not_automatically_a_retraction(self):
        self.assertEqual(fingerprint('Headline','Some words\n\n More words'),fingerprint('Headline','Some words More words'))
        self.assertNotEqual(fingerprint('Headline','Evidence A'),fingerprint('Headline','Evidence B'))
        self.assertEqual('changed',source_notice('Updated headline','The report mentions a correction elsewhere.'))
        self.assertEqual('correction_notice',source_notice('Correction: study results','The value was changed.'))
        self.assertEqual('retraction_notice',source_notice('Retraction: published study','The publisher withdrew the study.'))

    def test_new_ai_tasks_distinguish_hypotheses_and_do_not_assign_or_schedule(self):
        context={'scope':'selected_research','version':'a'*64,'complete':True,'source_ids':['news-1'],'revision_ids':['revision-1'],
                 'segments':[{'id':'report-0','text':'A public-source correction excerpt','scope':'selected_public_source_revision'}]}
        critique=prompt(context,'Analysis to critique','en',[],None,30000,'critique')[0]['content']
        self.assertIn('Never invent contradictory evidence',critique)
        self.assertIn('hypothetical objections',critique)
        self.assertIn('public-source revision excerpts',critique)
        meeting=prompt(context,'Meeting goal','fa',[],None,30000,'meeting')[0]['content']
        self.assertIn('Do not invent participants, assign work, schedule a meeting',meeting)
        self.assertIn('Persian (Farsi)',meeting)
        revision=prompt(context,'Review changes','en',[],None,30000,'correction_review')[0]['content']
        self.assertIn('not independent fact-checks',revision)
        self.assertIn('automatically updated',revision)
