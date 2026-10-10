import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select, text

from app.admin import current_admin, is_owner
from app.ai_models import SUPPORTED_ANALYSIS_MODELS
from app.config import get_settings
from app.database import SessionLocal
from app.models import AdminUser, AssistantWorkspace, Topic
from . import auth, service
from .contracts import Bind, Consent, Draft, Grant, Submit
from .models import ReportAudit, ReportBinding, ReportBusiness, ReportGrant
from .policy import bind_business, enabled, grant_for

router = APIRouter()


async def reporter(token: str | None = Cookie(default=None, alias=auth.SPEC.session)):
    return await auth.current(token)


async def owner(
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
):
    user = await current_admin(token)
    if not is_owner(user):
        raise HTTPException(403, "owner_only")
    return user


@router.post("/report/api/logout")
async def logout(
    response: Response,
    token: str | None = Cookie(default=None, alias=auth.SPEC.session),
):
    return await auth.logout(response, token)


@router.get("/report/api/me")
async def me(
    response: Response,
    user=Depends(reporter),
    token: str | None = Cookie(default=None, alias=auth.SPEC.session),
):
    if token:
        auth.cookies(response, token)
    return {"id": str(user.id), "display_name": user.display_name or user.username}


@router.get("/report/api/businesses")
async def businesses(user=Depends(reporter)):
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ReportBusiness, ReportGrant)
                .join(ReportGrant)
                .where(
                    ReportGrant.user_id == user.id,
                    ReportGrant.active.is_(True),
                    ReportBusiness.active.is_(True),
                )
            )
        ).all()
        result = []
        for business, grant in rows:
            bindings = (
                await session.execute(
                    select(ReportBinding, AssistantWorkspace)
                    .join(
                        AssistantWorkspace,
                        AssistantWorkspace.id == ReportBinding.assistant_id,
                    )
                    .where(
                        ReportBinding.business_id == business.id,
                        ReportBinding.active.is_(True),
                        AssistantWorkspace.deleted_at.is_(None),
                    )
                )
            ).all()
            topics = (
                await session.scalars(
                    select(Topic).where(
                        Topic.assistant_id.in_(
                            [
                                w.id
                                for _, w in bindings
                                if str(w.id) in grant.assistant_ids
                            ]
                        ),
                        Topic.enabled.is_(True),
                    )
                )
            ).all()
            result.append(
                {
                    "id": str(business.id),
                    "name": business.name,
                    "role": grant.role,
                    "consent": bool(business.policy.get("consented_at")),
                    "models": list(SUPPORTED_ANALYSIS_MODELS),
                    "policy": {
                        k: business.policy.get(k)
                        for k in (
                            "models",
                            "daily_cap",
                            "daily_budget_usd",
                            "retention_days",
                        )
                    },
                    "projects": [
                        {
                            "id": str(w.id),
                            "name": w.name,
                            "model": ((w.config or {}).get("runtime") or {}).get(
                                "analysis_model"
                            )
                            or get_settings().analysis_model,
                            "text_limit": min(
                                20000, get_settings().analysis_max_input_chars
                            ),
                            "tags": [t.name for t in topics if t.assistant_id == w.id],
                        }
                        for b, w in bindings
                        if str(w.id) in grant.assistant_ids
                    ],
                }
            )
        return {"items": result}


@router.put("/report/api/businesses/{business_id}/consent")
async def consent(business_id: uuid.UUID, payload: Consent, user=Depends(reporter)):
    if any(m not in SUPPORTED_ANALYSIS_MODELS for m in payload.models):
        raise HTTPException(422, "report_model_unavailable")
    async with SessionLocal() as session:
        await grant_for(session, user, business_id, manager=True)
        business = await session.scalar(
            select(ReportBusiness)
            .where(ReportBusiness.id == business_id)
            .with_for_update()
        )
        if not business:
            raise HTTPException(404, "report_not_found")
        business.policy = {
            **payload.model_dump(exclude={"confirmed"}),
            "provider": "openai",
            "consented_by": str(user.id),
            "consented_at": datetime.now(timezone.utc).isoformat(),
            "disclosure_revision": "openai-retention-20261010",
        }
        business.generation = uuid.uuid4()
        session.add(
            ReportAudit(
                user_id=user.id, business_id=business_id, action="policy.consented"
            )
        )
        await session.commit()
    return {"status": "saved"}


@router.delete("/report/api/businesses/{business_id}/consent")
async def revoke(business_id: uuid.UUID, user=Depends(reporter)):
    async with SessionLocal() as session:
        await grant_for(session, user, business_id, manager=True)
        business = await session.get(ReportBusiness, business_id)
        if not business:
            raise HTTPException(404, "report_not_found")
        business.policy, business.generation = {}, uuid.uuid4()
        session.add(
            ReportAudit(
                user_id=user.id, business_id=business_id, action="policy.revoked"
            )
        )
        await session.commit()
    return {"status": "revoked"}


