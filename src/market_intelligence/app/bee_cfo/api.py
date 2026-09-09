from __future__ import annotations

import uuid
from datetime import datetime
from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field

from app.admin import _require_assistant_access, current_admin
from app.config import get_settings

from .discovery import candidate_source_key, discover_from_homepages
from .benchmarking import benchmark_playbook
from .service import (
    approve_canary,
    canary_status,
    claim_lifecycle_for_report,
    deliver_report,
    evidence_pack_for_report,
    evidence_quality_for_report,
    evaluate_attention_candidate,
    evaluate_forecast,
    evaluate_media_forecast_result,
    evaluate_media_forecast_item,
    evaluate_price_forecast_result,
    get_profile,
    get_attention_policy,
    get_privacy_boundary,
    infrastructure_audit,
    capacity_status,
    list_open_checks,
    list_reports,
    list_alert_rules,
    list_coverage,
    list_events,
    list_sources,
    list_watches,
    market_pack_readiness,
    pilot_status,
    record_pilot_run,
    run_verified_pilot,
    suppress_pilot_run,
    record_source_decision,
    record_source_revalidation,
    readiness,
    register_source,
    register_watch,
    run_report,
    report_diff,
    prepare_canary,
    replay_reports,
    record_shadow_run,
    set_source_status,
    shadow_run_status,
    sync_configuration,
    source_ledger,
    media_scorecards,
    list_media_forecasts,
    get_media_weights,
    update_media_weights,
    upsert_alert_rule,
    update_attention_policy,
    update_privacy_boundary,
    update_profile,
    telegram_uat,
    why_changed,
)
from .indicators import (
    IndicatorSelectionRequired,
    PriceUnavailable,
    get_indicator_selection,
    indicator_catalog_readiness,
    list_indicator_catalog,
    probe_indicator_sources,
    set_indicator_selection,
)


router = APIRouter(prefix="/bee-cfo", tags=["bee-cfo"])
COOKIE = "research_bee_admin_session"


class ProfileUpdateRequest(BaseModel):
    status: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)
    schedule_slots: list[dict[str, object]] | None = None
    selected_market_ids: list[str] | None = None
    output_contract: dict[str, object] | None = None
    source_policy: dict[str, object] | None = None
    analysis_windows: dict[str, object] | None = None
    revision: str | None = Field(default=None, max_length=64)


class IndicatorSelectionRequest(BaseModel):
    market_key: str = Field(min_length=1, max_length=64)
    indicator_key: str = Field(min_length=1, max_length=64)
    status: str = Field(default="active", max_length=16)
    revision: str = Field(default="bee-cfo-indicator-1", max_length=64)


class IndicatorProbeRequest(BaseModel):
    indicator_key: str | None = Field(default=None, max_length=64)


class SourceRequest(BaseModel):
    source_key: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=200)
    homepage_url: str = Field(min_length=8, max_length=2048)
    fetch_url: str = Field(min_length=8, max_length=2048)
    adapter: str = "rss"
    origin: str = "user"
    discovery_path: str = "user_provided"
    authority: str = "unknown"
    status: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    freshness_hours: int = Field(default=72, ge=1, le=720)
    language: str = "fa"
    region: str = "global"
    metadata_json: dict[str, object] = Field(default_factory=dict)


class WatchRequest(BaseModel):
    watch_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    market: str = Field(min_length=1, max_length=80)
    asset_class: str = Field(min_length=1, max_length=80)
    region: str = "global"
    currency: str | None = None
    description: str = ""
    indicator_keys: list[str] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)
    status: str = "draft"


class ReportRunRequest(BaseModel):
    watch_id: uuid.UUID
    report_kind: str = "on_demand"
    force: bool = False


class ForecastEvaluationRequest(BaseModel):
    actual_scenario_key: str | None = Field(default=None, max_length=32)
    actual_state: dict[str, object] = Field(default_factory=dict)
    lesson: str = Field(default="", max_length=4000)


