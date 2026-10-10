"""Real isolated Postgres/API acceptance. Never run against a real deployment."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import func, select, update

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    AdminSession,
    AdminUser,
    AssistantWorkspace,
    BusinessProfile,
    Publication,
    Topic,
)
from app.admin import hash_password_async
from app.report_portal.models import (
    InternalReport,
    InternalReportJob,
    InternalReportVersion,
    ReportBusiness,
    ReportGrant,
)
from app.report_portal.policy import bind_business
from app.report_portal.service import execute_job
from app.report_portal import deletions
from app.main import app

cfg = get_settings()
assert cfg.environment != "production" and cfg.postgres_host.startswith(
    "bee-report-"
), "isolated fixture database required"
assert cfg.report_portal_enabled
PASSWORD = "Synthetic-report-test-42!"


async def seed():
    from app.report_portal.deletions import prepare

    await prepare()
    async with SessionLocal() as s:
        users = [
            AdminUser(
                id=uuid.uuid4(),
                username="report-" + uuid.uuid4().hex[:8],
                display_name="Synthetic reporter",
                role="viewer",
                active=True,
                login_method="password",
                password_hash=await hash_password_async(PASSWORD),
            )
            for _ in range(4)
        ]
        if cfg.owner_email:
            existing = await s.scalar(
                select(AdminUser).where(AdminUser.email == cfg.owner_email)
            )
            if existing:
                users[3] = existing
            else:
                users[3].email = cfg.owner_email
        s.add_all(users)
        projects = []
        for index in range(2):
            w = AssistantWorkspace(
                id=uuid.uuid4(),
                slug="report-" + uuid.uuid4().hex[:8],
                name="Synthetic project",
                description="Synthetic business news",
                business_name="Synthetic business",
                status="active",
                config={},
            )
            s.add(w)
            await s.flush()
            projects.append(w)
            pid = (
                int(
                    await s.scalar(
                        select(func.coalesce(func.max(BusinessProfile.id), 0))
                    )
                )
                + 1
            )
            s.add(
                BusinessProfile(
                    id=pid,
                    assistant_id=w.id,
                    business_name="Same name",
                    description="Produces software for companies",
                    products_services="Business software and analytics",
                    target_customers="Small companies",
                    markets="Europe",
                    output_tone="Formal",
                    source_revision="report-test",
                )
            )
            s.add(
                Topic(
                    assistant_id=w.id,
                    topic_key="T-TEST",
                    name="Software",
                    definition="Software product launches",
                    positive_terms=["software"],
                    negative_terms=[],
                    threshold=0.95,
                    source_revision="test",
                )
            )
            await s.flush()
            b = await bind_business(s, w.id)
            b.policy = {
                "consented_at": "2026-10-10",
                "models": [cfg.analysis_model],
                "daily_cap": 10,
                "daily_budget_usd": 1,
                "retention_days": 90,
            }
            if index == 0:
                s.add(
                    ReportGrant(
                        business_id=b.id,
                        user_id=users[0].id,
                        role="reporter",
                        assistant_ids=[str(w.id)],
                    )
                )
                s.add(
                    ReportGrant(
                        business_id=b.id,
                        user_id=users[2].id,
                        role="manager",
                        assistant_ids=[str(w.id)],
                    )
                )
            else:
                s.add(
                    ReportGrant(
                        business_id=b.id,
                        user_id=users[1].id,
                        role="reporter",
                        assistant_ids=[str(w.id)],
                    )
                )
        await s.commit()
        return users, projects


async def main():
    users, projects = await seed()
    checks = 0

    async def check(condition, name):
        nonlocal checks
        assert condition, name
        checks += 1

    clients = [
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        )
        for _ in users
    ]
    try:
        for index, c in enumerate(clients):
            r = await c.post(
                "/report/api/login",
                json={"username": users[index].username, "password": PASSWORD},
            )
            await check(
                r.status_code == (403 if index == 3 else 200), "login explicit grant"
            )
            if index != 3:
                c.headers["X-CSRF-Token"] = c.cookies.get("research_bee_report_csrf")
        a, b, manager, owner = clients
        business = (await a.get("/report/api/businesses")).json()["items"][0]
        foreign = (await b.get("/report/api/businesses")).json()["items"][0]
        await check(business["id"] != foreign["id"], "same-name business isolation")
        payload = {
            "draft_key": str(uuid.uuid4()),
            "business_id": business["id"],
            "assistant_id": str(projects[0].id),
            "title": "Synthetic private software launch",
            "text": "The company launched new software for small companies. PRIVATE-MARKER-20261010. This information is a private company assertion.",
            "reporter": "Editable display name",
            "tags": ["software"],
            "language": "en",
        }
        r = await a.post("/report/api/reports", json=payload)
        await check(r.status_code == 200, "draft create")
        rid = r.json()["id"]
        retried = await a.post("/report/api/reports", json=payload)
        await check(
            retried.status_code == 200 and retried.json()["id"] == rid,
            "idempotent draft retry",
        )
        r = await b.get("/report/api/reports/" + rid)
        await check(r.status_code == 404, "foreign detail denied")
        r = await owner.get("/report/api/reports/" + rid)
        await check(r.status_code == 401, "owner no implicit content")
        r = await manager.get("/report/api/reports/" + rid)
        await check(r.status_code == 200, "manager business scope")
        await check(r.json()["can_edit"] is False, "manager cannot edit another author")
        listing = await b.get(
            "/report/api/reports", params={"business_id": business["id"]}
        )
        await check(listing.status_code == 404, "foreign list denied")
        r = await a.post(
            "/report/api/reports", json={**payload, "author_id": str(users[2].id)}
        )
        await check(
            r.status_code == 422 and "PRIVATE-MARKER" not in r.text,
            "mass assignment and validation privacy",
        )
        r = await a.put("/report/api/reports/" + rid, json={**payload, "revision": 9})
        await check(r.status_code == 409, "optimistic draft conflict")
        async with SessionLocal() as s:
            v = await s.scalar(
                select(InternalReportVersion).where(
                    InternalReportVersion.report_id == uuid.UUID(rid)
                )
            )
            await check("PRIVATE-MARKER" not in v.ciphertext, "at rest encryption")
            await check(
                (await s.get(InternalReport, uuid.UUID(rid))).author_id == users[0].id,
                "author immutable",
            )
            public_before = await s.scalar(select(func.count(Publication.id)))
        key = str(uuid.uuid4())
        request = {"idempotency_key": key, "revision": 1, "confirmed": True}
        r = await a.post("/report/api/reports/" + rid + "/submit", json=request)
        await check(r.status_code == 200, "queue submit")
        jobid = r.json()["job_id"]
        r2 = await a.post("/report/api/reports/" + rid + "/submit", json=request)
        await check(r2.json()["job_id"] == jobid, "idempotent submit")
        r = await a.put("/report/api/reports/" + rid, json={**payload, "revision": 1})
        await check(r.status_code == 409, "sealed content immutable")
        calls = []

        def fake(req):
            data = json.loads(req.content)
            calls.append(data)
            assert data["store"] is False and not data.get("tools")
            raw = json.loads(data["input"][1]["content"])
            name = data["text"]["format"]["name"]
            if name == "article_relevance":
                aid = raw["articles"][0]["article_id"]
                out = {
                    "scores": [
                        {
                            "article_id": aid,
                            "topic_key": "T-TEST",
                            "score": 0.2,
                            "confidence": 0.9,
                            "reason": "Software launch relates to the selected topic.",
                            "evidence": [
                                "The company launched new software for small companies."
                            ],
                            "excluded": False,
                        }
                    ]
                }
            elif name == "news_business_relationship":
                aid = raw["articles"][0]["article_id"]
                out = {
                    "assessments": [
                        {
                            "article_id": aid,
                            "score": 0.8,
                            "confidence": 0.9,
                            "relation": "direct",
                            "reason": "The reported product is related to the business.",
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
                            "content": [
                                {"type": "output_text", "text": json.dumps(out)}
                            ],
                        }
                    ],
                },
            )

        async with SessionLocal() as s:
            j = await s.get(InternalReportJob, uuid.UUID(jobid))
            j.status = "running"
            j.started_at = datetime.now(timezone.utc)
            await s.commit()
        await execute_job(uuid.UUID(jobid), transport=httpx.MockTransport(fake))
        result = (await a.get("/report/api/reports/" + rid)).json()
        job = result["jobs"][0]
        await check(
            job["status"] == "succeeded",
            "analysis success: " + str(job.get("error_code")),
        )
        await check(len(calls) == 3, "scoring business analysis provider calls")
        await check(
            job["result"]["relevance"]["relevance_state"] == "rejected",
            "low relevance still analyzed",
        )
        await check(
            job["result"]["public_publishable"] is False, "no public publishability"
        )
        async with SessionLocal() as s:
            await check(
                await s.scalar(select(func.count(Publication.id))) == public_before,
                "public ledger unchanged",
            )
        r = await a.post("/report/api/reports/" + rid + "/revise", json={})
        await check(r.status_code == 200, "append revision")
        detail = (await a.get("/report/api/reports/" + rid)).json()
        await check(
            len(detail["versions"]) == 2
            and detail["versions"][0]["text"] == payload["text"],
            "original retained",
        )
        r = await a.put(
            "/report/api/reports/" + rid,
            json={**payload, "classification": "very_confidential", "revision": 1},
        )
        await check(r.status_code == 200, "very confidential draft")
        r = await a.post(
            "/report/api/reports/" + rid + "/submit",
            json={**request, "revision": 2, "idempotency_key": str(uuid.uuid4())},
        )
        await check(
            r.status_code == 409
            and r.json()["detail"] == "report_confidential_blocked",
            "external sensitive blocked",
        )
        probe = await a.post(
            "/report/api/reports", json={**payload, "draft_key": str(uuid.uuid4())}
        )
        probe_id = probe.json()["id"]
        async with SessionLocal() as s:
            biz = await s.get(ReportBusiness, uuid.UUID(business["id"]))
            biz.policy = {**biz.policy, "daily_cap": 1}
            await s.commit()
        r = await a.post(
            "/report/api/reports/" + probe_id + "/submit",
            json={**request, "idempotency_key": str(uuid.uuid4())},
        )
        await check(
            r.status_code == 429 and r.json()["detail"] == "report_daily_cap",
            "atomic business quota",
        )
        await check(
            (await a.get("/report/api/reports/" + probe_id)).json()["state"] == "draft",
            "quota preserves draft",
        )
        revoked = await manager.delete(
            "/report/api/businesses/" + business["id"] + "/consent"
        )
        await check(revoked.status_code == 200, "manager can revoke provider consent")
        r = await a.post(
            "/report/api/reports/" + probe_id + "/submit",
            json={**request, "idempotency_key": str(uuid.uuid4())},
        )
        await check(
            r.status_code == 409 and r.json()["detail"] == "report_consent_required",
            "revoked consent blocks new jobs",
        )
        r = await manager.put(
            "/report/api/businesses/" + business["id"] + "/consent",
            json={
                "confirmed": True,
                "models": [cfg.analysis_model],
                "daily_cap": 10,
                "daily_budget_usd": 0.00001,
                "retention_days": 90,
            },
        )
        await check(r.status_code == 200, "manager can approve bounded provider policy")
        r = await a.post(
            "/report/api/reports/" + probe_id + "/submit",
            json={**request, "idempotency_key": str(uuid.uuid4())},
        )
        await check(
            r.status_code == 429 and r.json()["detail"] == "report_budget_exhausted",
            "conservative budget gate",
        )
        async with SessionLocal() as s:
            w = await s.get(AssistantWorkspace, projects[0].id)
            w.config = {"active_business_id": None}
            await s.commit()
        r = await a.put(
            "/report/api/reports/" + probe_id, json={**payload, "revision": 1}
        )
        await check(r.status_code == 409, "unlinked business blocks fresh content")
        async with SessionLocal() as s:
            w = await s.get(AssistantWorkspace, projects[0].id)
            w.config = {}
            await s.commit()
        r = await a.delete("/report/api/reports/" + rid)
        await check(r.status_code == 200, "delete")
        r = await a.get("/report/api/reports/" + rid)
        await check(r.status_code == 404, "deleted not readable")
        async with SessionLocal() as s:
            j = await s.get(InternalReportJob, uuid.UUID(jobid))
            await check(
                j is not None and j.ciphertext == "" and j.input_snapshot == "",
                "purge retains financial ledger only",
            )
            await check(
                await s.scalar(
                    select(func.count(InternalReportVersion.id)).where(
                        InternalReportVersion.report_id == uuid.UUID(rid)
                    )
                )
                == 0,
                "all versions purged",
            )
            original = await s.get(InternalReport, uuid.UUID(rid))
            original.state = "draft"
            original.deleted_at = None
            await s.commit()
        await check(
            (await a.get("/report/api/reports/" + rid)).status_code == 404,
            "external tombstone blocks backup restoration",
        )
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
            cookies={
                "research_bee_report_session": a.cookies.get(
                    "research_bee_report_session"
                )
            },
        )
        r = await c.post("/report/api/reports", json=payload)
        await check(r.status_code == 403, "csrf")
        await c.aclose()
        copied = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
            cookies={
                "research_bee_user_session": a.cookies.get(
                    "research_bee_report_session"
                )
            },
        )
        r = await copied.get("/user/api/me")
        await check(r.status_code == 401, "portal cookie transplantation")
        await copied.aclose()
        nightly = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        )
        r = await nightly.post(
            "/report/api/login",
            json={"username": users[0].username, "password": PASSWORD},
        )
        import hashlib

        async with SessionLocal() as s:
            auth = await s.scalar(
                select(AdminSession).where(
                    AdminSession.token_hash
                    == hashlib.sha256(
                        nightly.cookies.get("research_bee_report_session").encode()
                    ).hexdigest()
                )
            )
            auth.created_at = datetime.now(timezone.utc) - timedelta(days=2)
            auth.expires_at = datetime.now(timezone.utc) + timedelta(hours=5)
            await s.commit()
        await check(
            (await nightly.get("/report/api/me")).status_code == 401,
            "nightly cutoff independent of refreshed expiry",
        )
        await nightly.aclose()
        async with SessionLocal() as s:
            grant = await s.scalar(
                select(ReportGrant).where(ReportGrant.user_id == users[1].id)
            )
            grant.active = False
            await s.commit()
        r = await b.get("/report/api/me")
        await check(r.status_code == 401, "immediate grant revocation")
        r = await a.get("/report")
        await check(
            r.headers.get("cache-control") == "no-store"
            and "noindex" in r.headers.get("x-robots-tag", ""),
            "private document headers",
        )
        print(
            json.dumps(
                {
                    "checks": checks,
                    "provider_calls": len(calls),
                    "synthetic_only": True,
                    "status": "passed",
                }
            )
        )
        return users, projects
    finally:
        for c in clients:
            await c.aclose()


if __name__ == "__main__":
    asyncio.run(main())
