"""Synthetic browser fixture. Refuses production; no external provider access."""

from contextlib import asynccontextmanager
import json

import httpx
from app.config import get_settings
from app.database import engine
from app.main import app
from app.report_portal import provider
from scripts.verify_report_portal import seed

cfg = get_settings()
assert cfg.environment != "production" and cfg.postgres_host.startswith(
    "bee-report-"
), "isolated database required"


def fake(request):
    data = json.loads(request.content)
    assert data.get("store") is False and not data.get("tools")
    raw = json.loads(data["input"][1]["content"])
    name = data["text"]["format"]["name"]
    if name == "article_relevance":
        aid = raw["articles"][0]["article_id"]
        out = {
            "scores": [
                {
                    "article_id": aid,
                    "topic_key": t["topic_key"],
                    "score": 0.2,
                    "confidence": 0.9,
                    "reason": "A synthetic software launch relates to the topic.",
                    "evidence": [
                        "The company launched new software for small companies."
                    ],
                    "excluded": False,
                }
                for t in raw["approved_topics"]
            ]
        }
    elif name == "news_business_relationship":
        out = {
            "assessments": [
                {
                    "article_id": raw["articles"][0]["article_id"],
                    "score": 0.8,
                    "confidence": 0.9,
                    "relation": "direct",
                    "reason": "The launch concerns the business products.",
                    "article_evidence": [
                        "The company launched new software for small companies."
                    ],
                    "business_evidence": [raw["business_claims"][1]["id"]],
                    "impact": "positive",
                    "urgency": "short_term",
                }
            ]
        }
    else:
        out = {
            "headline": "Company reports a software launch",
            "news_summary": "The company says it launched software for small companies.",
            "business_connection": "The claimed launch concerns the company's software products.",
            "opportunity": "Customers may find the product useful.",
            "risk": "The claim has not been independently verified.",
            "suggested_action": "Verify the launch and customer interest.",
            "time_horizon": "Short term",
            "confidence": 0.8,
            "facts": ["The company reports a software launch."],
            "inferences": ["The launch may attract customers."],
            "topic_scores": [],
        }
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "model": cfg.analysis_model,
            "usage": {"input_tokens": 100, "output_tokens": 100},
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(out)}],
                }
            ],
        },
    )


Original = provider.PrivateClient


class SyntheticClient(Original):
    def __init__(self, settings, *, transport=None, guard):
        super().__init__(settings, transport=httpx.MockTransport(fake), guard=guard)


provider.PrivateClient = SyntheticClient


async def fixtures():
    users, projects = await seed()
    value = {
        "reporter": users[0].username,
        "manager": users[2].username,
        "owner": users[3].username,
        "project": str(projects[0].id),
    }
    await engine.dispose()
    return value


FIXTURE = {}
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def fixture_lifespan(application):
    global FIXTURE
    FIXTURE = await fixtures()
    async with original_lifespan(application):
        yield


app.router.lifespan_context = fixture_lifespan


@app.get("/_report_fixture", include_in_schema=False)
async def fixture():
    return FIXTURE