class PriceForecastEvaluationRequest(BaseModel):
    actual_value: float = Field(gt=0)
    actual_state: dict[str, object] = Field(default_factory=dict)
    lesson: str = Field(default="", max_length=4000)


class AlertRuleRequest(BaseModel):
    watch_id: uuid.UUID
    rule_key: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=40)
    threshold: float | None = None
    config: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="draft", max_length=16)
    revision: str = Field(default="bee-cfo-alerts-1", max_length=64)


class MediaForecastEvaluationRequest(BaseModel):
    source_key: str = Field(min_length=1, max_length=64)
    horizon_days: int = Field(ge=1, le=365)
    actual_direction: str | None = Field(default=None, max_length=16)


class MediaForecastItemEvaluationRequest(BaseModel):
    actual_direction: str | None = Field(default=None, max_length=16)


class MediaWeightingRequest(BaseModel):
    component_weights: dict[str, float] = Field(default_factory=dict)
    source_priors: dict[str, float] = Field(default_factory=dict)
    analyst_priors: dict[str, float] = Field(default_factory=dict)
    minimum_independent_sources: int = Field(default=1, ge=1, le=10)
    minimum_sample: int = Field(default=20, ge=20, le=500)
    revision: str = Field(default="bee-cfo-media-weights-1", max_length=64)
    reset: bool = False


class ConfigurationSyncRequest(BaseModel):
    """Secret-free configuration payload exported from the Bee CFO Sheet."""

    timezone: str = Field(default="Asia/Tehran", max_length=64)
    schedule_slots: list[dict[str, object]] = Field(default_factory=list)
    output_contract: dict[str, object] = Field(default_factory=dict)
    source_policy: dict[str, object] = Field(default_factory=dict)
    analysis_windows: dict[str, object] = Field(default_factory=dict)
    market_key: str | None = Field(default=None, max_length=64)
    indicator_key: str | None = Field(default=None, max_length=64)
    # A Telegram destination is routing metadata, not a credential. It is
    # stored per Bee CFO workspace so a new workspace never inherits another
    # project's channel; the bot token remains deployment-secret only.
    telegram_destination: str | None = Field(default=None, max_length=32)
    sources: list[SourceRequest] = Field(default_factory=list)
    watches: list[WatchRequest] = Field(default_factory=list)
    status: str = Field(default="testing", max_length=16)
    activate_sources: bool = False
    activate_watches: bool = False
    revision: str = Field(default="bee-cfo-sheet-sync-1", max_length=64)


class PilotRunRequest(BaseModel):
    report_id: uuid.UUID
    checks: dict[str, bool] = Field(default_factory=dict)


class PilotRunSuppressionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class VerifiedPilotRunRequest(BaseModel):
    watch_id: uuid.UUID
    force: bool = False


class SourceDecisionRequest(BaseModel):
    indicator_key: str = Field(min_length=1, max_length=64)
    source_key: str = Field(min_length=1, max_length=64)
    owner: str = Field(min_length=1, max_length=160)
    permission_basis: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=8, max_length=2048)
    quote_unit: str = Field(min_length=1, max_length=80)
    timezone: str = Field(min_length=1, max_length=64)
    refresh_minutes: int = Field(default=60, ge=1, le=10080)
    fallback: str = Field(min_length=1, max_length=400)
    status: str = Field(default="draft", max_length=16)
    uat_status: str = Field(default="pending", max_length=16)
    expires_at: str | None = Field(default=None, max_length=64)
    notes: str = Field(default="", max_length=2000)
    provider_fixture: dict[str, object] | None = None
    provider_fixture_enforced: bool = False


class SourceRevalidationRequest(BaseModel):
    indicator_key: str = Field(min_length=1, max_length=64)
    source_key: str = Field(min_length=1, max_length=64)


