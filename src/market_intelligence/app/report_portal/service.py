"""Private drafts and durable analysis jobs. No public publication side effects."""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update

from app.config import get_settings
from app.database import SessionLocal
from app.models import AdminUser, AssistantWorkspace, BusinessProfile, Topic
from . import deletions
from .crypto import decrypt, encrypt
from .models import (
    InternalReport,
    InternalReportJob,
    InternalReportVersion,
    ReportAudit,
    ReportBusiness,
    ReportDeletion,
)
from .policy import allow_analysis, binding_for, grant_for


def now():
    return datetime.now(timezone.utc)


def audit(session, user, report, action):
    session.add(
        ReportAudit(
            user_id=user.id,
            business_id=report.business_id,
            report_id=report.id,
            action=action,
        )
    )


async def business_profile(session, business, assistant_id, settings):
    from app.research_context import resolve_context
    from app.business_context import (
        CompiledBusinessProfile,
        compile_brief,
        local_export,
        empty_brief,
    )

    context = await resolve_context(session, assistant_id, settings)
    if context and context.state != "ready":
        raise HTTPException(409, "report_business_unavailable")
    if (
        context
        and context.record.source != "none"
        and context.record.brief.get("ready")
    ):
        return CompiledBusinessProfile(business.name, context.record.brief)
    if business.source_ref.startswith("local:"):
        raw = await session.get(
            BusinessProfile, int(business.source_ref.rsplit(":", 1)[1])
        )
        brief = compile_brief(local_export(raw), source="local")
        if brief["ready"]:
            return CompiledBusinessProfile(raw.business_name, brief)
        # There is an authorized business identity, but no usable approved
        # claims. Topic analysis may proceed without inventing a relationship.
        return CompiledBusinessProfile("", empty_brief())
    raise HTTPException(409, "report_business_unavailable")


async def accessible(session, user, report_id, *, lock=False):
    statement = select(InternalReport).where(InternalReport.id == report_id)
    if lock:
        statement = statement.with_for_update()
    report = await session.scalar(statement)
    if (
        not report
        or report.state == "deleted"
        or report.expires_at <= now()
        or deletions.contains(report_id)
    ):
        raise HTTPException(404, "report_not_found")
    grant = await grant_for(session, user, report.business_id, report.assistant_id)
    if grant.role != "manager" and report.author_id != user.id:
        raise HTTPException(404, "report_not_found")
    return report


async def save(user, payload, report_id=None):
    async with SessionLocal() as session:
        await grant_for(session, user, payload.business_id, payload.assistant_id)
        await binding_for(session, payload.business_id, payload.assistant_id)
        if report_id:
            report = await accessible(session, user, report_id, lock=True)
            if report.author_id != user.id or report.state != "draft":
                raise HTTPException(409, "report_original_immutable")
            if (
                report.business_id != payload.business_id
                or report.assistant_id != payload.assistant_id
            ):
                raise HTTPException(409, "report_business_immutable")
            version = await session.get(
                InternalReportVersion, report.current_version_id
            )
            if version.revision != payload.revision or version.sealed_at:
                raise HTTPException(409, "report_revision_conflict")
            version.revision += 1
        else:
            # The client keeps this random ID until the save is acknowledged.
            # Serialize per author: network retries and two save buttons must
            # not create duplicate drafts or race past the draft limit.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "private-report-draft:" + str(user.id)},
            )
            if payload.draft_key:
                existing = await session.get(InternalReport, payload.draft_key)
                if existing:
                    existing = await accessible(session, user, existing.id)
                    if (
                        existing.author_id != user.id
                        or existing.business_id != payload.business_id
                        or existing.assistant_id != payload.assistant_id
                    ):
                        raise HTTPException(404, "report_not_found")
                    v = await session.get(
                        InternalReportVersion, existing.current_version_id
                    )
                    return {"id": str(existing.id), "revision": v.revision}
            drafts = await session.scalar(
                select(func.count(InternalReport.id)).where(
                    InternalReport.author_id == user.id,
                    InternalReport.state == "draft",
                    InternalReport.expires_at > now(),
                )
            )
            if drafts >= 50:
                raise HTTPException(429, "report_draft_cap")
            report = InternalReport(
                id=payload.draft_key or uuid.uuid4(),
                business_id=payload.business_id,
                assistant_id=payload.assistant_id,
                author_id=user.id,
                current_version_id=uuid.uuid4(),
                expires_at=now()
                + timedelta(days=get_settings().report_draft_retention_days),
            )
            session.add(report)
            await session.flush()
            version = InternalReportVersion(
                id=report.current_version_id, report_id=report.id, number=1, revision=1
            )
            session.add(version)
        value = payload.model_dump(
            mode="json",
            exclude={"business_id", "assistant_id", "revision", "draft_key"},
        )
        version.content_hash = hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        version.ciphertext = encrypt(report.business_id, str(version.id), value)
        version.classification = payload.classification
        audit(session, user, report, "draft.saved")
        await session.commit()
        return {"id": str(report.id), "revision": version.revision}


