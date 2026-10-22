import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_locale_quality import load_checkpoint, protected, save_checkpoint
from scripts.verify_public_news_quality import cells, make_context, QUESTION
from scripts.check_i18n_catalog import unique_object
from app.analysis_lenses.compiler import instruction, quote_choices
from app.news_chat.context import context_for, prompt


class ReviewToolsTests(unittest.TestCase):
    def test_duplicate_catalog_keys_cannot_be_hidden_by_json_last_write_wins(self):
        with self.assertRaisesRegex(ValueError,'duplicate translation key'):
            json.loads('{"title":{"en":"First","en":"Second"}}',object_pairs_hook=unique_object)
    def test_review_checkpoint_is_atomic_private_and_bound_to_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(load_checkpoint(root,'source-a',0))
            save_checkpoint(root,'source-a',0,{'entries':2,'corrections':[]})
            self.assertEqual({'entries':2,'corrections':[]},load_checkpoint(root,'source-a',0))
            self.assertEqual(0o600,(root/'source-a-0.json').stat().st_mode & 0o777)
            self.assertEqual([],list(root.glob('*.pending')))
            path = root/'source-a-0.json'
            value = json.loads(path.read_text());value['source_digest']='different';path.write_text(json.dumps(value))
            with self.assertRaisesRegex(RuntimeError,'checkpoint_mismatch'):load_checkpoint(root,'source-a',0)

    def test_format_contract_protects_interpolation_and_links(self):
        self.assertEqual(protected('Count {count}: %s https://example.test/a'),
                         protected('تعداد {count}: %s https://example.test/a'))
        self.assertNotEqual(protected('Hello ${name}'),protected('Hello ${other}'))

    def test_each_locale_samples_all_lenses_and_both_scopes(self):
        plan = cells([{'id':str(index)} for index in range(40)])
        for language in ['fa','en','tr','ar','es','it','de','fr']:
            localized = [row for row in plan if row[2]==language]
            self.assertEqual(5,len(localized))
            self.assertEqual({'general','marketing','security','product'},{row[3] for row in localized})
            self.assertEqual({'focused','contextual'},{row[4] for row in localized})

    def test_public_source_provenance_does_not_masquerade_as_ai_report(self):
        rows = [{'title':'Synthetic NASA excerpt','text':'A test was reported. No budget is provided.',
                 'url':'https://www.nasa.gov/fixture-'+str(index)} for index in range(40)]
        context = make_context(0,rows[0],'general','focused',rows)
        messages = prompt(context,QUESTION,'en',[],None,48000,'lens_analysis')
        system = messages[0]['content']
        self.assertIn('publisher excerpts, not AI-produced reports',system)
        self.assertIn('selected_public_source_revision',messages[1]['content'])
        self.assertTrue(quote_choices(context))
        self.assertIn('faithful paraphrase of that exact quote',instruction(context,'lens_analysis'))
        self.assertIn('Translate source headlines in prose fields too',instruction(context,'lens_analysis'))
        self.assertIn('A short menu excerpt is not evidence that the source ended',instruction(context,'lens_analysis'))
        self.assertIn('Lack of independent verification does not mean no event occurred',instruction(context,'lens_analysis'))
        original = prompt(context_for('An ordinary published AI report.',None),'Question','en',[],None,48000)[0]['content']
        self.assertIn('It is an AI-produced report',original)
        context['segments'].append({'id':'private','scope':'selected_private_memory','text':'PRIVATE_NOT_A_PUBLIC_QUOTE'})
        self.assertNotIn('PRIVATE_NOT_A_PUBLIC_QUOTE',str(quote_choices(context)))
