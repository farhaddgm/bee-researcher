import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from app import admin
from app.answer_length import AnswerLength, CharacterRanges
from app.news_chat.context import context_for, prompt
from app.news_chat.schemas import Question
from app.reader_preferences import ReaderChatDefaults, chat_defaults


class AnswerLengthTests(unittest.TestCase):
    def test_legacy_preferences_keep_existing_choices_and_default_to_auto(self):
        saved = chat_defaults({'provider': 'google', 'language': 'fa', 'voice_terms': 'Battery'})
        self.assertEqual(saved['provider'], 'google')
        self.assertEqual(saved['voice_terms'], 'Battery')
        self.assertEqual(saved['response_length'], 'auto')
        self.assertEqual(saved['length_characters']['short'], {'min': 200, 'max': 600})

    def test_ranges_reject_invalid_unbounded_and_unordered_values(self):
        for invalid in (0, -1, 20001, True, 1.5, '200', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                ReaderChatDefaults(length_characters={'short': {'min': invalid, 'max': 600}})
        for ranges in ({'short': {'min': 601, 'max': 600}},
                       {'short': {'min': 700, 'max': 1700}},
                       {'long': {'min': 1, 'max': 4000}}, {'unknown': {'min': 1, 'max': 2}}):
            with self.subTest(ranges=ranges), self.assertRaises(ValidationError):
                CharacterRanges.model_validate(ranges)

    def test_personal_ranges_round_trip_without_changing_other_reader_settings(self):
        chat = ReaderChatDefaults(response_length='medium', language='fa', length_characters={
            'short': {'min': 230, 'max': 510}, 'medium': {'min': 710, 'max': 1510},
            'long': {'min': 1710, 'max': 4310}}).model_dump()
        user = SimpleNamespace(preferences={'reader_portal': {'columns': 3, 'theme': 'dark', 'chat': chat}})
        restored = admin._reader_preferences_from_user(user)
        self.assertEqual(restored['chat'], chat)
        self.assertEqual((restored['columns'], restored['theme']), (3, 'dark'))

    def test_all_explicit_lengths_control_prompt_in_each_language_and_intent(self):
        ranges = CharacterRanges(short={'min': 230, 'max': 510})
        for language in ('fa', 'en', 'tr', 'ar', 'es', 'it', 'de', 'fr'):
            for intent in ('question', 'risks', 'opportunities', 'meeting', 'compare', 'critique', 'action_draft', 'correction_review'):
                for mode, interval in [('short', '230-510'), ('medium', '600-1600'), ('long', '1600-4000')]:
                    with self.subTest(language=language, intent=intent, mode=mode):
                        messages = prompt(context_for('Published evidence', None), 'Question', language, [], None,
                                          24000, intent, AnswerLength(mode=mode, characters=ranges))
                        self.assertIn(interval + ' characters', messages[0]['content'])
                        self.assertIn('Preserve essential qualifications and exact citations', messages[0]['content'])
                        self.assertIn('Published evidence', messages[1]['content'])

    def test_auto_lets_model_choose_and_does_not_apply_custom_ranges(self):
        length = AnswerLength(mode='auto', characters={'short': {'min': 333, 'max': 555}})
        self.assertIn('Choose the answer length yourself', length.instruction())
        self.assertNotIn('333-555', length.instruction())

    def test_length_instruction_counts_toward_input_bound(self):
        ctx = context_for('Published evidence', None)
        ordinary = prompt(ctx, 'Q', 'en', [], None, 24000)
        size = sum(len(m['content']) for m in ordinary) + 100
        with self.assertRaises(ValueError):
            prompt(ctx, 'Q', 'en', [], None, size, answer_length=AnswerLength(mode='long'))

    def test_request_length_is_optional_but_explicit_values_are_validated(self):
        base = dict(model_key='openai:fixture-v1', question='Q', idempotency_key='length-fixture-request', context_version='a'*64)
        self.assertIsNone(Question(**base).response_length)
        for mode in ('short', 'medium', 'long', 'auto'):
            self.assertEqual(Question(**base, response_length=mode).response_length, mode)
        for mode in ('brief', '', True):
            with self.assertRaises(ValidationError):
                Question(**base, response_length=mode)
        with self.assertRaises(ValidationError):
            Question(**base, length_characters={'short': {'min': 900, 'max': 100}})