async def detail(user, report_id):
    async with SessionLocal() as session:
        report = await accessible(session, user, report_id)
        versions = (
            await session.scalars(
                select(InternalReportVersion)
                .where(InternalReportVersion.report_id == report.id)
                .order_by(InternalReportVersion.number)
            )
        ).all()
        jobs = (
            await session.scalars(
                select(InternalReportJob)
                .where(InternalReportJob.report_id == report.id)
                .order_by(InternalReportJob.created_at.desc())
            )
        ).all()
        result = [
            {
                "id": str(v.id),
                "number": v.number,
                "revision": v.revision,
                "sealed": v.sealed_at is not None,
                **decrypt(report.business_id, str(v.id), v.ciphertext),
            }
            for v in versions
        ]
        return {
            "id": str(report.id),
            "business_id": str(report.business_id),
            "assistant_id": str(report.assistant_id),
            "can_edit": report.author_id == user.id,
            "state": report.state,
            "current_version_id": str(report.current_version_id),
            "versions": result,
            "jobs": [
                {
                    "id": str(j.id),
                    "version_id": str(j.version_id),
                    "status": j.status,
                    "error_code": j.error_code,
                    "result": decrypt(report.business_id, str(j.id), j.ciphertext)
                    if j.ciphertext
                    else None,
                }
                for j in jobs
            ],
        }


