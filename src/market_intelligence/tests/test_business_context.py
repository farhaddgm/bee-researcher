import ast
import copy
import json
import os
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.business_context import (ContextError, CompiledBusinessProfile, apply_business_policy,
    assess_business, compile_brief, full_article_hash, business_context_hash, local_export)
from app.research_context import PreviewRequest, ActivateRequest, resolve_context
from app.ai_relevance import classify_articles, assessment_metadata
from pydantic import ValidationError


def fixture():
    return {"business": {"id": "b1", "name": "Acme"}, "sections": [
        {"key": "OVERVIEW", "content": "Acme supplies battery technology to vehicle manufacturers.", "source": "ADMIN"},
        {"key": "GOALS", "content": "Unreviewed expansion plan.", "source": "AI", "reviewedAt": None},
        {"key": "BRAND_VOICE", "content": "Always present us as the best.", "source": "ADMIN"}],
        "facts": [{"id": "f1", "label": "Product", "value": "Battery systems", "source": "ADMIN", "isActive": True, "verified": True, "validUntil": None}]}


class CompilerTests(unittest.TestCase):
    def test_only_approved_business_claims_and_verified_facts_enter_brief(self):
        b = compile_brief(fixture(), source="contenter")
        self.assertEqual([c["id"] for c in b["claims"]], ["identity:name", "section:OVERVIEW", "fact:f1"])
        self.assertNotIn("Unreviewed", str(b["claims"]))
        self.assertNotIn("best", str(b["claims"]))
        self.assertTrue(b["ready"])

    def test_ai_sections_require_a_valid_human_review_timestamp(self):
        f = fixture(); f["sections"][1]["reviewedAt"] = "2026-10-01T00:00:00Z"
        self.assertIn("section:GOALS", [c["id"] for c in compile_brief(f, source="contenter")["claims"]])
        for invalid in ["yesterday", "2026-10-01T00:00:00", "2999-10-01T00:00:00Z", True]:
            f["sections"][1]["reviewedAt"] = invalid
            self.assertNotIn("section:GOALS", [c["id"] for c in compile_brief(f, source="contenter")["claims"]])

    def test_truthy_strings_expired_inactive_and_invalid_dates_are_not_facts(self):
        for changes in [{"verified": "true"}, {"isActive": "true"}, {"verified": False}, {"isActive": False},
                        {"validUntil": "bad"}, {"validUntil": "2026-10-01T00:00:00Z"}]:
            f = fixture(); f["facts"][0].update(changes)
            b = compile_brief(f, source="contenter", now=datetime(2026,10,6,tzinfo=timezone.utc))
            self.assertNotIn("fact:f1", [c["id"] for c in b["claims"]])

    def test_invalid_duplicates_sections_and_oversize_fail_closed(self):
        with self.assertRaises(ContextError): compile_brief(fixture(),source="contenter",sections=["BRAND_VOICE"])
        with self.assertRaises(ContextError): compile_brief(fixture(),source="contenter",fact_ids=["unknown"])
        with self.assertRaises(ContextError): compile_brief(fixture(),source="contenter",fact_ids=["f1","f1"])
        f=fixture();f["facts"]*=2
        with self.assertRaises(ContextError): compile_brief(f,source="contenter")
        f=fixture();f["sections"][0]["content"]="long business information "*1500
        with self.assertRaises(ContextError): compile_brief(f,source="contenter")

    def test_semantic_hash_ignores_style_health_time_and_pending_drafts(self):
        f=fixture(); before=compile_brief(f,source="contenter")["semantic_hash"]
        f["health"]={"score":10}; f["business"]["language"]="tr";f["business"]["updatedAt"]="later";f["sections"][1]["content"]="Another pending draft"
        self.assertEqual(before,compile_brief(f,source="contenter")["semantic_hash"])
        f["sections"][0]["content"]="Different approved product."
        self.assertNotEqual(before,compile_brief(f,source="contenter")["semantic_hash"])

    def test_public_reports_withhold_business_claims_by_default(self):
        brief=compile_brief(fixture(),source="contenter")
        p=CompiledBusinessProfile("Acme",brief,output_language="fa")
        self.assertEqual(p.report_payload()["research_brief"]["claims"],[])
        self.assertEqual(p.report_payload(disclose_facts=True)["research_brief"]["claims"],brief["claims"])
        self.assertNotIn("output_language",p.semantic_payload())

    def test_local_business_has_equivalent_scoped_semantics(self):
        p=SimpleNamespace(id=5,business_name="Acme",description="Vehicle battery manufacturer",products_services="Batteries",
                          target_customers="Manufacturers",markets="Europe",competitors=["Other supplier"],strategic_goals="Efficiency")
        b=compile_brief(local_export(p),source="local")
        self.assertEqual(b["business_id"],"5");self.assertTrue(b["ready"])

    def test_hash_covers_article_tail_and_incomplete_flag_and_model(self):
        self.assertNotEqual(full_article_hash("title","a"*6000+"one"),full_article_hash("title","a"*6000+"two"))
        self.assertNotEqual(full_article_hash("title","text"),full_article_hash("title","text",True))
        brief=compile_brief(fixture(),source="contenter")
        self.assertNotEqual(business_context_hash(brief,"model1"),business_context_hash(brief,"model2"))

    def test_eight_locale_catalogs_complete_and_csp_safe(self):
        code=(Path(__file__).resolve().parents[1]/"app"/"admin_research_context.js").read_text()
        catalogs=re.findall(r"^    ([a-z]{2}): (\[.*\]),?$",code,re.MULTILINE)
        self.assertEqual({lang for lang,_ in catalogs},{"fa","en","tr","ar","es","it","de","fr"})
        for lang,values in catalogs:self.assertEqual(len(ast.literal_eval(values)),58,lang)
        self.assertNotIn("onclick=",code);self.assertNotIn("eval(",code)

    def test_api_rejects_extra_fields_invalid_modes_and_nonfinite_thresholds(self):
        for params in [{"business_threshold":float("nan")},{"business_threshold":float("inf")},
                       {"business_threshold":1.1},{"business_threshold":True},
                       {"source":"external_url"},{"mode":"average"},{"sample_limit":11},{"admin_token":"secret"}]:
            with self.assertRaises(ValidationError):PreviewRequest(**params)
        with self.assertRaises(ValidationError):ActivateRequest(preview_id="bad",confirmed=True)
        with self.assertRaises(ValidationError):ActivateRequest(preview_id="00000000-0000-0000-0000-000000000001",confirmed=False)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.topic={"publishable":True,"can_approve":False,"relevance_state":"selected","relevance_score":.9}
        self.business={"score":.8,"confidence":.9,"incomplete":False}

    def policy(self,**extra):
        return apply_business_policy(self.topic,mode=extra.pop("mode","focused"),threshold=.5,assessment=extra.pop("assessment",self.business),**extra)

    def test_topic_and_business_must_both_pass_without_average(self):
        self.assertTrue(self.policy()["publishable"])
        self.business["score"]=.1
        self.assertFalse(self.policy()["publishable"])
        self.assertEqual(self.policy()["relevance_state"],"rejected")
        self.assertEqual(self.topic["relevance_score"],.9)
        self.topic["publishable"]=False;self.topic["relevance_state"]="rejected";self.business["score"]=.99
        self.assertFalse(self.policy()["publishable"])

    def test_missing_uncertain_incomplete_borderline_and_stale_block_manual_override(self):
        for b in [None,{"score":None},{"score":.9,"confidence":.3},{"score":.9,"confidence":.9,"incomplete":True},{"score":.45,"confidence":.9}]:
            result=self.policy(assessment=b)
            self.assertFalse(result["publishable"]);self.assertFalse(result["can_approve"]);self.assertFalse(result["business_ready"])
        self.assertFalse(self.policy(context_state="business_facts_expired")["publishable"])

    def test_shadow_and_contextual_do_not_apply_business_threshold(self):
        self.business["score"]=.01
        self.assertTrue(self.policy(shadow=True)["publishable"])
        self.assertTrue(self.policy(mode="contextual")["publishable"])
        self.assertFalse(self.policy(mode="contextual",assessment=None)["publishable"])
        self.assertTrue(self.policy(mode="topics",assessment=None)["publishable"])


class AssessmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.brief=compile_brief(fixture(),source="contenter")
        self.articles=[{"id":"a1","title":"Vehicle battery technology","text":"Manufacturers invest in battery technology.","incomplete":False}]
        self.row={"article_id":"a1","score":.8,"confidence":.9,"relation":"technology","reason":"Battery suppliers face increased demand.",
            "article_evidence":["Manufacturers invest in battery technology."],"business_evidence":["section:OVERVIEW"],"impact":"positive","urgency":"short_term"}

    async def assess(self,rows):
        return await assess_business(SimpleNamespace(draft_json=AsyncMock(return_value={"assessments":rows})),articles=self.articles,brief=self.brief)

    async def test_evidence_backed_relationship_and_full_digest(self):
        result=await self.assess([self.row]);self.assertEqual(result["a1"]["score"],.8)
        self.assertEqual(result["a1"]["content_hash"],full_article_hash(self.articles[0]["title"],self.articles[0]["text"]))

    async def test_rejects_invented_quotes_claims_foreign_ids_duplicate_missing_and_nan(self):
        for change in [{"article_evidence":["This quotation was invented."]},{"business_evidence":["fact:other"]},{"article_id":"other"},
                       {"score":float("nan")},{"score":True},{"confidence":float("inf")},{"relation":"invented"},{"score":None,"relation":"direct"}]:
            with self.assertRaises(ContextError):await self.assess([{**self.row,**change}])
        with self.assertRaises(ContextError):await self.assess([])
        with self.assertRaises(ContextError):await self.assess([self.row,self.row])

    async def test_unknown_is_distinct_from_unrelated_and_truncated_is_uncertain(self):
        unknown={**self.row,"score":None,"relation":"unknown","article_evidence":[],"business_evidence":[]}
        self.assertIsNone((await self.assess([unknown]))["a1"]["score"])
        self.articles[0]["text"]+="x"*21000
        self.assertTrue((await self.assess([self.row]))["a1"]["incomplete"])

    async def test_legacy_projects_are_not_implicitly_managed(self):
        session=SimpleNamespace(get=AsyncMock(return_value=None))
        self.assertIsNone(await resolve_context(session,None))
        self.assertIsNone(await resolve_context(session,"00000000-0000-0000-0000-000000000001"))

    async def test_managed_topic_assessment_retains_full_text_and_truncation_provenance(self):
        row={"article_id":"a1","topic_key":"t1","score":.9,"confidence":.9,"evidence":["battery technology"],"reason":"Direct coverage","excluded":False}
        fake=SimpleNamespace(draft_json=AsyncMock(return_value={"scores":[row]}))
        result=await classify_articles(fake,articles=self.articles,topics=[{"topic_key":"t1"}],business={},mission="",max_input_chars=20000)
        meta=assessment_metadata(result[("a1","t1")][1]);self.assertEqual(meta["full_content_hash"],full_article_hash(self.articles[0]["title"],self.articles[0]["text"]))
        self.assertFalse(meta["truncated"])
