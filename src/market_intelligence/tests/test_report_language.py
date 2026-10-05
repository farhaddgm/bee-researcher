import json
import os
import unittest
from types import SimpleNamespace

import httpx

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.config import Settings  # noqa: E402
from app.openai_client import OpenAIClient  # noqa: E402
from app.pipeline_service import _render_publication_message  # noqa: E402
from app.report_language import LANGUAGES, LIST_FIELDS, TEXT_FIELDS, ReportLanguageError, language_instructions, language_issues, prose_matches_language, report_copy  # noqa: E402
from app.telegram_delivery import render_analysis_message  # noqa: E402


def fields():
    return {**dict.fromkeys(TEXT_FIELDS, "این خبر دربارهٔ معرفی مدل جدید است."), "headline": "گوگل مدل تازه‌ای معرفی کرد", "facts": ["مدل جدید معرفی شد."], "inferences": ["بررسی تکمیلی لازم است."]}


class ReportLanguageTests(unittest.TestCase):
    def test_detects_untranslated_sentences_and_scattered_words(self):
        for text in ("Google announced a new model", "گوگل یک new model معرفی کرد", "مدل برای inference آماده است", "به گفتهٔ شرکت: ‘The model is now available’"):
            self.assertFalse(prose_matches_language(text, "fa"), text)

    def test_preserves_names_acronyms_models_and_urls(self):
        self.assertTrue(prose_matches_language("OpenAI مدل GPT-6 را با API و GPU معرفی کرد؛ https://example.org/new-model", "fa"))
        self.assertTrue(prose_matches_language("شرکت TechCrunch از Gemini و ChatGPT گزارش داد.", "fa"))

    def test_repeated_proper_names_do_not_reject_complete_translation(self):
        self.assertTrue(prose_matches_language("مدل Sonnet معرفی شد؛ Sonnet ارتقا یافته و Sonnet قبلی همچنان در دسترس است.", "fa"))
        self.assertTrue(prose_matches_language("مدل Codex عرضه شد؛ Codex تازه جایگزین Codex قبلی می‌شود.", "fa"))
        self.assertTrue(prose_matches_language("مدل‌های Sonnet و Opus و Haiku بررسی شدند.", "fa"))
        self.assertFalse(prose_matches_language("خبر: Google Announced A New Model", "fa"))
        self.assertFalse(prose_matches_language("مدل برای inference و reasoning آماده است", "fa"))

    def test_license_and_section_titles_are_translated_not_blanket_exempted(self):
        self.assertFalse(prose_matches_language("این خبر با Creative Commons Attribution Non-Commercial No Derivatives منتشر شده است", "fa"))
        self.assertTrue(prose_matches_language("این خبر با مجوز کرییتیو کامنز با شرط انتساب، غیرتجاری و بدون اقتباس منتشر شده است؛ CC BY-NC-ND", "fa"))
        self.assertIn("time_horizon", language_instructions("fa"))
        self.assertIn("Attribution Non-Commercial No Derivatives = انتساب", language_instructions("fa"))
        self.assertNotIn("اخبار ام‌آی‌تی", language_instructions("en"))

    def test_checks_facts_inferences_and_score_reasons_not_identifiers(self):
        payload = fields()
        payload.update(facts=["The model was announced"], inferences=["Possible market impact"], topic_scores=[{"topic_key": "AI-research", "score": .9, "reason": "This news is relevant"}])
        self.assertEqual(["facts[0]", "inferences[0]", "topic_scores[0].reason"], language_issues(payload, "fa"))

    def test_uses_complete_translated_title_keeps_original_immutable(self):
        article = SimpleNamespace(title="Google announced a new model", canonical_url="https://example.org/1", published_at=None, extraction_status="complete")
        analysis = SimpleNamespace(**fields(), confidence=.9, citations=[{"output_language": "fa"}])
        result = _render_publication_message(analysis=analysis, article=article, source=SimpleNamespace(name="TechCrunch", output_language="fa"))
        self.assertIn("گوگل مدل تازه‌ای معرفی کرد", result)
        self.assertNotIn("Google announced", result)
        self.assertEqual("Google announced a new model", article.title)

    def test_partial_fallback_cannot_look_translated(self):
        analysis = SimpleNamespace(**{**fields(), "news_summary": "Google announced a new model"}, confidence=.4)
        result = _render_publication_message(analysis=analysis, article=SimpleNamespace(title="Google announced a new model", canonical_url="https://example.org/1", published_at=None, extraction_status="complete"), source=SimpleNamespace(name="TechCrunch", output_language="fa"))
        self.assertIn("در انتظار ترجمهٔ کامل", result)
        self.assertNotIn("Google announced", result)
        self.assertIn("https://example.org/1", result)

    def test_report_locale_is_not_backoffice_locale(self):
        for language in LANGUAGES:
            labels = report_copy(language)
            result = render_analysis_message(headline=labels["pending_title"], summary=labels["pending_summary"], business_connection=labels["analysis_pending"], opportunity="", risk="", action="", confidence=.1, source_name="TechCrunch", source_url="https://example.org/1", published_at=None, incomplete=False, business_name="AI", output_language=language, template_blocks=[{"type": "title"}, {"type": "summary"}, {"type": "source"}])
            self.assertIn(labels["source"], result)
            self.assertIn("TechCrunch", result)
            if language not in {"fa", "ar"}:
                self.assertNotIn("منبع", result)

    def test_two_latin_languages_need_translated_title_and_current_language(self):
        prose = {**dict.fromkeys(TEXT_FIELDS, "Ein neues Modell wurde angekündigt."), "headline": "Google stellt ein neues Modell vor", "facts": [], "inferences": []}
        article = SimpleNamespace(title="Google announced a new model", language="en", canonical_url="https://example.org/1", published_at=None, extraction_status="complete")
        source = SimpleNamespace(name="TechCrunch", output_language="de")
        analysis = SimpleNamespace(**prose, confidence=.9, citations=[{"output_language": "de"}])
        result = _render_publication_message(analysis=analysis, article=article, source=source)
        self.assertIn("Google stellt", result)
        self.assertNotIn("Google announced", result)
        analysis.citations = [{"output_language": "en"}]
        stale = _render_publication_message(analysis=analysis, article=article, source=source)
        self.assertIn("Vollständige Übersetzung ausstehend", stale)


class TranslationClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self, payload, *, status="completed"):
        def handler(request):
            body = json.loads(request.content)
            self.assertFalse(body["store"])
            self.assertIn("ALL reader-facing prose", body["input"][0]["content"])
            self.assertEqual("complete_news_translation", body["text"]["format"]["name"])
            return httpx.Response(200, json={"status": status, "model": "fixture", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]}], "usage": {"input_tokens": 100, "output_tokens": 80}})
        config = Settings(postgres_db="assistant_test", postgres_user="assistant_test", postgres_password="test", redis_password="test", openai_api_key="fixture", external_analysis_approved=True, _env_file=None)
        return OpenAIClient(config, transport=httpx.MockTransport(handler))

    async def test_translation_covers_every_prose_field(self):
        result = await self.client(fields()).translate_report(fields=fields(), output_language="fa")
        self.assertEqual("fa", result.payload["_report_language"]["output_language"])
        self.assertEqual(100, result.input_tokens)
        self.assertEqual(80, result.output_tokens)
        self.assertEqual(set((*TEXT_FIELDS, *LIST_FIELDS, "_report_language")), set(result.payload))

    async def test_rejects_partial_translation(self):
        with self.assertRaises(ReportLanguageError):
            await self.client({**fields(), "risk": "Some risks remain"}).translate_report(fields=fields(), output_language="fa")

    async def test_rejects_missing_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "omitted evidence"):
            await self.client({**fields(), "facts": []}).translate_report(fields=fields(), output_language="fa")

    async def test_rejects_token_truncated_translation(self):
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            await self.client(fields(), status="incomplete").translate_report(fields=fields(), output_language="fa")

    async def test_batch_identities_evidence_and_locale_are_mandatory(self):
        source = {"one": fields(), "two": fields()}
        valid = {"reports": [{"report_id": key, **fields()} for key in source]}
        for payload, error in (({"reports": valid["reports"][:1]}, "identities"), ({"reports": [{**row, "report_id": "one"} for row in valid["reports"]]}, "identities"), ({"reports": [{**row, "facts": []} for row in valid["reports"]]}, "evidence")):
            client = self.client(fields())
            async def post(_path, _body, response=payload):
                return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(response)}]}]}
            client._post = post
            with self.assertRaisesRegex(RuntimeError, error):
                await client.translate_reports(reports=source, output_language="fa")

    async def test_batch_is_bounded_before_calling_provider(self):
        with self.assertRaisesRegex(ValueError, "one to three"):
            await self.client(fields()).translate_reports(reports={str(i): fields() for i in range(4)}, output_language="fa")