async def list_reports(user, business_id, offset=0, limit=20):
    async with SessionLocal() as session:
        grant = await grant_for(session, user, business_id)
        projects = [uuid.UUID(v) for v in grant.assistant_ids]
        statement = select(InternalReport).where(
            InternalReport.business_id == business_id,
            InternalReport.assistant_id.in_(projects),
            InternalReport.state != "deleted",
            InternalReport.expires_at > now(),
        )
        if grant.role != "manager":
            statement = statement.where(InternalReport.author_id == user.id)
        # Tombstoned rows restored from old backups are never exposed.
        rows = (
            await session.scalars(
                statement.order_by(InternalReport.created_at.desc(), InternalReport.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        items = []
        for report in rows:
            if deletions.contains(report.id):
                continue
            version = await session.get(
                InternalReportVersion, report.current_version_id
            )
            job = await session.scalar(
                select(InternalReportJob)
                .where(InternalReportJob.version_id == version.id)
                .order_by(InternalReportJob.created_at.desc())
                .limit(1)
            )
            value = decrypt(business_id, str(version.id), version.ciphertext)
            items.append(
                {
                    "id": str(report.id),
                    "title": value["title"],
                    "tags": value.get("tags", []),
                    "created_at": report.created_at.isoformat(),
                    "state": job.status if job else report.state,
                    "version": version.number,
                }
            )
        return {
            "items": items,
            "next_offset": offset + limit if len(rows) == limit else None,
        }


async def revise(user, report_id):
    async with SessionLocal() as session:
        report = await accessible(session, user, report_id, lock=True)
        if report.author_id != user.id:
            raise HTTPException(403, "report_author_required")
        old = await session.get(InternalReportVersion, report.current_version_id)
        if not old.sealed_at:
            raise HTTPException(409, "report_revision_conflict")
        if old.number >= 20:
            raise HTTPException(409, "report_version_limit")
        if await session.scalar(
            select(InternalReportJob.id).where(
                InternalReportJob.report_id == report.id,
                InternalReportJob.status.in_(["queued", "running"]),
            )
        ):
            raise HTTPException(409, "report_busy")
        value = decrypt(report.business_id, str(old.id), old.ciphertext)
        version = InternalReportVersion(
            id=uuid.uuid4(),
            report_id=report.id,
            parent_id=old.id,
            number=old.number + 1,
            revision=1,
            content_hash=old.content_hash,
            classification=old.classification,
        )
        version.ciphertext = encrypt(report.business_id, str(version.id), value)
        session.add(version)
        report.current_version_id, report.state = version.id, "draft"
        audit(session, user, report, "revision.created")
        await session.commit()
        return {"id": str(report.id), "revision": 1}


async def remove(user, report_id):
    async with SessionLocal() as session:
        report = await accessible(session, user, report_id, lock=True)
        # Persist the external tombstone first: a DB failure is fail-closed.
        deletions.record(report.id)
        if not await session.get(ReportDeletion, report.id):
            session.add(ReportDeletion(report_id=report.id))
        await session.execute(
            update(InternalReportJob)
            .where(InternalReportJob.report_id == report.id)
            .values(
                input_snapshot="", ciphertext="", status="cancelled", finished_at=now()
            )
        )
        await session.execute(
            delete(InternalReportVersion).where(
                InternalReportVersion.report_id == report.id
            )
        )
        report.state, report.deleted_at = "deleted", now()
        audit(session, user, report, "report.deleted")
        await session.commit()
    return {"status": "deleted"}


async def submit(user, report_id, payload):
    async with SessionLocal() as session:
        report = await accessible(session, user, report_id, lock=True)
        if report.author_id != user.id:
            raise HTTPException(403, "report_author_required")
        old_job = await session.scalar(
            select(InternalReportJob).where(
                InternalReportJob.user_id == user.id,
                InternalReportJob.idempotency_key == str(payload.idempotency_key),
            )
        )
        if old_job:
            if old_job.report_id != report.id:
                raise HTTPException(409, "report_idempotency_conflict")
            return {"job_id": str(old_job.id), "status": old_job.status}
        version = await session.get(InternalReportVersion, report.current_version_id)
        if version.sealed_at or version.revision != payload.revision:
            raise HTTPException(409, "report_revision_conflict")
        business = await session.get(ReportBusiness, report.business_id)
        settings = await allow_analysis(
            session, user, business, report.assistant_id, version.classification
        )
        # Serializes business quotas even when many users submit simultaneously.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "private-report:" + str(business.id)},
        )
        local_now = now().astimezone(ZoneInfo(settings.timezone))
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
            timezone.utc
        )
        count, spent = (
            await session.execute(
                select(
                    func.count(InternalReportJob.id),
                    func.coalesce(
                        func.sum(
                            func.coalesce(
                                InternalReportJob.actual_usd,
                                InternalReportJob.reserved_usd,
                            )
                        ),
                        0,
                    ),
                ).where(
                    InternalReportJob.business_id == business.id,
                    InternalReportJob.created_at >= start,
                )
            )
        ).one()
        if count >= min(
            business.policy.get("daily_cap", 10), settings.report_daily_submission_cap
        ):
            raise HTTPException(429, "report_daily_cap")
        value = decrypt(report.business_id, str(version.id), version.ciphertext)
        if len(value["text"]) > settings.analysis_max_input_chars:
            raise HTTPException(422, "report_text_too_long")
        topics = (
            await session.scalars(
                select(Topic)
                .where(
                    Topic.assistant_id == report.assistant_id, Topic.enabled.is_(True)
                )
                .order_by(Topic.topic_key)
            )
        ).all()
        if not topics or len(topics) > 30:
            raise HTTPException(409, "report_topics_required")
        profile = await business_profile(
            session, business, report.assistant_id, settings
        )
        workspace = await session.get(AssistantWorkspace, report.assistant_id)
        snapshot = {
            "value": value,
            "model": settings.analysis_model,
            "business": profile.semantic_payload(),
            "mission": workspace.description,
            "context_hash": profile.research_brief["semantic_hash"],
            "brief": profile.research_brief,
            "topics": [
                {
                    "topic_key": t.topic_key,
                    "name": t.name,
                    "definition": t.definition,
                    "positive_terms": list(t.positive_terms),
                    "negative_terms": list(t.negative_terms),
                    "threshold": t.threshold,
                }
                for t in topics
            ],
        }
        from app.ai_models import NEW_MODEL_TOKEN_PRICES

        rates = NEW_MODEL_TOKEN_PRICES.get(
            settings.analysis_model,
            (
                settings.model_input_usd_per_million_tokens,
                settings.model_output_usd_per_million_tokens,
            ),
        )
        # UTF-8 bytes bound token count conservatively; reserve for scoring +
        # analysis and a bounded language repair, not just the last API call.
        input_bound = len(json.dumps(snapshot, ensure_ascii=False).encode()) * 4 + 16000
        reserved = Decimal(str((input_bound * rates[0] + 26000 * rates[1]) / 1_000_000))
        budget = Decimal(
            str(
                min(
                    business.policy.get("daily_budget_usd", 1),
                    settings.report_daily_budget_usd,
                )
            )
        )
        if Decimal(spent) + reserved > budget:
            raise HTTPException(429, "report_budget_exhausted")
        job = InternalReportJob(
            id=uuid.uuid4(),
            report_id=report.id,
            version_id=version.id,
            business_id=business.id,
            user_id=user.id,
            idempotency_key=str(payload.idempotency_key),
            policy_generation=business.generation,
            reserved_usd=reserved,
            input_snapshot="",
        )
        job.input_snapshot = encrypt(business.id, str(job.id) + ":input", snapshot)
        session.add(job)
        version.sealed_at, report.state = now(), "submitted"
        report.expires_at = report.created_at + timedelta(
            days=min(
                business.policy.get("retention_days", 90),
                settings.report_retention_days,
            )
        )
        audit(session, user, report, "report.submitted")
        await session.commit()
        return {"job_id": str(job.id), "status": "queued"}


async def execute_job(job_id, *, transport=None):
    from .provider import PrivateClient
    from app.ai_relevance import (
        assessment_metadata,
        classify_articles,
        relevance_decision,
    )

    client = None
    try:
        async with SessionLocal() as session:
            job = await session.get(InternalReportJob, job_id)
            user = await session.get(AdminUser, job.user_id)
            report = await accessible(session, user, job.report_id)
            version = await session.get(InternalReportVersion, job.version_id)
            business = await session.get(ReportBusiness, job.business_id)
            settings = await allow_analysis(
                session, user, business, report.assistant_id, version.classification
            )
            if job.policy_generation != business.generation:
                raise HTTPException(409, "report_policy_changed")
            snapshot = decrypt(business.id, str(job.id) + ":input", job.input_snapshot)
            if snapshot["model"] != settings.analysis_model:
                raise HTTPException(409, "report_policy_changed")

        async def check():
            async with SessionLocal() as session:
                current_job = await session.get(InternalReportJob, job_id)
                current_user = await session.get(AdminUser, user.id)
                if not current_user or not current_user.active:
                    raise HTTPException(409, "report_access_revoked")
                await accessible(session, current_user, report.id)
                current_business = await session.get(ReportBusiness, business.id)
                active_settings = await allow_analysis(
                    session,
                    current_user,
                    current_business,
                    report.assistant_id,
                    version.classification,
                )
                if active_settings.analysis_model != snapshot["model"]:
                    raise HTTPException(409, "report_policy_changed")
                if (
                    current_job.status != "running"
                    or current_business.generation != job.policy_generation
                ):
                    raise HTTPException(409, "report_policy_changed")
                current_profile = await business_profile(
                    session, current_business, report.assistant_id, settings
                )
                if (
                    current_profile.research_brief["semantic_hash"]
                    != snapshot["context_hash"]
                ):
                    raise HTTPException(409, "report_business_changed")

        client = PrivateClient(settings, transport=transport, guard=check)
        value = snapshot["value"]
        topic_inputs = [
            {k: v for k, v in t.items() if k != "threshold"} for t in snapshot["topics"]
        ]
        scores = await classify_articles(
            client,
            articles=[
                {
                    "id": str(version.id),
                    "title": value["title"],
                    "text": value["text"],
                    "incomplete": False,
                }
            ],
            topics=topic_inputs,
            business=snapshot["business"],
            mission=snapshot["mission"],
            max_input_chars=len(value["text"]),
        )
        rows = []
        for topic in snapshot["topics"]:
            score, raw_meta = scores[(str(version.id), topic["topic_key"])]
            rows.append(
                {
                    **assessment_metadata(raw_meta),
                    "valid": True,
                    "topic_key": topic["topic_key"],
                    "score": score,
                    "threshold": topic["threshold"],
                }
            )
        decision = relevance_decision(rows, topic_count=len(rows))
        decision["publishable"] = False
        decision["can_approve"] = False
        from app.business_context import assess_business

        business_scores = (
            await assess_business(
                client,
                articles=[
                    {
                        "id": str(version.id),
                        "title": value["title"],
                        "text": value["text"],
                        "incomplete": False,
                    }
                ],
                brief=snapshot["brief"],
                language=value["language"],
            )
            if snapshot["brief"]["claims"]
            else {
                str(version.id): {
                    "score": None,
                    "relation": "unknown",
                    "reason": "",
                    "article_evidence": [],
                    "business_evidence": [],
                    "context_available": False,
                }
            }
        )
        analysis = await client.analyze(
            article_title=value["title"],
            article_text=value["text"],
            source_name="Private company assertion; not independently verified",
            source_url="",
            published_at=value["event_date"] or None,
            business_profile=snapshot["business"],
            topics=topic_inputs,
            incomplete_text=False,
            output_language=value["language"],
            origin="internal",
        )
        if not snapshot["brief"]["claims"]:
            analysis.payload["business_connection"] = ""
        await check()
        result = {
            "analysis": analysis.payload,
            "relevance": decision,
            "topic_scores": rows,
            "business_assessment": business_scores[str(version.id)],
            "origin": "company_assertion",
            "independently_verified": False,
            "public_publishable": False,
            "version_id": str(version.id),
            "content_hash": version.content_hash,
            "model": settings.analysis_model,
            "context_hash": snapshot["context_hash"],
        }
        async with SessionLocal() as session:
            live = await session.scalar(
                select(InternalReportJob)
                .where(InternalReportJob.id == job_id)
                .with_for_update()
            )
            if live.status == "running" and not deletions.contains(report.id):
                live.ciphertext = encrypt(business.id, str(job_id), result)
                live.input_snapshot = ""
                live.status, live.finished_at = "succeeded", now()
                live.actual_usd = client.cost if client.usage_complete else None
                await session.commit()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        code = (
            exc.detail
            if isinstance(exc, HTTPException) and str(exc.detail).startswith("report_")
            else "report_analysis_failed"
        )
        async with SessionLocal() as session:
            live = await session.get(InternalReportJob, job_id)
            if live and live.status == "running":
                live.status, live.error_code, live.finished_at, live.input_snapshot = (
                    "failed",
                    str(code),
                    now(),
                    "",
                )
                live.actual_usd = (
                    client.cost
                    if client and client.usage_complete and client.calls > 0
                    else None
                )
                await session.commit()


async def _worker_loop(stop):
    settings = get_settings()
    while not stop.is_set():
        job_id = None
        async with SessionLocal() as session:
            cutoff = now() - timedelta(seconds=settings.report_job_timeout_seconds + 30)
            await session.execute(
                update(InternalReportJob)
                .where(
                    InternalReportJob.status == "running",
                    InternalReportJob.started_at < cutoff,
                )
                .values(
                    status="failed",
                    error_code="report_worker_interrupted",
                    finished_at=now(),
                    input_snapshot="",
                )
            )
            busy = select(InternalReportJob.business_id).where(
                InternalReportJob.status == "running"
            )
            job = await session.scalar(
                select(InternalReportJob)
                .where(
                    InternalReportJob.status == "queued",
                    InternalReportJob.business_id.not_in(busy),
                )
                .order_by(InternalReportJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": "private-report:" + str(job.business_id)},
                )
                running = await session.scalar(
                    select(InternalReportJob.id).where(
                        InternalReportJob.business_id == job.business_id,
                        InternalReportJob.status == "running",
                    )
                )
                if not running:
                    job.status, job.started_at, job.heartbeat_at = (
                        "running",
                        now(),
                        now(),
                    )
                    job_id = job.id
            await session.commit()
        if job_id:
            try:
                await asyncio.wait_for(
                    execute_job(job_id), timeout=settings.report_job_timeout_seconds
                )
            except TimeoutError:
                async with SessionLocal() as session:
                    await session.execute(
                        update(InternalReportJob)
                        .where(
                            InternalReportJob.id == job_id,
                            InternalReportJob.status == "running",
                        )
                        .values(
                            status="failed",
                            error_code="report_analysis_timeout",
                            input_snapshot="",
                            finished_at=now(),
                        )
                    )
                    await session.commit()
        else:
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass


async def _maintenance_loop(stop):
    while not stop.is_set():
        async with SessionLocal() as session:
            expired = (
                await session.scalars(
                    select(InternalReport)
                    .where(
                        InternalReport.expires_at <= now(),
                        InternalReport.state != "deleted",
                    )
                    .limit(50)
                )
            ).all()
            for report in expired:
                deletions.record(report.id)
                if not await session.get(ReportDeletion, report.id):
                    session.add(ReportDeletion(report_id=report.id))
                await session.execute(
                    update(InternalReportJob)
                    .where(InternalReportJob.report_id == report.id)
                    .values(
                        input_snapshot="",
                        ciphertext="",
                        status="cancelled",
                        finished_at=now(),
                    )
                )
                await session.execute(
                    delete(InternalReportVersion).where(
                        InternalReportVersion.report_id == report.id
                    )
                )
                report.state, report.deleted_at = "deleted", now()
            await session.commit()
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass


async def _resilient_loop(loop, stop):
    """A temporary database/storage outage must not kill the background task.

    No exception text or SQL parameters enter logs, and interrupted paid jobs
    are recovered as failed by the next worker tick, never silently retried.
    """
    import logging

    while not stop.is_set():
        try:
            await loop(stop)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).warning("private_report_worker_unavailable")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass


async def worker(stop):
    await _resilient_loop(_worker_loop, stop)


async def maintenance(stop):
    await _resilient_loop(_maintenance_loop, stop)