class AttentionPolicyRequest(BaseModel):
    revision: str = Field(default="bee-cfo-attention-1", max_length=64)
    enabled: bool = True
    daily_cap: int = Field(default=3, ge=1, le=20)
    minimum_severity: str = Field(default="important", max_length=16)
    dedup_hours: int = Field(default=12, ge=1, le=168)
    expiry_hours: int = Field(default=24, ge=1, le=168)
    quiet_hours: dict[str, str] = Field(default_factory=lambda: {"start": "23:00", "end": "07:00", "timezone": "Asia/Tehran"})


class AttentionCandidateRequest(BaseModel):
    dedup_key: str = Field(min_length=1, max_length=160)
    severity: str = Field(default="important", max_length=16)
    title: str = Field(default="", max_length=300)
    evidence: list[str] = Field(default_factory=list, max_length=10)


class PrivacyBoundaryRequest(BaseModel):
    revision: str = Field(default="bee-cfo-privacy-1", max_length=64)
    phase_one_personal_data_enabled: bool = False
    phase_one_allowed_data: list[str] = Field(default_factory=lambda: ["market_data", "source_metadata", "operational_audit"])
    future_controls: list[str] = Field(default_factory=list)
    phase_two_processing_enabled: bool = False


async def _access(assistant_id: uuid.UUID, token: str | None, *, write: bool = False) -> None:
    user = await current_admin(token)
    await _require_assistant_access(assistant_id, user, write=write)


@router.get("/profile")
async def bee_cfo_profile(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias=COOKIE)) -> dict[str, object]:
    await _access(assistant_id, token)
    return await get_profile(assistant_id)