@router.post("/report/api/reports")
async def create(payload: Draft, user=Depends(reporter)):
    return await service.save(user, payload)


@router.put("/report/api/reports/{report_id}")
async def save(report_id: uuid.UUID, payload: Draft, user=Depends(reporter)):
    return await service.save(user, payload, report_id)


@router.get("/report/api/reports")
async def reports(
    business_id: uuid.UUID,
    offset: int = Query(default=0, ge=0, le=10000),
    user=Depends(reporter),
):
    return await service.list_reports(user, business_id, offset)


@router.get("/report/api/reports/{report_id}")
async def detail(report_id: uuid.UUID, user=Depends(reporter)):
    return await service.detail(user, report_id)


@router.post("/report/api/reports/{report_id}/submit")
async def submit(report_id: uuid.UUID, payload: Submit, user=Depends(reporter)):
    return await service.submit(user, report_id, payload)


@router.post("/report/api/reports/{report_id}/revise")
async def revise(report_id: uuid.UUID, user=Depends(reporter)):
    return await service.revise(user, report_id)


@router.delete("/report/api/reports/{report_id}")
async def remove(report_id: uuid.UUID, user=Depends(reporter)):
    return await service.remove(user, report_id)


@router.get("/admin/api/report/access")
async def access(user=Depends(owner)):
    async with SessionLocal() as session:
        businesses = (
            await session.scalars(select(ReportBusiness).order_by(ReportBusiness.name))
        ).all()
        grants = (await session.scalars(select(ReportGrant))).all()
        bindings = (
            await session.scalars(
                select(ReportBinding).where(ReportBinding.active.is_(True))
            )
        ).all()
        workspaces = (
            await session.scalars(
                select(AssistantWorkspace).where(
                    AssistantWorkspace.deleted_at.is_(None)
                )
            )
        ).all()
        users = (
            await session.scalars(select(AdminUser).where(AdminUser.active.is_(True)))
        ).all()
        return {
            "enabled": get_settings().report_portal_enabled,
            "businesses": [
                {
                    "id": str(b.id),
                    "name": b.name,
                    "projects": [
                        str(p.assistant_id) for p in bindings if p.business_id == b.id
                    ],
                }
                for b in businesses
            ],
            "grants": [
                {
                    "business_id": str(g.business_id),
                    "user_id": str(g.user_id),
                    "role": g.role,
                    "assistant_ids": g.assistant_ids,
                    "active": g.active,
                }
                for g in grants
            ],
            "projects": [{"id": str(w.id), "name": w.name} for w in workspaces],
            "users": [
                {"id": str(u.id), "name": u.display_name or u.username} for u in users
            ],
        }


@router.post("/admin/api/report/businesses")
async def bind(payload: Bind, user=Depends(owner)):
    enabled()
    async with SessionLocal() as session:
        business = await bind_business(session, payload.assistant_id)
        session.add(
            ReportAudit(
                user_id=user.id, business_id=business.id, action="business.bound"
            )
        )
        await session.commit()
        return {"id": str(business.id), "name": business.name}


@router.put("/admin/api/report/grants")
async def grant(payload: Grant, user=Depends(owner)):
    enabled()
    async with SessionLocal() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {
                "key": "private-report-grant:"
                + str(payload.business_id)
                + ":"
                + str(payload.user_id)
            },
        )
        account = await session.get(AdminUser, payload.user_id)
        if not account or not account.active:
            raise HTTPException(404, "account_not_found")
        projects = (
            await session.scalars(
                select(ReportBinding.assistant_id).where(
                    ReportBinding.business_id == payload.business_id,
                    ReportBinding.active.is_(True),
                )
            )
        ).all()
        if not set(payload.assistant_ids).issubset(set(projects)):
            raise HTTPException(422, "report_project_unavailable")
        row = await session.scalar(
            select(ReportGrant)
            .where(
                ReportGrant.business_id == payload.business_id,
                ReportGrant.user_id == payload.user_id,
            )
            .with_for_update()
        )
        if not row:
            row = ReportGrant(business_id=payload.business_id, user_id=payload.user_id)
            session.add(row)
        row.role, row.active, row.assistant_ids, row.granted_by = (
            payload.role,
            payload.active,
            [str(p) for p in payload.assistant_ids],
            user.id,
        )
        row.updated_at = datetime.now(timezone.utc)
        session.add(
            ReportAudit(
                user_id=user.id, business_id=payload.business_id, action="grant.changed"
            )
        )
        await session.commit()
    return {"status": "saved"}
