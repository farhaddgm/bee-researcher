"""Explicit business grants. Site ownership never grants private content access."""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text

from app.config import get_settings
from app.models import (
    AdminUser,
    AssistantWorkspace,
    BusinessProfile,
    ContenterBusinessLink,
)
from .crypto import keyring
from .models import ReportBinding, ReportBusiness, ReportGrant


def enabled():
    if not get_settings().report_portal_enabled:
        raise HTTPException(503, "report_unavailable")
    keyring()


async def has_report_access(session, user):
    if not user.active or not get_settings().report_portal_enabled:
        return False
    try:
        keyring()
    except HTTPException:
        return False
    return bool(
        await session.scalar(
            select(ReportGrant.id)
            .join(ReportBusiness)
            .where(
                ReportGrant.user_id == user.id,
                ReportGrant.active.is_(True),
                ReportBusiness.active.is_(True),
            )
        )
    )


async def grant_for(session, user, business_id, assistant_id=None, *, manager=False):
    enabled()
    grant = await session.scalar(
        select(ReportGrant)
        .join(ReportBusiness)
        .where(
            ReportGrant.user_id == user.id,
            ReportGrant.business_id == business_id,
            ReportGrant.active.is_(True),
            ReportBusiness.active.is_(True),
        )
    )
    if not user.active or not grant or (manager and grant.role != "manager"):
        raise HTTPException(404, "report_not_found")
    if assistant_id is not None and str(assistant_id) not in grant.assistant_ids:
        raise HTTPException(404, "report_not_found")
    return grant


async def business_identity(session, assistant_id):
    """Stable identity only; never resolve another business using a display name."""
    workspace = await session.get(AssistantWorkspace, assistant_id)
    if not workspace or workspace.deleted_at or workspace.status == "archived":
        raise HTTPException(409, "report_project_unavailable")
    link = await session.get(ContenterBusinessLink, assistant_id)
    if link:
        from app.contenter import cache_visible, connection_status

        settings = get_settings()
        if (
            not cache_visible(link, settings)
            or not connection_status(settings)["configured"]
        ):
            raise HTTPException(409, "report_business_unavailable")
        instance = hashlib.sha256(
            str(settings.contenter_api_url).rstrip("/").encode()
        ).hexdigest()
        return (
            f"contenter:{instance}:{link.external_business_id}",
            link.business_name,
            str(link.generation),
        )
    config = workspace.config or {}
    selected = config.get("active_business_id")
    statement = select(BusinessProfile).where(
        BusinessProfile.assistant_id == assistant_id
    )
    if selected:
        statement = statement.where(BusinessProfile.id == int(selected))
    elif "active_business_id" in config:
        raise HTTPException(409, "report_business_required")
    profile = await session.scalar(statement.order_by(BusinessProfile.id))
    if not profile:
        raise HTTPException(409, "report_business_required")
    return f"local:{assistant_id}:{profile.id}", profile.business_name, str(profile.id)


async def binding_for(session, business_id, assistant_id):
    binding = await session.scalar(
        select(ReportBinding).where(
            ReportBinding.business_id == business_id,
            ReportBinding.assistant_id == assistant_id,
            ReportBinding.active.is_(True),
        )
    )
    if not binding:
        raise HTTPException(409, "report_project_unavailable")
    identity, _, generation = await business_identity(session, assistant_id)
    if identity != binding.source_ref or generation != binding.generation:
        raise HTTPException(409, "report_business_changed")
    return binding


async def bind_business(session, assistant_id):
    identity, name, generation = await business_identity(session, assistant_id)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "private-report-bind:" + identity},
    )
    business = await session.scalar(
        select(ReportBusiness).where(ReportBusiness.source_ref == identity)
    )
    if not business:
        business = ReportBusiness(
            id=uuid.uuid4(), source_ref=identity, name=name[:160], policy={}
        )
        session.add(business)
        await session.flush()
    binding = await session.scalar(
        select(ReportBinding).where(
            ReportBinding.business_id == business.id,
            ReportBinding.assistant_id == assistant_id,
        )
    )
    if not binding:
        binding = ReportBinding(
            business_id=business.id,
            assistant_id=assistant_id,
            source_ref=identity,
            generation=generation,
        )
        session.add(binding)
    else:
        binding.source_ref, binding.generation, binding.active = (
            identity,
            generation,
            True,
        )
    return business


async def allow_analysis(session, user, business, assistant_id, classification):
    await grant_for(session, user, business.id, assistant_id)
    await binding_for(session, business.id, assistant_id)
    if classification == "very_confidential":
        raise HTTPException(409, "report_confidential_blocked")
    policy = business.policy or {}
    if not policy.get("consented_at"):
        raise HTTPException(409, "report_consent_required")
    workspace = await session.get(AssistantWorkspace, assistant_id)
    settings = get_settings()
    model = ((workspace.config or {}).get("runtime") or {}).get(
        "analysis_model"
    ) or settings.analysis_model
    from app.ai_models import SUPPORTED_ANALYSIS_MODELS

    if model not in SUPPORTED_ANALYSIS_MODELS or model not in policy.get("models", []):
        raise HTTPException(409, "report_model_consent_required")
    if not settings.external_analysis_approved or not settings.openai_api_key:
        raise HTTPException(503, "report_provider_unavailable")
    return settings.model_copy(update={"analysis_model": model})