@router.put("/profile")
async def bee_cfo_update_profile(
    assistant_id: uuid.UUID,
    payload: ProfileUpdateRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await update_profile(assistant_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/readiness")
async def bee_cfo_readiness(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await readiness(assistant_id)


@router.get("/pilot")
async def bee_cfo_pilot_status(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await pilot_status(assistant_id)


@router.post("/pilot/runs")
async def bee_cfo_record_pilot_run(
    assistant_id: uuid.UUID,
    payload: PilotRunRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Persist a controlled run; this never enables scheduled delivery."""
    await _access(assistant_id, token, write=True)
    try:
        return await record_pilot_run(assistant_id, report_id=payload.report_id, checks=payload.checks)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/pilot/verified-runs")
async def bee_cfo_run_verified_pilot(
    assistant_id: uuid.UUID,
    payload: VerifiedPilotRunRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Record one full no-send pilot observation from typed runtime receipts."""
    await _access(assistant_id, token, write=True)
    try:
        return await run_verified_pilot(assistant_id, watch_id=payload.watch_id, force=payload.force)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, IndicatorSelectionRequired, PriceUnavailable) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/pilot/runs/{run_id}/suppress")
async def bee_cfo_suppress_pilot_run(
    run_id: uuid.UUID,
    assistant_id: uuid.UUID,
    payload: PilotRunSuppressionRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Correct an operator-input error while retaining its governance record."""
    await _access(assistant_id, token, write=True)
    try:
        return await suppress_pilot_run(assistant_id, run_id=run_id, reason=payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/indicators/catalog")
async def bee_cfo_indicator_catalog(
    assistant_id: uuid.UUID,
    include_disabled: bool = False,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await list_indicator_catalog(include_disabled=include_disabled)


@router.get("/indicators/selection")
async def bee_cfo_indicator_selection(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return {"assistant_id": str(assistant_id), "selection": await get_indicator_selection(assistant_id)}


@router.get("/indicators/readiness")
async def bee_cfo_indicator_readiness(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Return read-only UAT readiness for every admin-defined catalog option."""
    await _access(assistant_id, token)
    return await indicator_catalog_readiness(assistant_id)


@router.get("/market-packs")
async def bee_cfo_market_packs(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await market_pack_readiness(assistant_id)


@router.get("/source-ledger")
async def bee_cfo_source_ledger(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await source_ledger(assistant_id)


@router.post("/source-ledger/decisions")
async def bee_cfo_record_source_decision(
    assistant_id: uuid.UUID,
    payload: SourceDecisionRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await record_source_decision(assistant_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/source-ledger/revalidate")
async def bee_cfo_revalidate_source_contract(
    assistant_id: uuid.UUID,
    payload: SourceRevalidationRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Audit the configured price-source contract without activating it."""
    await _access(assistant_id, token, write=True)
    try:
        return await record_source_revalidation(assistant_id, **payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/indicators/probe")
async def bee_cfo_probe_indicator_sources(
    assistant_id: uuid.UUID,
    payload: IndicatorProbeRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Probe active direct sources; draft references can never be probed into activation."""
    await _access(assistant_id, token, write=True)
    return await probe_indicator_sources(settings=get_settings(), indicator_key=payload.indicator_key)


@router.put("/indicators/selection")
async def bee_cfo_set_indicator_selection(
    assistant_id: uuid.UUID,
    payload: IndicatorSelectionRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        selection = await set_indicator_selection(assistant_id, **payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "saved", "selection": selection}


@router.put("/configuration")
async def bee_cfo_sync_configuration(
    assistant_id: uuid.UUID,
    payload: ConfigurationSyncRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Atomically sync the non-secret Sheet contract into Bee CFO."""
    await _access(assistant_id, token, write=True)
    try:
        return await sync_configuration(assistant_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sources")
async def bee_cfo_sources(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias=COOKIE)) -> dict[str, object]:
    await _access(assistant_id, token)
    rows = await list_sources(assistant_id)
    return {"assistant_id": str(assistant_id), "count": len(rows), "sources": rows}


@router.post("/sources")
async def bee_cfo_register_source(
    assistant_id: uuid.UUID,
    payload: SourceRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await register_source(assistant_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sources/{source_id}/status")
async def bee_cfo_source_status(
    source_id: uuid.UUID,
    assistant_id: uuid.UUID,
    status: str = Query(...),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await set_source_status(assistant_id, source_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sources/discover")
async def bee_cfo_discover_sources(
    assistant_id: uuid.UUID,
    seed_source_keys: list[str] | None = None,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Discover same-domain feeds and store them as draft suggestions only."""
    await _access(assistant_id, token, write=True)
    sources = await list_sources(assistant_id)
    selected = [row for row in sources if row["status"] == "active" and (not seed_source_keys or row["source_key"] in seed_source_keys)]
    candidates = await discover_from_homepages([str(row["homepage_url"]) for row in selected], get_settings())
    saved = []
    for candidate in candidates:
        saved.append(
            await register_source(
                assistant_id,
                {
                    "source_key": candidate_source_key(candidate.fetch_url),
                    "name": candidate.name,
                    "homepage_url": candidate.homepage_url,
                    "fetch_url": candidate.fetch_url,
                    "adapter": candidate.adapter,
                    "origin": "discovered",
                    "discovery_path": candidate.discovery_path,
                    "authority": candidate.authority,
                    "status": "draft",
                    "priority": 2,
                    "freshness_hours": 72,
                },
            )
        )
    return {"status": "completed", "candidates": saved, "auto_activated": 0}


@router.get("/watches")
async def bee_cfo_watches(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias=COOKIE)) -> dict[str, object]:
    await _access(assistant_id, token)
    rows = await list_watches(assistant_id)
    return {"assistant_id": str(assistant_id), "count": len(rows), "watches": rows}


@router.post("/watches")
async def bee_cfo_register_watch(
    assistant_id: uuid.UUID,
    payload: WatchRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await register_watch(assistant_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reports/run")
async def bee_cfo_run_report(
    assistant_id: uuid.UUID,
    payload: ReportRunRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await run_report(assistant_id=assistant_id, **payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/reports")
async def bee_cfo_reports(
    assistant_id: uuid.UUID,
    watch_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    rows = await list_reports(assistant_id, watch_id=watch_id, limit=limit)
    return {"assistant_id": str(assistant_id), "count": len(rows), "reports": rows}


@router.get("/reports/replay")
async def bee_cfo_replay_reports(
    assistant_id: uuid.UUID,
    cutoff: datetime,
    watch_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Reconstruct the latest report available at a point in time."""
    await _access(assistant_id, token)
    return await replay_reports(assistant_id, cutoff=cutoff, watch_id=watch_id, limit=limit)


@router.get("/reports/{report_id}/diff")
async def bee_cfo_report_diff(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    compare_to: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    try:
        return await report_diff(assistant_id, report_id=report_id, compare_to=compare_to)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/{report_id}/evidence-pack")
async def bee_cfo_report_evidence_pack(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    try:
        return await evidence_pack_for_report(assistant_id, report_id=report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/{report_id}/quality-gate")
async def bee_cfo_report_quality_gate(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    try:
        return await evidence_quality_for_report(assistant_id, report_id=report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/{report_id}/claim-lifecycle")
async def bee_cfo_report_claim_lifecycle(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    try:
        return await claim_lifecycle_for_report(assistant_id, report_id=report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reports/{report_id}/canary")
async def bee_cfo_prepare_canary(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await prepare_canary(assistant_id, report_id=report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reports/{report_id}/canary/approve")
async def bee_cfo_approve_canary(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await approve_canary(assistant_id, report_id=report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reports/{report_id}/canary")
async def bee_cfo_canary_status(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await canary_status(assistant_id, report_id=report_id)


@router.post("/reports/{report_id}/shadow-run")
async def bee_cfo_record_shadow_run(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Record a no-send shadow run from an already persisted report."""
    await _access(assistant_id, token, write=True)
    try:
        return await record_shadow_run(assistant_id, report_id=report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/{report_id}/shadow-run")
async def bee_cfo_shadow_run_status(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await shadow_run_status(assistant_id, report_id=report_id)


@router.post("/reports/{report_id}/why-changed")
async def bee_cfo_why_changed(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Build a bounded stored-evidence explanation; no model is re-run."""
    await _access(assistant_id, token)
    try:
        return await why_changed(assistant_id, report_id=report_id, requestor="admin_api")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/{report_id}/telegram-uat")
async def bee_cfo_report_telegram_uat(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    try:
        return await telegram_uat(assistant_id, report_id=report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/checks")
async def bee_cfo_open_checks(
    assistant_id: uuid.UUID,
    watch_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await list_open_checks(assistant_id, watch_id=watch_id, limit=limit)


@router.get("/capacity")
async def bee_cfo_capacity(
    assistant_id: uuid.UUID,
    watch_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await capacity_status(assistant_id, watch_id=watch_id)


@router.post("/reports/{report_id}/deliver")
async def bee_cfo_deliver_report(
    report_id: uuid.UUID,
    assistant_id: uuid.UUID,
    repeat: bool = Query(default=False),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Run the manual Telegram pilot delivery gate for one report.

    ``repeat=true`` is an explicit owner-requested exception for replaying a
    sample message; normal delivery remains idempotent.
    """
    await _access(assistant_id, token, write=True)
    try:
        return await deliver_report(assistant_id=assistant_id, report_id=report_id, repeat=repeat)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/synonyms")
async def bee_cfo_synonyms(
    assistant_id: uuid.UUID,
    indicator_key: str | None = None,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    from .benchmarking import INDICATOR_SYNONYMS, expand_indicator_terms
    if indicator_key:
        return {"indicator_key": indicator_key.upper(), "terms": expand_indicator_terms(indicator_key)}
    return {"synonyms": {key: {language: list(values) for language, values in languages.items()} for key, languages in INDICATOR_SYNONYMS.items()}}


@router.get("/benchmarks")
async def bee_cfo_benchmarks(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return {"assistant_id": str(assistant_id), "revision": "bee-cfo-benchmark-playbook-1", "benchmarks": benchmark_playbook()}


@router.get("/alerts/rules")
async def bee_cfo_alert_rules(
    assistant_id: uuid.UUID,
    watch_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await list_alert_rules(assistant_id, watch_id=watch_id)


@router.put("/alerts/rules")
async def bee_cfo_upsert_alert_rule(
    assistant_id: uuid.UUID,
    payload: AlertRuleRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return {"status": "saved", "rule": await upsert_alert_rule(assistant_id, payload.model_dump())}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/attention-policy")
async def bee_cfo_attention_policy(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await get_attention_policy(assistant_id)


@router.put("/attention-policy")
async def bee_cfo_update_attention_policy(
    assistant_id: uuid.UUID,
    payload: AttentionPolicyRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await update_attention_policy(assistant_id, payload.model_dump())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/attention-policy/evaluate")
async def bee_cfo_evaluate_attention_policy(
    assistant_id: uuid.UUID,
    payload: AttentionCandidateRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    """Evaluate/suppress an alert candidate; delivery remains separately gated."""
    await _access(assistant_id, token, write=True)
    try:
        return await evaluate_attention_candidate(assistant_id, payload.model_dump())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/events")
async def bee_cfo_events(
    assistant_id: uuid.UUID,
    watch_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await list_events(assistant_id, watch_id=watch_id, limit=limit)


@router.get("/coverage")
async def bee_cfo_coverage(
    assistant_id: uuid.UUID,
    report_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await list_coverage(assistant_id, report_id=report_id, limit=limit)


@router.post("/media-forecasts/evaluate")
async def bee_cfo_evaluate_media_forecast(
    assistant_id: uuid.UUID,
    report_id: uuid.UUID,
    payload: MediaForecastEvaluationRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await evaluate_media_forecast_result(assistant_id=assistant_id, report_id=report_id, **payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/media-scorecards")
async def bee_cfo_media_scorecards(
    assistant_id: uuid.UUID,
    source_key: str | None = None,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await media_scorecards(assistant_id, source_key=source_key)


@router.get("/media-forecasts")
async def bee_cfo_media_forecasts(
    assistant_id: uuid.UUID,
    report_id: uuid.UUID | None = None,
    source_key: str | None = None,
    horizon_key: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await list_media_forecasts(assistant_id, report_id=report_id, source_key=source_key, horizon_key=horizon_key, limit=limit)


@router.get("/media-weights")
async def bee_cfo_media_weights(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await get_media_weights(assistant_id)


@router.put("/media-weights")
async def bee_cfo_update_media_weights(
    assistant_id: uuid.UUID,
    payload: MediaWeightingRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    return await update_media_weights(assistant_id, payload.model_dump())


@router.post("/media-forecasts/{forecast_id}/evaluate")
async def bee_cfo_evaluate_media_forecast_item(
    forecast_id: uuid.UUID,
    assistant_id: uuid.UUID,
    payload: MediaForecastItemEvaluationRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await evaluate_media_forecast_item(
            assistant_id=assistant_id,
            forecast_id=forecast_id,
            actual_direction=payload.actual_direction,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/forecasts/{forecast_id}/evaluate")
async def bee_cfo_evaluate_forecast(
    forecast_id: uuid.UUID,
    assistant_id: uuid.UUID,
    payload: ForecastEvaluationRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await evaluate_forecast(assistant_id=assistant_id, forecast_id=forecast_id, **payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/price-forecasts/{forecast_id}/evaluate")
async def bee_cfo_evaluate_price_forecast(
    forecast_id: uuid.UUID,
    assistant_id: uuid.UUID,
    payload: PriceForecastEvaluationRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await evaluate_price_forecast_result(
            assistant_id=assistant_id,
            forecast_id=forecast_id,
            **payload.model_dump(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/infrastructure-audit")
async def bee_cfo_infrastructure_audit(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await infrastructure_audit(assistant_id)


@router.get("/privacy-boundary")
async def bee_cfo_privacy_boundary(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token)
    return await get_privacy_boundary(assistant_id)


@router.put("/privacy-boundary")
async def bee_cfo_update_privacy_boundary(
    assistant_id: uuid.UUID,
    payload: PrivacyBoundaryRequest,
    token: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, object]:
    await _access(assistant_id, token, write=True)
    try:
        return await update_privacy_boundary(assistant_id, payload.model_dump())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
