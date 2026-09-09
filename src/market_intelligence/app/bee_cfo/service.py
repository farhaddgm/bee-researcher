from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.telegram_delivery import TelegramClient
from app.models import (
    BeeCFOAlert,
    BeeCFOAlertRule,
    BeeCFOMarketEvent,
    BeeCFOCoverageSnapshot,
    BeeCFODelivery,
    BeeCFOForecast,
    BeeCFOForecastEvaluation,
    BeeCFOFactorAttribution,
    BeeCFOInfrastructureAudit,
    BeeCFOGovernanceEvent,
    BeeCFOIndicator,
    BeeCFOIndicatorSource,
    BeeCFOMediaForecast,
    BeeCFOMediaForecastOutcome,
    BeeCFOMediaWeightingAudit,
    BeeCFOPriceDelivery,
    BeeCFOPriceForecast,
    BeeCFOPriceForecastEvaluation,
    BeeCFOPriceSnapshot,
    BeeCFOMediaForecastEvaluation,
    BeeCFOProfile,
    BeeCFOReport,
    BeeCFOSnapshot,
    BeeCFOSource,
    BeeCFOWatch,
    AssistantWorkspace,
)
from app.pipeline_service import settings_for_assistant

from .analysis import generate_market_report
from .benchmarking import (
    benchmark_playbook,
    build_evidence_cards,
    build_media_pulse,
    compute_coverage_score,
    compute_novelty_metrics,
    default_alert_rules,
    evaluate_alert_rule,
    evaluate_media_outcome,
    expand_indicator_terms,
    extract_event_ledger,
    model_agreement,
    relative_benchmark_contract,
    source_scorecard,
)
from .operations import (
    build_capacity_budget,
    build_coverage_gaps,
    build_confidence_budget,
    deduplicate_open_checks,
    build_open_checks,
    build_price_source_health,
    build_report_diff,
    build_replay_payload,
    assess_evidence_quality,
    assess_delivery_readiness,
    classify_alert_maturity,
    evaluate_telegram_uat,
)
from .governance import (
    DEFAULT_ATTENTION_POLICY,
    MARKET_PACKS,
    PHASE_TWO_PRIVACY_BOUNDARY,
    assess_pilot_run,
    build_verified_pilot_checks,
    evaluate_attention_budget,
    normalize_attention_policy,
    normalize_privacy_boundary,
    pilot_observation_eligibility,
    summarize_pilot_runs,
    validate_source_decision,
)
from .audit import run_infrastructure_audit
from .factors import build_factor_attributions
from .forecasting import build_price_forecasts, evaluate_price_forecast
from .evidence import build_evidence_pack, verify_evidence_pack
from .claim_lifecycle import build_claim_lifecycle
from .canary import build_canary_preview
from .shadow import build_shadow_run
from .quote_control import evaluate_source_contract, source_contract_fingerprint
from .contracts import (
    calibration_bucket,
    detect_state_changes,
    state_fingerprint,
    validate_output_contract,
    validate_schedule_slots,
    validate_source_registration,
    validate_timezone,
    validate_watch_registration,
)
from .researcher_adapter import SharedResearcherAdapter, cluster_evidence
from .media_forecasts import (
    build_media_consensus,
    build_media_history,
    default_media_weighting,
    mark_media_expiry,
    normalize_media_weighting,
)
from .windows import (
    filter_evidence_by_lookback,
    normalize_analysis_windows,
    price_comparison,
)
from .delivery import (
    BEE_CFO_FOLLOWUP_MESSAGE_LIMIT,
    BEE_CFO_MEDIA_MESSAGE_LIMIT,
    BEE_CFO_REPORT_MESSAGE_LIMIT,
    BEE_CFO_PRICE_RENDERER_REVISION,
    BEE_CFO_RENDERER_REVISION,
    render_price_message,
    render_followup_messages,
    render_media_outlook_messages,
    render_report_diff_message,
    render_report_message,
    render_why_changed_message,
    validate_telegram_destination,
)
from .indicators import (
    IndicatorSelectionRequired,
    PriceUnavailable,
    capture_price_snapshot,
    get_indicator_selection,
    set_indicator_selection,
    validate_indicator_selection,
)


DEFAULT_OUTPUT_CONTRACT: dict[str, object] = {
    "sections": ["current_state", "scenarios", "changes", "sources", "uncertainties"],
    "language": "fa",
    "max_chars": 6000,
    "tone": "رسمی، شفاف و تحلیلی",
    "include_citations": True,
}
DEFAULT_SOURCE_POLICY: dict[str, object] = {
    "allow_user_sources": True,
    "allow_discovery": True,
    "discovered_requires_approval": True,
    "minimum_authority_for_primary": "specialist",
    "max_discovered_sources_per_run": 10,
    "media_weighting": default_media_weighting(),
    "analysis_windows": normalize_analysis_windows(),
    "quote_reconciliation": {"revision": "bee-cfo-quote-control-1", "max_relative_spread": 0.10, "require_verifier": False},
    "canary_policy": {"revision": "bee-cfo-canary-1", "enforced": False},
    "model_gate": {"revision": "bee-cfo-champion-challenger-1", "candidate_publication_approved": False},
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _normalized_source_policy(value: object) -> dict[str, object]:
    policy = {**DEFAULT_SOURCE_POLICY, **dict(value or {})}
    for key in ("quote_reconciliation", "canary_policy", "model_gate"):
        configured = policy.get(key)
        configured_values = dict(configured) if isinstance(configured, dict) else {}
        policy[key] = {
            **dict(DEFAULT_SOURCE_POLICY[key]),
            **configured_values,
        }
    try:
        policy["quote_reconciliation"]["max_relative_spread"] = max(
            0.0,
            min(1.0, float(policy["quote_reconciliation"].get("max_relative_spread", 0.10))),
        )
    except (TypeError, ValueError):
        policy["quote_reconciliation"]["max_relative_spread"] = 0.10
    policy["quote_reconciliation"]["require_verifier"] = bool(policy["quote_reconciliation"].get("require_verifier"))
    policy["canary_policy"]["enforced"] = bool(policy["canary_policy"].get("enforced"))
    policy["model_gate"]["candidate_publication_approved"] = bool(
        policy["model_gate"].get("candidate_publication_approved")
    )
    policy["analysis_windows"] = normalize_analysis_windows(policy.get("analysis_windows"))
    return policy


def _profile_payload(profile: BeeCFOProfile) -> dict[str, object]:
    source_policy = _normalized_source_policy(profile.source_policy)
    return {
        "id": str(profile.id),
        "assistant_id": str(profile.assistant_id),
        "phase": profile.phase,
        "status": profile.status,
        "timezone": profile.timezone,
        "schedule_slots": list(profile.schedule_slots or []),
        "selected_market_ids": list(profile.selected_market_ids or []),
        "output_contract": dict(profile.output_contract or {}),
        "source_policy": source_policy,
        "revision": profile.revision,
        "updated_at": _iso(profile.updated_at),
    }


def _source_payload(source: BeeCFOSource) -> dict[str, object]:
    return {
        "id": str(source.id),
        "assistant_id": str(source.assistant_id),
        "source_key": source.source_key,
        "name": source.name,
        "homepage_url": source.homepage_url,
        "fetch_url": source.fetch_url,
        "adapter": source.adapter,
        "origin": source.origin,
        "discovery_path": source.discovery_path,
        "authority": source.authority,
        "status": source.status,
        "priority": source.priority,
        "freshness_hours": source.freshness_hours,
        "language": source.language,
        "region": source.region,
        "last_checked_at": _iso(source.last_checked_at),
        "last_success_at": _iso(source.last_success_at),
        "last_error": source.last_error,
    }


def _watch_payload(watch: BeeCFOWatch) -> dict[str, object]:
    return {
        "id": str(watch.id),
        "assistant_id": str(watch.assistant_id),
        "watch_key": watch.watch_key,
        "name": watch.name,
        "market": watch.market,
        "asset_class": watch.asset_class,
        "region": watch.region,
        "currency": watch.currency,
        "description": watch.description,
        "indicator_keys": list(watch.indicator_keys or []),
        "source_keys": list(watch.source_keys or []),
        "status": watch.status,
        "source_revision": watch.source_revision,
    }


def _factor_payload(item: BeeCFOFactorAttribution) -> dict[str, object]:
    return {
        "id": str(item.id),
        "factor_key": item.factor_key,
        "category": item.category,
        "label": item.label,
        "direction": item.direction,
        "strength": item.strength,
        "score": item.score,
        "confidence": item.confidence,
        "evidence_count": item.evidence_count,
        "source_keys": item.source_keys,
        "evidence": item.evidence,
        "horizon": item.horizon,
        "invalidation": item.invalidation,
        "attribution_kind": item.attribution_kind,
        "model_revision": item.model_revision,
    }


def _price_forecast_payload(item: BeeCFOPriceForecast) -> dict[str, object]:
    return {
        "id": str(item.id),
        "indicator_key": item.indicator_key,
        "horizon_days": item.horizon_days,
        "forecast_for": _iso(item.forecast_for),
        "data_cutoff": _iso(item.data_cutoff),
        "baseline_value": float(item.baseline_value) if item.baseline_value is not None else None,
        "point_value": float(item.point_value) if item.point_value is not None else None,
        "lower_value": float(item.lower_value) if item.lower_value is not None else None,
        "upper_value": float(item.upper_value) if item.upper_value is not None else None,
        "probability_up": item.probability_up,
        "probability_down": item.probability_down,
        "probability_flat": item.probability_flat,
        "method": item.method,
        "model_revision": item.model_revision,
        "sample_size": item.sample_size,
        "quality_status": item.quality_status,
        "components": item.components,
        "metrics": item.metrics,
        "status": item.status,
    }


def _alert_rule_payload(item: BeeCFOAlertRule) -> dict[str, object]:
    return {
        "id": str(item.id), "watch_id": str(item.watch_id), "rule_key": item.rule_key,
        "kind": item.kind, "threshold": item.threshold, "config": item.config,
        "status": item.status, "revision": item.revision,
    }


def _event_payload(item: BeeCFOMarketEvent) -> dict[str, object]:
    return {
        "id": str(item.id), "watch_id": str(item.watch_id), "report_id": str(item.report_id) if item.report_id else None,
        "event_key": item.event_key, "event_type": item.event_type, "title": item.title,
        "expected": item.expected, "actual": item.actual, "previous": item.previous,
        "source_keys": item.source_keys, "source_urls": item.source_urls,
        "published_at": _iso(item.published_at), "novelty_score": item.novelty_score,
        "status": item.status, "metadata": item.metadata_json,
    }


def _coverage_payload(item: BeeCFOCoverageSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id), "report_id": str(item.report_id), "indicator_key": item.indicator_key,
        "score": item.score, "status": item.status, "components": item.components,
        "missing": item.missing, "created_at": _iso(item.created_at),
    }


def _media_forecast_payload(item: BeeCFOMediaForecast) -> dict[str, object]:
    return {
        "id": str(item.id),
        "forecast_id": item.forecast_id,
        "article_id": item.article_id,
        "statement_index": item.statement_index,
        "source_key": item.source_key,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "analyst_name": item.analyst_name,
        "published_at": _iso(item.published_at),
        "view": item.view,
        "snippet": item.snippet,
        "stance": item.stance,
        "horizon_key": item.horizon_key,
        "horizon_label": item.horizon_label,
        "horizon_days": item.horizon_days,
        "horizon_explicit": item.horizon_explicit,
        "confidence": item.confidence,
        "conflict_status": item.conflict_status,
        "conflict_group": item.conflict_group,
        "narrative_key": item.narrative_key,
        "independence_weight": item.independence_weight,
        "status": item.status,
        "provenance": item.provenance,
    }


def _report_payload(
    report: BeeCFOReport,
    *,
    forecasts: list[BeeCFOForecast] | None = None,
    factors: list[BeeCFOFactorAttribution] | None = None,
    price_forecasts: list[BeeCFOPriceForecast] | None = None,
    media_forecasts: list[BeeCFOMediaForecast] | None = None,
) -> dict[str, object]:
    return {
        "id": str(report.id),
        "assistant_id": str(report.assistant_id),
        "watch_id": str(report.watch_id),
        "snapshot_id": str(report.snapshot_id),
        "report_kind": report.report_kind,
        "as_of": _iso(report.as_of),
        "status": report.status,
        "current_state": report.current_state,
        "scenarios": report.scenarios,
        "changes": report.changes,
        "uncertainties": report.uncertainties,
        "citations": report.citations,
        "confidence": report.confidence,
        "model": report.model,
        "output_contract_revision": report.output_contract_revision,
        "forecasts": [
            {
                "id": str(item.id),
                "scenario_key": item.scenario_key,
                "title": item.title,
                "probability": item.probability,
                "horizon_end": _iso(item.horizon_end),
                "expected_change": item.expected_change,
                "triggers": item.triggers,
                "invalidation": item.invalidation,
                "status": item.status,
            }
            for item in forecasts or []
        ],
        "factor_attributions": [_factor_payload(item) for item in factors or []],
        "price_forecasts": [_price_forecast_payload(item) for item in price_forecasts or []],
        "media_forecasts": [_media_forecast_payload(item) for item in media_forecasts or []],
    }


async def get_or_create_profile(assistant_id: uuid.UUID) -> BeeCFOProfile:
    async with SessionLocal() as session:
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
        workspace = await session.get(AssistantWorkspace, assistant_id)
        if workspace is None:
            raise KeyError("assistant workspace not found")
        if profile is None:
            profile = BeeCFOProfile(
                assistant_id=assistant_id,
                phase="market_analyst",
                status="draft",
                timezone="Asia/Tehran",
                schedule_slots=[],
                selected_market_ids=[],
                output_contract=dict(DEFAULT_OUTPUT_CONTRACT),
                source_policy=dict(DEFAULT_SOURCE_POLICY),
            )
            session.add(profile)
            await session.commit()
            await session.refresh(profile)
        return profile


async def get_profile(assistant_id: uuid.UUID) -> dict[str, object]:
    return _profile_payload(await get_or_create_profile(assistant_id))


async def readiness(assistant_id: uuid.UUID) -> dict[str, object]:
    """Return a secret-free pilot gate for the phase-one Bee CFO runtime."""
    profile = await get_or_create_profile(assistant_id)
    async with SessionLocal() as session:
        sources = (
            await session.execute(
                select(BeeCFOSource).where(BeeCFOSource.assistant_id == assistant_id)
            )
        ).scalars().all()
        watches = (
            await session.execute(
                select(BeeCFOWatch).where(BeeCFOWatch.assistant_id == assistant_id)
            )
        ).scalars().all()
    settings = await settings_for_assistant(get_settings(), assistant_id)
    active_sources = [source for source in sources if source.status == "active"]
    active_source_keys = {source.source_key for source in active_sources}
    active_watches = [watch for watch in watches if watch.status == "active"]
    indicator_selection = await get_indicator_selection(assistant_id)
    warnings: list[str] = []
    watches_reference_active_sources = True
    for watch in active_watches:
        missing = set(watch.source_keys or []) - active_source_keys
        if not watch.source_keys or missing:
            watches_reference_active_sources = False
    delivery_readiness = assess_delivery_readiness(
        profile_status=profile.status,
        timezone_configured=bool(profile.timezone),
        has_schedule_slots=bool(profile.schedule_slots),
        selected_market_configured=bool(profile.selected_market_ids),
        indicator_selected=bool(indicator_selection and indicator_selection.get("status") == "active"),
        active_source_count=len(active_sources),
        active_watch_count=len(active_watches),
        watches_reference_active_sources=watches_reference_active_sources,
        telegram_token_configured=bool(settings.telegram_bot_token),
        telegram_destination_configured=bool(settings.telegram_channel_id),
        output_contract_valid=profile.output_contract.get("language") in {"fa", "en"},
    )
    if profile.output_contract.get("include_citations") is not True:
        warnings.append("citations are not enabled in the output contract")
    warnings.append("personal profile, holdings, goals and recommendations remain disabled in phase one")
    return {
        "status": "ready" if delivery_readiness["manual_pilot"]["ready"] else "blocked",
        "ready_for_pilot": delivery_readiness["manual_pilot"]["ready"],
        "ready_for_scheduled_delivery": delivery_readiness["scheduled_delivery"]["ready"],
        "assistant_id": str(assistant_id),
        "profile_status": profile.status,
        "counts": {
            "sources": len(sources),
            "active_sources": len(active_sources),
            "watches": len(watches),
            "active_watches": len(active_watches),
            "indicator_selection": 1 if indicator_selection and indicator_selection.get("status") == "active" else 0,
        },
        "telegram": {
            "token_configured": bool(settings.telegram_bot_token),
            "destination_configured": bool(settings.telegram_channel_id),
            "secret_location": "deployment_secret_store",
        },
        "blockers": list(delivery_readiness["manual_pilot"]["blockers"]),
        "manual_pilot": delivery_readiness["manual_pilot"],
        "scheduled_delivery": delivery_readiness["scheduled_delivery"],
        "warnings": warnings,
    }


async def update_profile(assistant_id: uuid.UUID, payload: dict[str, object]) -> dict[str, object]:
    async with SessionLocal() as session:
        workspace = await session.get(AssistantWorkspace, assistant_id)
        if workspace is None:
            raise KeyError("assistant workspace not found")
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
        if profile is None:
            profile = BeeCFOProfile(
                assistant_id=assistant_id,
                phase="market_analyst",
                status="draft",
                timezone="Asia/Tehran",
                schedule_slots=[],
                selected_market_ids=[],
                output_contract=dict(DEFAULT_OUTPUT_CONTRACT),
                source_policy=dict(DEFAULT_SOURCE_POLICY),
            )
            session.add(profile)
        if "timezone" in payload:
            profile.timezone = validate_timezone(payload["timezone"])
        if "schedule_slots" in payload:
            raw_slots = payload["schedule_slots"]
            profile.schedule_slots = validate_schedule_slots(raw_slots) if raw_slots else []
        if "selected_market_ids" in payload:
            ids = payload["selected_market_ids"]
            if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                raise ValueError("selected_market_ids must be a list of strings")
            profile.selected_market_ids = list(dict.fromkeys(ids))
        if "output_contract" in payload:
            profile.output_contract = validate_output_contract(payload["output_contract"])
        if "source_policy" in payload:
            if not isinstance(payload["source_policy"], dict):
                raise ValueError("source_policy must be an object")
            requested_policy = dict(payload["source_policy"])
            merged_policy = {**DEFAULT_SOURCE_POLICY, **dict(profile.source_policy or {}), **requested_policy}
            if "analysis_windows" in requested_policy:
                merged_policy["analysis_windows"] = normalize_analysis_windows(requested_policy["analysis_windows"])
            else:
                merged_policy["analysis_windows"] = normalize_analysis_windows(merged_policy.get("analysis_windows"))
            profile.source_policy = merged_policy
        if "analysis_windows" in payload:
            windows = normalize_analysis_windows(payload["analysis_windows"])
            policy = {**DEFAULT_SOURCE_POLICY, **dict(profile.source_policy or {})}
            policy["analysis_windows"] = windows
            profile.source_policy = policy
        if "status" in payload:
            status = str(payload["status"]).strip().lower()
            if status not in {"draft", "testing", "active", "paused"}:
                raise ValueError("profile status is invalid")
            if status == "active" and (not profile.selected_market_ids or not profile.schedule_slots):
                raise ValueError("an active Bee CFO profile must select markets and schedule slots")
            profile.status = status
        profile.revision = str(payload.get("revision") or profile.revision or "bee-cfo-1")[:64]
        workspace_config = dict(workspace.config or {})
        workspace_config["product"] = "bee_cfo"
        workspace_runtime = dict(workspace_config.get("runtime") or {})
        workspace_runtime["schedule_slots"] = list(profile.schedule_slots or [])
        workspace_runtime["bootstrap_pending"] = False
        workspace_config["runtime"] = workspace_runtime
        workspace.config = workspace_config
        await session.commit()
        await session.refresh(profile)
        return _profile_payload(profile)


async def get_media_weights(assistant_id: uuid.UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
        if profile is None:
            profile = await get_or_create_profile(assistant_id)
        policy = dict(profile.source_policy or {})
        weighting = normalize_media_weighting(policy.get("media_weighting"))
        audits = (
            await session.execute(
                select(BeeCFOMediaWeightingAudit)
                .where(BeeCFOMediaWeightingAudit.assistant_id == assistant_id)
                .order_by(BeeCFOMediaWeightingAudit.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
    return {
        "assistant_id": str(assistant_id),
        "system_weighting": default_media_weighting(),
        "weighting": weighting,
        "mode": str(policy.get("media_weighting_mode") or "system_plus_user_scenario"),
        "audit": [
            {
                "id": str(item.id),
                "mode": item.mode,
                "revision": item.revision,
                "created_at": _iso(item.created_at),
            }
            for item in audits
        ],
    }


async def update_media_weights(assistant_id: uuid.UUID, payload: dict[str, object]) -> dict[str, object]:
    reset = bool(payload.get("reset"))
    weighting = default_media_weighting() if reset else normalize_media_weighting(payload)
    mode = "reset" if reset else "user_scenario"
    revision = str(payload.get("revision") or "bee-cfo-media-weights-1")[:64]
    async with SessionLocal() as session:
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
        if profile is None:
            raise KeyError("Bee CFO profile not found")
        policy = {**DEFAULT_SOURCE_POLICY, **dict(profile.source_policy or {})}
        policy["analysis_windows"] = normalize_analysis_windows(policy.get("analysis_windows"))
        policy["media_weighting"] = weighting
        policy["media_weighting_mode"] = mode
        profile.source_policy = policy
        profile.revision = str(payload.get("revision") or profile.revision or revision)[:64]
        audit = BeeCFOMediaWeightingAudit(
            assistant_id=assistant_id,
            mode=mode,
            revision=revision,
            weighting=weighting,
        )
        session.add(audit)
        await session.commit()
        await session.refresh(audit)
    return {
        "assistant_id": str(assistant_id),
        "system_weighting": default_media_weighting(),
        "weighting": weighting,
        "mode": mode,
        "audit": {"id": str(audit.id), "revision": audit.revision, "created_at": _iso(audit.created_at)},
    }


async def list_sources(assistant_id: uuid.UUID) -> list[dict[str, object]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(BeeCFOSource).where(BeeCFOSource.assistant_id == assistant_id).order_by(BeeCFOSource.priority.desc(), BeeCFOSource.source_key)
            )
        ).scalars().all()
    return [_source_payload(row) for row in rows]


async def register_source(assistant_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, object]:
    normalized = validate_source_registration(payload)
    async with SessionLocal() as session:
        source = await session.scalar(
            select(BeeCFOSource).where(
                BeeCFOSource.assistant_id == assistant_id,
                BeeCFOSource.source_key == normalized["source_key"],
            )
        )
        if source is None:
            source = BeeCFOSource(assistant_id=assistant_id, **normalized)
            session.add(source)
        else:
            for key, value in normalized.items():
                setattr(source, key, value)
        await session.commit()
        await session.refresh(source)
    if source.status == "active":
        await SharedResearcherAdapter().sync_source(assistant_id, source)
    return _source_payload(source)


async def set_source_status(assistant_id: uuid.UUID, source_id: uuid.UUID, status: str) -> dict[str, object]:
    status = str(status).strip().lower()
    if status not in {"draft", "active", "disabled", "rejected"}:
        raise ValueError("source status is invalid")
    async with SessionLocal() as session:
        source = await session.scalar(select(BeeCFOSource).where(BeeCFOSource.id == source_id, BeeCFOSource.assistant_id == assistant_id))
        if source is None:
            raise KeyError("source not found")
        if source.origin == "discovered" and status == "active" and source.authority == "unknown":
            raise ValueError("an unknown discovered source cannot be activated")
        source.status = status
        await session.commit()
        await session.refresh(source)
    await SharedResearcherAdapter().sync_source(assistant_id, source)
    return _source_payload(source)


async def list_watches(assistant_id: uuid.UUID) -> list[dict[str, object]]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(BeeCFOWatch).where(BeeCFOWatch.assistant_id == assistant_id).order_by(BeeCFOWatch.watch_key))).scalars().all()
    return [_watch_payload(row) for row in rows]


async def register_watch(assistant_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, object]:
    normalized = validate_watch_registration(payload)
    async with SessionLocal() as session:
        source_keys = set(
            (await session.execute(select(BeeCFOSource.source_key).where(BeeCFOSource.assistant_id == assistant_id))).scalars().all()
        )
        missing = sorted(set(normalized["source_keys"]) - source_keys)
        if missing:
            raise ValueError(f"watch references unregistered source keys: {', '.join(missing)}")
        if normalized["status"] == "active":
            active_source_keys = set(
                (
                    await session.execute(
                        select(BeeCFOSource.source_key).where(
                            BeeCFOSource.assistant_id == assistant_id,
                            BeeCFOSource.status == "active",
                        )
                    )
                ).scalars().all()
            )
            if not set(normalized["source_keys"]) & active_source_keys:
                raise ValueError("an active watch must reference at least one active source")
        watch = await session.scalar(
            select(BeeCFOWatch).where(
                BeeCFOWatch.assistant_id == assistant_id,
                BeeCFOWatch.watch_key == normalized["watch_key"],
            )
        )
        if watch is None:
            watch = BeeCFOWatch(assistant_id=assistant_id, **normalized)
            session.add(watch)
        else:
            for key, value in normalized.items():
                setattr(watch, key, value)
        await session.commit()
        await session.refresh(watch)
        return _watch_payload(watch)


async def sync_configuration(assistant_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, object]:
    """Apply a secret-free Bee CFO configuration export after full validation.

    The Sheet is an authoring surface, not a credential store. This method
    validates the complete payload before writing and leaves sources/watches
    in draft unless activation is explicitly requested by the caller.
    """
    timezone_name = validate_timezone(payload.get("timezone", "Asia/Tehran"))
    schedule_slots = validate_schedule_slots(payload.get("schedule_slots", []))
    output_contract = validate_output_contract(
        payload.get("output_contract") or DEFAULT_OUTPUT_CONTRACT
    )
    source_policy = payload.get("source_policy") or DEFAULT_SOURCE_POLICY
    if not isinstance(source_policy, dict):
        raise ValueError("source_policy must be an object")
    source_policy = {**DEFAULT_SOURCE_POLICY, **source_policy}
    requested_windows = payload.get("analysis_windows") or source_policy.get("analysis_windows")
    source_policy["analysis_windows"] = normalize_analysis_windows(requested_windows)
    telegram_destination = payload.get("telegram_destination")
    if telegram_destination is not None:
        telegram_destination = validate_telegram_destination(telegram_destination)

    raw_sources = payload.get("sources", [])
    raw_watches = payload.get("watches", [])
    if not isinstance(raw_sources, list) or not isinstance(raw_watches, list):
        raise ValueError("sources and watches must be lists")

    activate_sources = bool(payload.get("activate_sources", False))
    activate_watches = bool(payload.get("activate_watches", False))
    normalized_sources: list[dict[str, object]] = []
    source_keys: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ValueError("each source must be an object")
        source_payload = dict(raw_source)
        if source_payload.get("status") is None:
            source_payload.pop("status", None)
        if activate_sources:
            source_payload["status"] = "active"
        normalized = validate_source_registration(source_payload)
        if normalized["source_key"] in source_keys:
            raise ValueError(f"duplicate source key: {normalized['source_key']}")
        source_keys.add(str(normalized["source_key"]))
        normalized_sources.append(normalized)

    normalized_watches: list[dict[str, object]] = []
    watch_keys: set[str] = set()
    for raw_watch in raw_watches:
        if not isinstance(raw_watch, dict):
            raise ValueError("each watch must be an object")
        watch_payload = dict(raw_watch)
        if activate_watches:
            watch_payload["status"] = "active"
        normalized = validate_watch_registration(watch_payload)
        if normalized["watch_key"] in watch_keys:
            raise ValueError(f"duplicate watch key: {normalized['watch_key']}")
        watch_keys.add(str(normalized["watch_key"]))
        missing = sorted(set(normalized["source_keys"]) - source_keys)
        if missing:
            raise ValueError(
                f"watch {normalized['watch_key']} references sources outside this sync: {', '.join(missing)}"
            )
        if normalized["status"] == "active":
            active_keys = {
                str(source["source_key"])
                for source in normalized_sources
                if source["status"] == "active"
            }
            if not set(normalized["source_keys"]) & active_keys:
                raise ValueError(
                    f"watch {normalized['watch_key']} must reference an active source"
                )
        normalized_watches.append(normalized)

    profile_status = str(payload.get("status", "testing")).strip().lower()
    if profile_status not in {"draft", "testing", "active", "paused"}:
        raise ValueError("profile status is invalid")
    if profile_status == "active" and (
        not schedule_slots
        or not normalized_watches
        or any(watch["status"] != "active" for watch in normalized_watches)
    ):
        raise ValueError("an active sync requires schedule slots and active watches")

    market_key = payload.get("market_key")
    indicator_key = payload.get("indicator_key")
    if bool(market_key) != bool(indicator_key):
        raise ValueError("market_key and indicator_key must be supplied together")
    selection_status = "active" if profile_status in {"testing", "active"} else "draft"
    if market_key and indicator_key:
        await validate_indicator_selection(
            assistant_id,
            market_key=str(market_key),
            indicator_key=str(indicator_key),
            status=selection_status,
        )

    async with SessionLocal() as session:
        workspace = await session.get(AssistantWorkspace, assistant_id)
        if workspace is None:
            raise KeyError("assistant workspace not found")
        profile = await session.scalar(
            select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id)
        )
        if profile is None:
            profile = BeeCFOProfile(
                assistant_id=assistant_id,
                phase="market_analyst",
                output_contract=output_contract,
                source_policy=source_policy,
            )
            session.add(profile)
        profile.status = profile_status
        profile.timezone = timezone_name
        profile.schedule_slots = schedule_slots
        profile.output_contract = output_contract
        profile.source_policy = source_policy
        profile.revision = str(payload.get("revision") or "bee-cfo-sheet-sync-1")[:64]

        source_rows: list[BeeCFOSource] = []
        for normalized in normalized_sources:
            source = await session.scalar(
                select(BeeCFOSource).where(
                    BeeCFOSource.assistant_id == assistant_id,
                    BeeCFOSource.source_key == normalized["source_key"],
                )
            )
            if source is None:
                source = BeeCFOSource(assistant_id=assistant_id, **normalized)
                session.add(source)
            else:
                for key, value in normalized.items():
                    setattr(source, key, value)
            source_rows.append(source)

        watch_rows: list[BeeCFOWatch] = []
        for normalized in normalized_watches:
            watch = await session.scalar(
                select(BeeCFOWatch).where(
                    BeeCFOWatch.assistant_id == assistant_id,
                    BeeCFOWatch.watch_key == normalized["watch_key"],
                )
            )
            if watch is None:
                watch = BeeCFOWatch(assistant_id=assistant_id, **normalized)
                session.add(watch)
            else:
                for key, value in normalized.items():
                    setattr(watch, key, value)
            watch_rows.append(watch)

        await session.flush()
        profile.selected_market_ids = [str(watch.id) for watch in watch_rows]
        workspace_config = dict(workspace.config or {})
        workspace_config["product"] = "bee_cfo"
        workspace_runtime = dict(workspace_config.get("runtime") or {})
        workspace_runtime["schedule_slots"] = list(schedule_slots)
        workspace_runtime["bootstrap_pending"] = False
        workspace_config["runtime"] = workspace_runtime
        if telegram_destination is not None:
            # Destination IDs are non-secret routing metadata. Keep them
            # isolated per workspace; never copy or persist the bot token.
            workspace_telegram = dict(workspace_config.get("telegram") or {})
            workspace_telegram["feedback_channel_id"] = telegram_destination
            workspace_config["telegram"] = workspace_telegram
        workspace.config = workspace_config
        await session.commit()
        await session.refresh(profile)
        for source in source_rows:
            await session.refresh(source)
        for watch in watch_rows:
            await session.refresh(watch)

    for source in source_rows:
        if source.status == "active":
            await SharedResearcherAdapter().sync_source(assistant_id, source)
    selection = None
    if market_key and indicator_key:
        selection = await set_indicator_selection(
            assistant_id,
            market_key=str(market_key),
            indicator_key=str(indicator_key),
            status=selection_status,
            revision=str(payload.get("revision") or "bee-cfo-indicator-1"),
        )
    return {
        "status": "applied",
        "assistant_id": str(assistant_id),
        "profile": _profile_payload(profile),
        "sources": [_source_payload(source) for source in source_rows],
        "watches": [_watch_payload(watch) for watch in watch_rows],
        "indicator_selection": selection,
        "activation": {
            "sources_requested": activate_sources,
            "watches_requested": activate_watches,
            "secrets_applied": False,
        },
    }


async def run_report(
    *,
    assistant_id: uuid.UUID,
    watch_id: uuid.UUID,
    report_kind: str = "on_demand",
    force: bool = False,
) -> dict[str, object]:
    if report_kind not in {"scheduled", "weekly", "on_demand", "change_alert"}:
        raise ValueError("report_kind is invalid")
    profile = await get_or_create_profile(assistant_id)
    async with SessionLocal() as session:
        watch = await session.scalar(select(BeeCFOWatch).where(BeeCFOWatch.id == watch_id, BeeCFOWatch.assistant_id == assistant_id))
        if watch is None:
            raise KeyError("watch not found")
        if watch.status != "active":
            raise ValueError("only active watches can produce reports")
        previous_snapshots = (
            await session.execute(
                select(BeeCFOSnapshot).where(BeeCFOSnapshot.watch_id == watch.id).order_by(BeeCFOSnapshot.as_of.desc()).limit(8)
            )
        ).scalars().all()
        previous = previous_snapshots[0] if previous_snapshots else None
        indicator_key = str((watch.indicator_keys or [""])[0])
        price_rows = []
        if indicator_key:
            price_rows = (
                await session.execute(
                    select(BeeCFOPriceSnapshot)
                    .where(
                        BeeCFOPriceSnapshot.assistant_id == assistant_id,
                        BeeCFOPriceSnapshot.indicator_key == indicator_key,
                    )
                    .order_by(BeeCFOPriceSnapshot.observed_at.asc())
                    .limit(500)
                )
            ).scalars().all()
        price_observations = [
            {
                "observed_at": row.observed_at,
                "value": row.value,
                "source_id": str(row.source_id),
                "raw_quote": row.raw_quote or {},
                "provenance": row.provenance or {},
            }
            for row in price_rows
        ]
    settings = await settings_for_assistant(get_settings(), assistant_id)
    adapter = SharedResearcherAdapter()
    collection = await adapter.collect_for_watch(
        assistant_id=assistant_id,
        watch=watch,
        settings=settings,
        force=force,
    )
    evidence = await adapter.load_evidence(assistant_id=assistant_id, watch=watch)
    as_of = datetime.now(timezone.utc).replace(microsecond=0)
    source_policy = _normalized_source_policy(profile.source_policy)
    analysis_windows = source_policy["analysis_windows"]
    analysis_evidence_rows, analysis_window = filter_evidence_by_lookback(
        evidence,
        as_of=as_of,
        hours=int(analysis_windows["media_analysis_window_hours"]),
    )
    analysis_evidence_rows = list(analysis_evidence_rows)
    evidence_clusters = cluster_evidence(analysis_evidence_rows)
    analysis_evidence = [cluster[0] for cluster in evidence_clusters]
    preflight_capacity = build_capacity_budget(
        source_count=len({item.source_key for item in analysis_evidence_rows}),
        evidence_count=len(analysis_evidence_rows),
        media_forecast_count=0,
        price_source_count=0,
        model_calls=1,
    )
    if preflight_capacity["status"] == "blocked":
        audit = await _append_governance_event(
            assistant_id,
            category="capacity",
            event_key=f"watch:{watch.id}:preflight:{as_of.isoformat()}",
            status="failed",
            payload={
                "stage": "pre_model_preflight",
                "capacity": preflight_capacity,
                "model_called": False,
                "outbound_message_sent": False,
                "scheduler_changed": False,
            },
        )
        return {
            "status": "capacity_blocked",
            "assistant_id": str(assistant_id),
            "watch_id": str(watch.id),
            "capacity": preflight_capacity,
            "audit": audit,
            "model_called": False,
        }
    watch_payload = _watch_payload(watch)
    previous_novelty = ((previous.current_state or {}).get("novelty_metrics") or {}) if previous is not None else {}
    novelty_metrics = compute_novelty_metrics(
        analysis_evidence_rows,
        evidence_clusters,
        previous_ids=set(str(item) for item in previous_novelty.get("fingerprints", []) if item),
    )
    evidence_cards = build_evidence_cards(analysis_evidence_rows, evidence_clusters)
    factor_bundle = build_factor_attributions(analysis_evidence_rows)
    price_forecast_bundle = build_price_forecasts(price_observations, as_of=as_of)
    challenger = price_forecast_bundle.get("champion_challenger")
    model_gate = source_policy["model_gate"]
    price_forecast_bundle["publication"] = {
        "revision": str(model_gate.get("revision") or "bee-cfo-champion-challenger-1")[:64],
        "candidate_publication_approved": bool(model_gate.get("candidate_publication_approved")),
        "candidate_eligible_for_owner_review": bool(isinstance(challenger, dict) and challenger.get("eligible_for_owner_review")),
        "public_target_permitted": bool(
            isinstance(challenger, dict)
            and challenger.get("eligible_for_owner_review")
            and model_gate.get("candidate_publication_approved")
        ),
    }
    generated, model, usage = await generate_market_report(
        settings=settings,
        watch=watch_payload,
        evidence=analysis_evidence,
        output_contract=dict(profile.output_contract or DEFAULT_OUTPUT_CONTRACT),
    )
    generated["current_state"]["factor_attributions"] = factor_bundle["factors"]
    generated["current_state"]["factor_summary"] = factor_bundle["top_factors"]
    generated["current_state"]["factor_quality"] = factor_bundle["quality_status"]
    generated["current_state"]["factor_limitations"] = factor_bundle["limitations"]
    generated["current_state"]["price_forecast"] = price_forecast_bundle
    generated["current_state"]["price_forecast_status"] = price_forecast_bundle["status"]
    generated["current_state"]["analysis_window"] = analysis_window
    generated["current_state"]["analysis_windows"] = analysis_windows
    generated["current_state"]["collected_evidence_count"] = len(evidence)
    generated["current_state"]["excluded_evidence_count"] = max(0, len(evidence) - len(analysis_evidence_rows))
    generated["current_state"]["analysis_evidence_count"] = len(analysis_evidence_rows)
    media_rows = generated["current_state"].get("media_perspectives") or []
    media_rows = [dict(item) for item in media_rows if isinstance(item, dict)]
    media_weighting = normalize_media_weighting((profile.source_policy or {}).get("media_weighting"))
    mark_media_expiry(
        media_rows,
        now=as_of,
        expiry_hours=media_weighting.get("expiry_hours") if isinstance(media_weighting, dict) else None,
    )
    media_consensus = build_media_consensus(media_rows, weighting=media_weighting, now=as_of)
    media_history = build_media_history(
        media_rows,
        previous_states=[
            snapshot.current_state
            for snapshot in reversed(previous_snapshots)
            if isinstance(snapshot.current_state, dict)
        ],
        now=as_of,
    )
    previous_claims = []
    if previous is not None and isinstance(previous.current_state, dict):
        old_lifecycle = previous.current_state.get("media_claim_lifecycle")
        if isinstance(old_lifecycle, dict) and isinstance(old_lifecycle.get("claims"), list):
            previous_claims = old_lifecycle["claims"]
    claim_lifecycle = build_claim_lifecycle(media_rows, previous=previous_claims)
    generated["current_state"]["media_perspectives"] = media_rows
    generated["current_state"]["media_consensus"] = media_consensus
    generated["current_state"]["media_history"] = media_history
    generated["current_state"]["media_claim_lifecycle"] = claim_lifecycle
    generated["current_state"]["media_weighting"] = media_weighting
    generated["current_state"]["media_conflicts"] = [
        item for item in media_rows if item.get("conflict_status") == "internal_conflict"
    ]
    generated["current_state"]["evidence_cards"] = evidence_cards
    generated["current_state"]["novelty_metrics"] = novelty_metrics
    generated["current_state"]["media_pulse"] = build_media_pulse(
        [item for item in media_rows if isinstance(item, dict)], novelty_metrics,
    )
    generated["current_state"]["model_agreement"] = model_agreement(price_forecast_bundle)
    generated["current_state"]["price_comparison"] = price_comparison(
        price_observations,
        as_of=as_of,
        window_hours=int(analysis_windows["price_comparison_window_hours"]),
        tolerance_hours=int(analysis_windows["price_comparison_tolerance_hours"]),
    )
    generated["current_state"]["benchmark"] = relative_benchmark_contract(indicator_key)
    generated["current_state"]["benchmark_playbook"] = benchmark_playbook()
    generated["current_state"]["synonym_terms"] = expand_indicator_terms(indicator_key)
    latest = max((item.published_at or item.discovered_at for item in analysis_evidence_rows if item.published_at or item.discovered_at), default=None)
    age_hours = ((as_of - latest).total_seconds() / 3600) if latest else 999.0
    freshness = 1.0 if age_hours <= 24 else 0.65 if age_hours <= 72 else 0.25 if analysis_evidence_rows else 0.0
    source_count = len({item.source_key for item in analysis_evidence_rows})
    usable_source_count = len({item.source_key for item in analysis_evidence})
    coverage = compute_coverage_score(
        quote=bool(price_observations),
        source_health=usable_source_count / max(1, source_count),
        freshness=freshness,
        media_opinion=any(isinstance(item, dict) and item.get("evidence_type") == "explicit_opinion" for item in media_rows),
        benchmark=False,
        forecast=price_forecast_bundle["status"] == "available",
    )
    generated["current_state"]["coverage_score"] = coverage
    latest_raw_quote = price_observations[-1].get("raw_quote") if price_observations else {}
    price_source_health = (
        latest_raw_quote.get("price_source_health")
        if isinstance(latest_raw_quote, dict) and isinstance(latest_raw_quote.get("price_source_health"), dict)
        else build_price_source_health(
            attempted_sources=[],
            selected_source=None,
            errors=["no price snapshot in this report"] if not price_observations else [],
        )
    )
    generated["current_state"]["price_source_health"] = price_source_health
    generated["current_state"]["confidence_budget"] = build_confidence_budget(
        coverage=coverage,
        model_agreement=generated["current_state"]["model_agreement"],
        media_pulse=generated["current_state"]["media_pulse"],
        forecast=price_forecast_bundle,
        source_health=price_source_health,
        evidence_count=len(analysis_evidence_rows),
        source_count=source_count,
    )
    generated["current_state"]["coverage_gaps"] = build_coverage_gaps(
        coverage,
        evidence=analysis_evidence_rows,
    )
    attempted_price_sources = (
        price_source_health.get("attempted_sources", [])
        if isinstance(price_source_health, dict)
        else []
    )
    generated["current_state"]["capacity_budget"] = build_capacity_budget(
        source_count=source_count,
        evidence_count=len(analysis_evidence_rows),
        media_forecast_count=len(media_rows),
        price_source_count=len(attempted_price_sources) if isinstance(attempted_price_sources, list) else 0,
        model_calls=1 if model != "fallback" else 0,
    )
    generated["current_state"]["price_change_percent"] = generated["current_state"]["price_comparison"].get("change_percent")
    event_rows = extract_event_ledger(analysis_evidence_rows, watch_key=watch.watch_key, as_of=as_of)
    generated["current_state"]["event_count"] = len(event_rows)
    generated["current_state"]["events"] = event_rows[:12]
    generated["current_state"]["open_checks"] = build_open_checks(
        current_state=generated["current_state"],
        report_as_of=as_of.isoformat(),
        forecasts=generated.get("scenarios") if isinstance(generated.get("scenarios"), list) else (),
        live_uat_required=True,
    )
    generated["current_state"]["alert_maturity"] = classify_alert_maturity(
        candidate={"kind": "report_state", "watch_key": watch.watch_key},
        independent_sources=usable_source_count,
        source_quality=float(price_source_health.get("score", 0) or 0) if isinstance(price_source_health, dict) else 0.0,
        stale="freshness" in coverage.get("missing", []),
    )
    changes = list(generated.get("changes") or [])
    changes.extend(detect_state_changes(previous.current_state if previous else None, generated["current_state"]))
    for cluster in evidence_clusters:
        if len(cluster) > 1 and len({item.source_key for item in cluster}) > 1:
            changes.append({
                "kind": "multi_source_event",
                "significance": "watch",
                "explanation": "چند منبع روایت‌های نزدیک از یک رویداد ارائه کرده‌اند؛ اختلاف روایت‌ها باید در بازبینی حفظ شود.",
                "evidence": [item.source_url for item in cluster],
            })
    citations = list(generated.get("citations") or [])
    generated["current_state"]["evidence_pack"] = build_evidence_pack(
        analysis_evidence_rows,
        report_as_of=as_of,
        model_revision=str(price_forecast_bundle.get("model_revision") or model),
        renderer_revision=BEE_CFO_RENDERER_REVISION,
        output_contract_revision=profile.revision,
        source_policy_revision=str(source_policy.get("revision") or profile.revision),
    )
    generated["current_state"]["evidence_quality_gate"] = assess_evidence_quality(generated["current_state"])
    fingerprint = state_fingerprint(generated["current_state"])
    provenance = [
        {
            "source_key": item.source_key,
            "source_name": item.source_name,
            "source_url": item.source_url,
            "origin": item.source_origin,
            "authority": item.source_authority,
            "discovery_path": item.discovery_path,
            "published_at": _iso(item.published_at),
        }
        for item in analysis_evidence_rows
    ]
    snapshot = BeeCFOSnapshot(
        id=uuid.uuid4(),
        assistant_id=assistant_id,
        watch_id=watch.id,
        as_of=as_of,
        current_state=generated["current_state"],
        provenance=provenance,
        data_quality=round(min(1.0, len({item.source_key for item in analysis_evidence_rows}) * 0.2 + len(analysis_evidence_rows) * 0.02), 4),
        change_fingerprint=fingerprint,
    )
    report = BeeCFOReport(
        id=uuid.uuid4(),
        assistant_id=assistant_id,
        watch_id=watch.id,
        snapshot_id=snapshot.id,
        report_kind=report_kind,
        as_of=as_of,
        status="ready",
        current_state=generated["current_state"],
        scenarios=generated["scenarios"],
        changes=changes,
        uncertainties=generated["uncertainties"],
        citations=citations,
        confidence=generated["confidence"],
        model=model,
        output_contract_revision=profile.revision,
    )
    forecast_rows: list[BeeCFOForecast] = []
    for scenario in generated["scenarios"]:
        forecast_rows.append(
            BeeCFOForecast(
                assistant_id=assistant_id,
                report_id=report.id,
                watch_id=watch.id,
                scenario_key=scenario["key"],
                title=scenario["title"],
                probability=scenario["probability"],
                horizon_end=as_of + timedelta(days=7),
                expected_change=scenario["expected_change"],
                triggers=scenario["triggers"],
                invalidation=scenario["invalidation"],
            )
        )
    media_forecast_rows = [
        BeeCFOMediaForecast(
            assistant_id=assistant_id,
            report_id=report.id,
            watch_id=watch.id,
            forecast_id=str(item.get("forecast_id") or uuid.uuid4().hex),
            article_id=str(item.get("article_id") or "unknown"),
            statement_index=int(item.get("statement_index") or 0),
            source_key=str(item.get("source_key") or "unknown"),
            source_name=str(item.get("source_name") or "رسانه"),
            source_url=str(item.get("source_url") or ""),
            analyst_name=str(item.get("analyst_name") or "") or None,
            published_at=datetime.fromisoformat(str(item["published_at"]).replace("Z", "+00:00")) if item.get("published_at") else None,
            view=str(item.get("view") or "نظر صریحی ثبت نشد"),
            snippet=str(item.get("snippet") or "") or None,
            stance=str(item.get("stance") or "unknown"),
            horizon_key=str(item.get("horizon_key") or "unspecified"),
            horizon_label=str(item.get("horizon_label") or item.get("horizon") or "بدون افق مشخص"),
            horizon_days=int(item["horizon_days"]) if item.get("horizon_days") is not None else None,
            horizon_explicit=bool(item.get("horizon_explicit")),
            confidence=float(item.get("confidence") or 0),
            conflict_status=str(item.get("conflict_status") or "clear"),
            conflict_group=str(item.get("conflict_group") or "") or None,
            narrative_key=str(item.get("narrative_key") or "") or None,
            independence_weight=float(item.get("independence_weight") or 1),
            status=str(item.get("status") or "active"),
            provenance={
                "extraction_revision": "bee-cfo-media-ledger-1",
                "source_origin": item.get("source_origin"),
                "expires_at": item.get("expires_at"),
                "temporal_status": item.get("temporal_status"),
                "claim_lifecycle": next(
                    (claim for claim in claim_lifecycle["claims"] if claim.get("forecast_id") == item.get("forecast_id")),
                    None,
                ),
            },
        )
        for item in media_rows
        if item.get("source_url")
    ]
    factor_rows = [
        BeeCFOFactorAttribution(
            assistant_id=assistant_id,
            report_id=report.id,
            snapshot_id=snapshot.id,
            watch_id=watch.id,
            factor_key=str(item["factor_key"]),
            category=str(item["category"]),
            label=str(item["label"]),
            direction=str(item["direction"]),
            strength=str(item["strength"]),
            score=item.get("score"),
            evidence_count=int(item["evidence_count"]),
            source_keys=item["source_keys"],
            evidence=item["evidence"],
            horizon=str(item["horizon"]),
            invalidation=str(item["invalidation"]),
            attribution_kind=str(item["attribution_kind"]),
            confidence=float(item["confidence"]),
            model_revision=str(factor_bundle["model_revision"]),
        )
        for item in factor_bundle["factors"]
    ]
    numeric_forecast_rows: list[BeeCFOPriceForecast] = []
    if price_forecast_bundle["status"] == "available" and indicator_key:
        for item in price_forecast_bundle["forecasts"]:
            numeric_forecast_rows.append(
                BeeCFOPriceForecast(
                    assistant_id=assistant_id,
                    report_id=report.id,
                    watch_id=watch.id,
                    indicator_key=indicator_key,
                    horizon_days=int(item["horizon_days"]),
                    forecast_for=datetime.fromisoformat(str(item["forecast_for"])),
                    data_cutoff=datetime.fromisoformat(str(item["data_cutoff"])) if item.get("data_cutoff") else None,
                    baseline_value=item["baseline_value"],
                    point_value=item["point_value"],
                    lower_value=item["lower_value"],
                    upper_value=item["upper_value"],
                    probability_up=float(item["probability_up"]),
                    probability_down=float(item["probability_down"]),
                    probability_flat=float(item["probability_flat"]),
                    method=str(item["method"]),
                    model_revision=str(item["model_revision"]),
                    sample_size=int(item["sample_size"]),
                    quality_status=str(item["quality_status"]),
                    components=item["components"],
                    metrics=item["metrics"],
                    status="open",
                )
            )
    alert: BeeCFOAlert | None = None
    if previous is not None and changes:
        alert = BeeCFOAlert(
            assistant_id=assistant_id,
            watch_id=watch.id,
            snapshot_id=snapshot.id,
            alert_key=fingerprint,
            dedup_key=f"{watch.id}:{fingerprint}",
            severity="important" if len(changes) > 2 else "watch",
            kind="state_change",
            explanation="تغییر قابل توضیح نسبت به snapshot قبلی شناسایی شد.",
            delta={"changes": changes},
        )
    async with SessionLocal() as session:
        active_rules = (
            await session.execute(
                select(BeeCFOAlertRule).where(
                    BeeCFOAlertRule.assistant_id == assistant_id,
                    BeeCFOAlertRule.watch_id == watch.id,
                    BeeCFOAlertRule.status == "active",
                )
            )
        ).scalars().all()
    rule_candidates = [
        candidate
        for rule in active_rules
        if (candidate := evaluate_alert_rule(_alert_rule_payload(rule), current=generated["current_state"], previous=previous.current_state if previous else None)) is not None
    ]
    rule_alerts = [
        BeeCFOAlert(
            assistant_id=assistant_id,
            watch_id=watch.id,
            snapshot_id=snapshot.id,
            alert_key=state_fingerprint({"rule": item["rule_key"], "fingerprint": fingerprint}),
            dedup_key=f"{watch.id}:rule:{item['rule_key']}:{fingerprint}",
            severity=str(item["severity"]),
            kind=str(item["kind"]),
            explanation=str(item["explanation"]),
            delta={
                **item["delta"],
                "maturity": classify_alert_maturity(
                    candidate=item,
                    independent_sources=usable_source_count,
                    source_quality=float(price_source_health.get("score", 0) or 0) if isinstance(price_source_health, dict) else 0.0,
                    stale="freshness" in coverage.get("missing", []),
                ),
            },
        )
        for item in rule_candidates
    ]
    generated["current_state"]["alert_candidates"] = [
        {
            **item,
            "maturity": classify_alert_maturity(
                candidate=item,
                independent_sources=usable_source_count,
                source_quality=float(price_source_health.get("score", 0) or 0) if isinstance(price_source_health, dict) else 0.0,
                stale="freshness" in coverage.get("missing", []),
            ),
        }
        for item in rule_candidates
    ]
    coverage_row = BeeCFOCoverageSnapshot(
        assistant_id=assistant_id,
        report_id=report.id,
        indicator_key=indicator_key or None,
        score=float(coverage["score"]),
        status=str(coverage["status"]),
        components=coverage["components"],
        missing=coverage["missing"],
    )
    event_model_rows = [
        BeeCFOMarketEvent(
            assistant_id=assistant_id,
            watch_id=watch.id,
            report_id=report.id,
            event_key=str(item["event_key"]),
            event_type=str(item["event_type"]),
            title=str(item["title"]),
            expected=item.get("expected"),
            actual=item.get("actual"),
            previous=item.get("previous"),
            source_keys=item["source_keys"],
            source_urls=item["source_urls"],
            published_at=datetime.fromisoformat(str(item["published_at"])) if item.get("published_at") else None,
            novelty_score=float(item.get("novelty_score", 0)),
            status=str(item.get("status", "observed")),
            metadata_json=item.get("metadata", {}),
        )
        for item in event_rows
    ]
    async with SessionLocal() as session:
        session.add(snapshot)
        # The report references the snapshot by foreign key and the models do
        # not declare an ORM relationship, so persist the parent explicitly
        # before adding the report and its forecasts.
        await session.flush()
        session.add(report)
        await session.flush()
        session.add_all(forecast_rows)
        session.add_all(media_forecast_rows)
        session.add_all(factor_rows)
        session.add_all(numeric_forecast_rows)
        session.add(coverage_row)
        for event_model in event_model_rows:
            exists = await session.scalar(
                select(BeeCFOMarketEvent.id).where(
                    BeeCFOMarketEvent.assistant_id == assistant_id,
                    BeeCFOMarketEvent.event_key == event_model.event_key,
                )
            )
            if exists is None:
                session.add(event_model)
        if alert is not None:
            session.add(alert)
        for rule_alert in rule_alerts:
            duplicate = await session.scalar(select(BeeCFOAlert.id).where(BeeCFOAlert.assistant_id == assistant_id, BeeCFOAlert.dedup_key == rule_alert.dedup_key))
            if duplicate is None:
                session.add(rule_alert)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(
                select(BeeCFOReport).where(
                    BeeCFOReport.watch_id == watch.id,
                    BeeCFOReport.as_of == as_of,
                    BeeCFOReport.report_kind == report_kind,
                )
            )
            if existing is None:
                raise
            forecasts = (await session.execute(select(BeeCFOForecast).where(BeeCFOForecast.report_id == existing.id))).scalars().all()
            media_forecasts = (await session.execute(select(BeeCFOMediaForecast).where(BeeCFOMediaForecast.report_id == existing.id).order_by(BeeCFOMediaForecast.source_key, BeeCFOMediaForecast.published_at))).scalars().all()
            factors = (await session.execute(select(BeeCFOFactorAttribution).where(BeeCFOFactorAttribution.report_id == existing.id))).scalars().all()
            price_forecasts = (await session.execute(select(BeeCFOPriceForecast).where(BeeCFOPriceForecast.report_id == existing.id))).scalars().all()
            return {"status": "duplicate", "report": _report_payload(existing, forecasts=forecasts, factors=factors, price_forecasts=price_forecasts, media_forecasts=media_forecasts), "collection": collection}
    return {
        "status": "completed",
        "report": _report_payload(report, forecasts=forecast_rows, factors=factor_rows, price_forecasts=numeric_forecast_rows, media_forecasts=media_forecast_rows),
        "collection": collection,
        "evidence_count": len(evidence),
        "source_count": len({item.source_key for item in evidence}),
        "event_cluster_count": len(evidence_clusters),
        "model_usage": usage,
        "alert_created": alert is not None,
        "factor_count": len(factor_rows),
        "price_forecast_count": len(numeric_forecast_rows),
        "price_forecast_status": price_forecast_bundle["status"],
        "coverage": coverage,
        "novelty_metrics": novelty_metrics,
        "event_count": len(event_rows),
        "rule_alert_count": len(rule_alerts),
        "media_forecast_count": len(media_forecast_rows),
        "media_conflict_count": int(media_consensus.get("conflict_count", 0)),
        "evidence_quality_gate": generated["current_state"]["evidence_quality_gate"],
    }


async def list_reports(assistant_id: uuid.UUID, *, watch_id: uuid.UUID | None = None, limit: int = 50) -> list[dict[str, object]]:
    async with SessionLocal() as session:
        query = select(BeeCFOReport).where(BeeCFOReport.assistant_id == assistant_id).order_by(BeeCFOReport.as_of.desc()).limit(limit)
        if watch_id is not None:
            query = query.where(BeeCFOReport.watch_id == watch_id)
        reports = (await session.execute(query)).scalars().all()
        result: list[dict[str, object]] = []
        for report in reports:
            forecasts = (await session.execute(select(BeeCFOForecast).where(BeeCFOForecast.report_id == report.id).order_by(BeeCFOForecast.scenario_key))).scalars().all()
            media_forecasts = (await session.execute(select(BeeCFOMediaForecast).where(BeeCFOMediaForecast.report_id == report.id).order_by(BeeCFOMediaForecast.source_key, BeeCFOMediaForecast.published_at))).scalars().all()
            factors = (await session.execute(select(BeeCFOFactorAttribution).where(BeeCFOFactorAttribution.report_id == report.id).order_by(BeeCFOFactorAttribution.score.desc().nullslast()))).scalars().all()
            price_forecasts = (await session.execute(select(BeeCFOPriceForecast).where(BeeCFOPriceForecast.report_id == report.id).order_by(BeeCFOPriceForecast.horizon_days))).scalars().all()
            result.append(_report_payload(report, forecasts=forecasts, factors=factors, price_forecasts=price_forecasts, media_forecasts=media_forecasts))
    return result


async def report_diff(
    assistant_id: uuid.UUID,
    *,
    report_id: uuid.UUID,
    compare_to: uuid.UUID | None = None,
) -> dict[str, object]:
    """Return an auditable report diff without invoking collection or a model."""

    async with SessionLocal() as session:
        current = await session.scalar(
            select(BeeCFOReport).where(
                BeeCFOReport.id == report_id,
                BeeCFOReport.assistant_id == assistant_id,
            )
        )
        if current is None:
            raise KeyError("report not found")
        if compare_to is not None:
            previous = await session.scalar(
                select(BeeCFOReport).where(
                    BeeCFOReport.id == compare_to,
                    BeeCFOReport.assistant_id == assistant_id,
                    BeeCFOReport.watch_id == current.watch_id,
                )
            )
        else:
            previous = await session.scalar(
                select(BeeCFOReport)
                .where(
                    BeeCFOReport.assistant_id == assistant_id,
                    BeeCFOReport.watch_id == current.watch_id,
                    BeeCFOReport.as_of < current.as_of,
                )
                .order_by(BeeCFOReport.as_of.desc())
            )
        current_state = current.current_state or {}
        previous_state = previous.current_state if previous is not None else None
        result = build_report_diff(previous_state, current_state)
        current_cards = current_state.get("evidence_cards") if isinstance(current_state.get("evidence_cards"), list) else []
        new_ids = set(str(item) for item in result.get("new_evidence_ids", []) if item)
        result["new_evidence"] = [
            item for item in current_cards
            if isinstance(item, dict) and str(item.get("evidence_id")) in new_ids
        ][:3]
        watch = await session.get(BeeCFOWatch, current.watch_id)
        result["telegram_message"] = render_report_diff_message(
            diff=result,
            watch_name=watch.name if watch is not None else "گزارش بازار",
        )
        return {
            "assistant_id": str(assistant_id),
            "report_id": str(current.id),
            "compare_to": str(previous.id) if previous is not None else None,
            "current_as_of": _iso(current.as_of),
            "previous_as_of": _iso(previous.as_of) if previous is not None else None,
            **result,
        }


async def replay_reports(
    assistant_id: uuid.UUID,
    *,
    cutoff: datetime,
    watch_id: uuid.UUID | None = None,
    limit: int = 200,
) -> dict[str, object]:
    reports = await list_reports(assistant_id, watch_id=watch_id, limit=limit)
    result = build_replay_payload(reports, cutoff)
    return {"assistant_id": str(assistant_id), "watch_id": str(watch_id) if watch_id else None, **result}


async def evidence_quality_for_report(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    """Return the persisted evidence gate or deterministically reconstruct it."""
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
        existing = await session.scalar(
            select(BeeCFOGovernanceEvent)
            .where(
                BeeCFOGovernanceEvent.assistant_id == assistant_id,
                BeeCFOGovernanceEvent.category == "pilot_run",
                BeeCFOGovernanceEvent.event_key == str(report_id),
                BeeCFOGovernanceEvent.status != "suppressed",
            )
            .order_by(BeeCFOGovernanceEvent.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return {"status": "already_recorded", "run": _event_payload(existing), "pilot": await pilot_status(assistant_id)}
    state = dict(report.current_state or {})
    gate = state.get("evidence_quality_gate")
    if not isinstance(gate, dict):
        gate = assess_evidence_quality(state)
    return {"assistant_id": str(assistant_id), "report_id": str(report_id), "quality_gate": gate, "model_rerun": False}


async def list_open_checks(
    assistant_id: uuid.UUID,
    *,
    watch_id: uuid.UUID | None = None,
    limit: int = 200,
) -> dict[str, object]:
    async with SessionLocal() as session:
        query = select(BeeCFOReport).where(BeeCFOReport.assistant_id == assistant_id).order_by(BeeCFOReport.as_of.desc()).limit(limit)
        if watch_id is not None:
            query = query.where(BeeCFOReport.watch_id == watch_id)
        reports = (await session.execute(query)).scalars().all()
    checks: list[dict[str, object]] = []
    for report in reports:
        state = report.current_state if isinstance(report.current_state, dict) else {}
        for item in state.get("open_checks", []) if isinstance(state.get("open_checks"), list) else []:
            if isinstance(item, dict):
                checks.append({"report_id": str(report.id), "watch_id": str(report.watch_id), "as_of": _iso(report.as_of), **item})
    checks = deduplicate_open_checks(checks, limit=limit)
    return {"assistant_id": str(assistant_id), "count": len(checks), "checks": checks}


async def capacity_status(
    assistant_id: uuid.UUID,
    *,
    watch_id: uuid.UUID | None = None,
) -> dict[str, object]:
    async with SessionLocal() as session:
        query = select(BeeCFOReport).where(BeeCFOReport.assistant_id == assistant_id).order_by(BeeCFOReport.as_of.desc())
        if watch_id is not None:
            query = query.where(BeeCFOReport.watch_id == watch_id)
        report = await session.scalar(query)
    if report is None:
        return {"assistant_id": str(assistant_id), "status": "no_report", "capacity": None}
    state = report.current_state if isinstance(report.current_state, dict) else {}
    return {
        "assistant_id": str(assistant_id),
        "watch_id": str(report.watch_id),
        "report_id": str(report.id),
        "as_of": _iso(report.as_of),
        "status": "available",
        "capacity": state.get("capacity_budget"),
    }


async def telegram_uat(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
        price = await session.scalar(
            select(BeeCFOPriceDelivery).where(
                BeeCFOPriceDelivery.assistant_id == assistant_id,
                BeeCFOPriceDelivery.report_id == report_id,
            )
        )
        delivery = await session.scalar(
            select(BeeCFODelivery).where(
                BeeCFODelivery.assistant_id == assistant_id,
                BeeCFODelivery.report_id == report_id,
            )
        )
    result = evaluate_telegram_uat(
        price_delivery={"status": price.status, "message_ids": price.message_ids or []} if price else {},
        report_delivery={
            "status": delivery.status,
            "message_ids": delivery.message_ids or [],
            "media_message_ids": delivery.media_message_ids or [],
        } if delivery else {},
    )
    return {"assistant_id": str(assistant_id), "report_id": str(report_id), **result}


async def list_alert_rules(assistant_id: uuid.UUID, *, watch_id: uuid.UUID | None = None) -> dict[str, object]:
    async with SessionLocal() as session:
        query = select(BeeCFOAlertRule).where(BeeCFOAlertRule.assistant_id == assistant_id).order_by(BeeCFOAlertRule.rule_key)
        if watch_id is not None:
            query = query.where(BeeCFOAlertRule.watch_id == watch_id)
        rows = (await session.execute(query)).scalars().all()
        return {"assistant_id": str(assistant_id), "rules": [_alert_rule_payload(item) for item in rows], "defaults": default_alert_rules()}


async def upsert_alert_rule(assistant_id: uuid.UUID, payload: dict[str, object]) -> dict[str, object]:
    watch_id = uuid.UUID(str(payload["watch_id"]))
    rule_key = str(payload.get("rule_key") or "").strip()[:64]
    kind = str(payload.get("kind") or "").strip()[:40]
    if not rule_key or not kind:
        raise ValueError("rule_key and kind are required")
    allowed = {item["kind"] for item in default_alert_rules()}
    if kind not in allowed:
        raise ValueError("unsupported Bee CFO alert rule kind")
    status = str(payload.get("status", "draft")).lower()
    if status not in {"draft", "active", "paused"}:
        raise ValueError("alert rule status is invalid")
    async with SessionLocal() as session:
        watch = await session.scalar(select(BeeCFOWatch).where(BeeCFOWatch.id == watch_id, BeeCFOWatch.assistant_id == assistant_id))
        if watch is None:
            raise KeyError("watch not found")
        row = await session.scalar(select(BeeCFOAlertRule).where(BeeCFOAlertRule.assistant_id == assistant_id, BeeCFOAlertRule.watch_id == watch_id, BeeCFOAlertRule.rule_key == rule_key))
        if row is None:
            row = BeeCFOAlertRule(assistant_id=assistant_id, watch_id=watch_id, rule_key=rule_key, kind=kind)
            session.add(row)
        row.kind = kind
        row.threshold = float(payload["threshold"]) if payload.get("threshold") is not None else None
        row.config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        row.status = status
        row.revision = str(payload.get("revision") or "bee-cfo-alerts-1")[:64]
        await session.commit()
        await session.refresh(row)
        return _alert_rule_payload(row)


async def list_events(assistant_id: uuid.UUID, *, watch_id: uuid.UUID | None = None, limit: int = 100) -> dict[str, object]:
    async with SessionLocal() as session:
        query = select(BeeCFOMarketEvent).where(BeeCFOMarketEvent.assistant_id == assistant_id).order_by(BeeCFOMarketEvent.created_at.desc()).limit(limit)
        if watch_id is not None:
            query = query.where(BeeCFOMarketEvent.watch_id == watch_id)
        rows = (await session.execute(query)).scalars().all()
        return {"assistant_id": str(assistant_id), "count": len(rows), "events": [_event_payload(item) for item in rows]}


async def list_coverage(assistant_id: uuid.UUID, *, report_id: uuid.UUID | None = None, limit: int = 100) -> dict[str, object]:
    async with SessionLocal() as session:
        query = select(BeeCFOCoverageSnapshot).where(BeeCFOCoverageSnapshot.assistant_id == assistant_id).order_by(BeeCFOCoverageSnapshot.created_at.desc()).limit(limit)
        if report_id is not None:
            query = query.where(BeeCFOCoverageSnapshot.report_id == report_id)
        rows = (await session.execute(query)).scalars().all()
        return {"assistant_id": str(assistant_id), "count": len(rows), "coverage": [_coverage_payload(item) for item in rows]}


async def evaluate_media_forecast_result(*, assistant_id: uuid.UUID, report_id: uuid.UUID, source_key: str, horizon_days: int, actual_direction: str | None) -> dict[str, object]:
    if horizon_days not in {1, 2, 7, 30, 90}:
        raise ValueError("media evaluation horizon must be 1, 2, 7, 30 or 90 days")
    async with SessionLocal() as session:
        report = await session.scalar(select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id))
        if report is None:
            raise KeyError("report not found")
        perspectives = (report.current_state or {}).get("media_perspectives") or []
        perspective = next((item for item in perspectives if isinstance(item, dict) and item.get("source_key") == source_key and int(item.get("horizon_days") or 0) == horizon_days), None)
        if perspective is None:
            raise KeyError("media forecast not found")
        existing = await session.scalar(select(BeeCFOMediaForecastEvaluation.id).where(BeeCFOMediaForecastEvaluation.report_id == report_id, BeeCFOMediaForecastEvaluation.source_key == source_key, BeeCFOMediaForecastEvaluation.horizon_days == horizon_days))
        if existing is not None:
            raise ValueError("media forecast has already been evaluated")
        result = evaluate_media_outcome(expected_stance=str(perspective.get("stance")), actual_direction=actual_direction, probability=float(perspective.get("confidence", 0.5)))
        now = datetime.now(timezone.utc)
        row = BeeCFOMediaForecastEvaluation(assistant_id=assistant_id, report_id=report_id, source_key=source_key, horizon_days=horizon_days, expected_stance=str(perspective.get("stance")), actual_direction=actual_direction, outcome=result["outcome"], direction_hit=result["direction_hit"], brier_score=result["brier_score"], evaluated_at=now, provenance={"method": "owner_supplied_actual_direction", "evaluated_at": now.isoformat()})
        session.add(row)
        await session.commit()
        return {"status": "evaluated", "report_id": str(report_id), "source_key": source_key, "horizon_days": horizon_days, **result}


async def media_scorecards(assistant_id: uuid.UUID, *, source_key: str | None = None) -> dict[str, object]:
    async with SessionLocal() as session:
        query = select(BeeCFOMediaForecastEvaluation).where(BeeCFOMediaForecastEvaluation.assistant_id == assistant_id).order_by(BeeCFOMediaForecastEvaluation.evaluated_at.desc())
        if source_key:
            query = query.where(BeeCFOMediaForecastEvaluation.source_key == source_key)
        rows = (await session.execute(query)).scalars().all()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(row.source_key, []).append({"direction_hit": row.direction_hit, "brier_score": row.brier_score, "outcome": row.outcome, "horizon_days": row.horizon_days})
    scorecards = [{"source_key": key, **source_scorecard(values)} for key, values in sorted(grouped.items())]
    async with SessionLocal() as session:
        outcome_query = select(BeeCFOMediaForecastOutcome).where(BeeCFOMediaForecastOutcome.assistant_id == assistant_id).order_by(BeeCFOMediaForecastOutcome.evaluated_at.desc())
        if source_key:
            outcome_query = outcome_query.where(BeeCFOMediaForecastOutcome.source_key == source_key)
        outcomes = (await session.execute(outcome_query)).scalars().all()
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
    media_weighting = normalize_media_weighting((profile.source_policy or {}).get("media_weighting") if profile else None)
    minimum_sample = int(media_weighting.get("minimum_sample", 20))
    scorecards = [{"source_key": key, **source_scorecard(values, minimum_sample=minimum_sample)} for key, values in sorted(grouped.items())]
    by_horizon: dict[str, list[dict[str, object]]] = {}
    by_analyst: dict[str, list[dict[str, object]]] = {}
    by_source_horizon: dict[tuple[str, str], list[dict[str, object]]] = {}
    by_source_analyst: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in outcomes:
        item = {"direction_hit": row.direction_hit, "brier_score": row.brier_score, "outcome": row.outcome, "source_key": row.source_key}
        by_horizon.setdefault(row.horizon_key, []).append(item)
        if row.analyst_name:
            by_analyst.setdefault(row.analyst_name, []).append(item)
            by_source_analyst.setdefault((row.source_key, row.analyst_name), []).append(item)
        by_source_horizon.setdefault((row.source_key, row.horizon_key), []).append(item)
    return {
        "assistant_id": str(assistant_id),
        "minimum_sample": minimum_sample,
        "weighting_revision": media_weighting.get("revision"),
        "scorecards": [
            {**item, "source_prior": (media_weighting.get("source_priors") or {}).get(item["source_key"], 1.0)}
            for item in scorecards
        ],
        "horizon_scorecards": [{"horizon_key": key, **source_scorecard(values, minimum_sample=minimum_sample)} for key, values in sorted(by_horizon.items())],
        "analyst_scorecards": [
            {"analyst_name": key, "analyst_prior": (media_weighting.get("analyst_priors") or {}).get(key, 1.0), **source_scorecard(values, minimum_sample=minimum_sample)}
            for key, values in sorted(by_analyst.items())
        ],
        "source_horizon_scorecards": [
            {"source_key": source, "horizon_key": horizon, "source_prior": (media_weighting.get("source_priors") or {}).get(source, 1.0), **source_scorecard(values, minimum_sample=minimum_sample)}
            for (source, horizon), values in sorted(by_source_horizon.items())
        ],
        "source_analyst_scorecards": [
            {"source_key": source, "analyst_name": analyst, **source_scorecard(values, minimum_sample=minimum_sample)}
            for (source, analyst), values in sorted(by_source_analyst.items())
        ],
    }


async def list_media_forecasts(
    assistant_id: uuid.UUID,
    *,
    report_id: uuid.UUID | None = None,
    source_key: str | None = None,
    horizon_key: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    async with SessionLocal() as session:
        query = select(BeeCFOMediaForecast).where(BeeCFOMediaForecast.assistant_id == assistant_id).order_by(BeeCFOMediaForecast.published_at.desc().nullslast()).limit(limit)
        if report_id is not None:
            query = query.where(BeeCFOMediaForecast.report_id == report_id)
        if source_key:
            query = query.where(BeeCFOMediaForecast.source_key == source_key)
        if horizon_key:
            query = query.where(BeeCFOMediaForecast.horizon_key == horizon_key)
        rows = (await session.execute(query)).scalars().all()
    return {"assistant_id": str(assistant_id), "count": len(rows), "forecasts": [_media_forecast_payload(row) for row in rows]}


async def evaluate_media_forecast_item(
    *,
    assistant_id: uuid.UUID,
    forecast_id: uuid.UUID,
    actual_direction: str | None,
) -> dict[str, object]:
    async with SessionLocal() as session:
        forecast = await session.scalar(select(BeeCFOMediaForecast).where(BeeCFOMediaForecast.id == forecast_id, BeeCFOMediaForecast.assistant_id == assistant_id))
        if forecast is None:
            raise KeyError("media forecast not found")
        existing = await session.scalar(select(BeeCFOMediaForecastOutcome.id).where(BeeCFOMediaForecastOutcome.forecast_id == forecast_id))
        if existing is not None:
            raise ValueError("media forecast has already been evaluated")
        result = evaluate_media_outcome(
            expected_stance=forecast.stance,
            actual_direction=actual_direction,
            probability=forecast.confidence,
        )
        now = datetime.now(timezone.utc)
        outcome = BeeCFOMediaForecastOutcome(
            assistant_id=assistant_id,
            forecast_id=forecast.id,
            report_id=forecast.report_id,
            source_key=forecast.source_key,
            analyst_name=forecast.analyst_name,
            horizon_key=forecast.horizon_key,
            horizon_days=forecast.horizon_days,
            expected_stance=forecast.stance,
            actual_direction=actual_direction,
            outcome=result["outcome"],
            direction_hit=result["direction_hit"],
            brier_score=result["brier_score"],
            evaluated_at=now,
            provenance={"method": "owner_supplied_actual_direction", "evaluated_at": now.isoformat(), "forecast_url": forecast.source_url},
        )
        session.add(outcome)
        await session.commit()
    return {"status": "evaluated", "forecast_id": str(forecast_id), "source_key": forecast.source_key, "horizon_key": forecast.horizon_key, **result}


async def evaluate_forecast(
    *,
    assistant_id: uuid.UUID,
    forecast_id: uuid.UUID,
    actual_scenario_key: str | None,
    actual_state: dict[str, object],
    lesson: str = "",
) -> dict[str, object]:
    async with SessionLocal() as session:
        forecast = await session.scalar(select(BeeCFOForecast).where(BeeCFOForecast.id == forecast_id, BeeCFOForecast.assistant_id == assistant_id))
        if forecast is None:
            raise KeyError("forecast not found")
        if await session.scalar(select(BeeCFOForecastEvaluation.id).where(BeeCFOForecastEvaluation.forecast_id == forecast_id)):
            raise ValueError("forecast has already been evaluated")
        if actual_scenario_key is None:
            outcome, error_score = "not_evaluable", None
        elif actual_scenario_key == forecast.scenario_key:
            outcome, error_score = "hit", 0.0
        else:
            outcome, error_score = "miss", 1.0
        evaluated_at = datetime.now(timezone.utc)
        evaluation = BeeCFOForecastEvaluation(
            assistant_id=assistant_id,
            forecast_id=forecast_id,
            evaluated_at=evaluated_at,
            outcome=outcome,
            actual_state=actual_state,
            error_score=error_score,
            calibration_bucket=calibration_bucket(forecast.probability),
            lesson=lesson[:4000],
            provenance=[{"method": "owner_supplied_outcome", "evaluated_at": evaluated_at.isoformat()}],
        )
        forecast.status = "evaluated"
        session.add(evaluation)
        await session.commit()
        return {
            "forecast_id": str(forecast.id),
            "outcome": outcome,
            "error_score": error_score,
            "calibration_bucket": evaluation.calibration_bucket,
            "evaluated_at": evaluated_at.isoformat(),
        }


async def evaluate_price_forecast_result(
    *,
    assistant_id: uuid.UUID,
    forecast_id: uuid.UUID,
    actual_value: float,
    actual_state: dict[str, object],
    lesson: str = "",
) -> dict[str, object]:
    """Record one realized quote and make numeric calibration measurable."""
    async with SessionLocal() as session:
        forecast = await session.scalar(
            select(BeeCFOPriceForecast).where(
                BeeCFOPriceForecast.id == forecast_id,
                BeeCFOPriceForecast.assistant_id == assistant_id,
            )
        )
        if forecast is None:
            raise KeyError("price forecast not found")
        if await session.scalar(select(BeeCFOPriceForecastEvaluation.id).where(BeeCFOPriceForecastEvaluation.forecast_id == forecast_id)):
            raise ValueError("price forecast has already been evaluated")
        metrics = evaluate_price_forecast(_price_forecast_payload(forecast), actual_value)
        evaluated_at = datetime.now(timezone.utc)
        evaluation = BeeCFOPriceForecastEvaluation(
            assistant_id=assistant_id,
            forecast_id=forecast_id,
            evaluated_at=evaluated_at,
            actual_value=metrics["actual_value"],
            absolute_error=metrics["absolute_error"],
            percentage_error=metrics["percentage_error"],
            direction_outcome=metrics["direction_outcome"],
            direction_hit=metrics["direction_hit"],
            interval_covered=metrics["interval_covered"],
            brier_score=metrics["brier_score"],
            actual_state=actual_state,
            lesson=lesson[:4000],
            provenance={"method": "owner_supplied_actual_value", "evaluated_at": evaluated_at.isoformat()},
        )
        forecast.status = "evaluated"
        session.add(evaluation)
        await session.commit()
        return {
            "forecast_id": str(forecast.id),
            "status": "evaluated",
            "evaluated_at": evaluated_at.isoformat(),
            **metrics,
        }


async def infrastructure_audit(assistant_id: uuid.UUID) -> dict[str, object]:
    result = run_infrastructure_audit()
    async with SessionLocal() as session:
        audit = await session.scalar(select(BeeCFOInfrastructureAudit).where(BeeCFOInfrastructureAudit.assistant_id == assistant_id))
        if audit is None:
            audit = BeeCFOInfrastructureAudit(assistant_id=assistant_id, status=result["status"], decision=result["decision"], isolation_contract=result["isolation_contract"], checked_at=datetime.now(timezone.utc))
            session.add(audit)
        else:
            audit.status = result["status"]
            audit.decision = result["decision"]
            audit.isolation_contract = result["isolation_contract"]
            audit.checked_at = datetime.now(timezone.utc)
        await session.commit()
    return result


async def _append_governance_event(
    assistant_id: uuid.UUID,
    *,
    category: str,
    event_key: str,
    status: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Persist non-personal audit evidence for a post-phase-one control."""
    async with SessionLocal() as session:
        event = BeeCFOGovernanceEvent(
            assistant_id=assistant_id,
            category=category,
            event_key=event_key[:160],
            status=status,
            payload=payload,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
    return {
        "id": str(event.id),
        "category": event.category,
        "event_key": event.event_key,
        "status": event.status,
        "created_at": _iso(event.created_at),
        "payload": event.payload,
    }


async def record_pilot_run(
    assistant_id: uuid.UUID,
    *,
    report_id: uuid.UUID,
    checks: dict[str, object],
) -> dict[str, object]:
    """Record one manual shadow-pilot observation without delivering it."""
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
    provided = dict(checks or {})
    # A run cannot claim success for a missing report. The remaining checks are
    # explicit operator evidence from a controlled replay/UAT run.
    provided["report_available"] = True
    assessment = assess_pilot_run(provided)
    payload: dict[str, object] = {
        "report_id": str(report_id),
        "watch_id": str(report.watch_id),
        "report_as_of": _iso(report.as_of),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "checks": {key: bool(provided.get(key)) for key in assessment["required_checks"]},
        **assessment,
    }
    event = await _append_governance_event(
        assistant_id,
        category="pilot_run",
        event_key=str(report_id),
        status="passed" if assessment["valid"] else "failed",
        payload=payload,
    )
    return {"status": "recorded", "run": event, "pilot": await pilot_status(assistant_id)}


async def _pilot_observation_window(assistant_id: uuid.UUID, *, watch_id: uuid.UUID) -> dict[str, object]:
    """Return the latest unsuppressed pilot evidence for one watch.

    Legacy events did not store ``watch_id``.  For those entries the report
    relation is consulted once, so the guard remains effective across upgrades.
    """
    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(BeeCFOGovernanceEvent)
                .where(
                    BeeCFOGovernanceEvent.assistant_id == assistant_id,
                    BeeCFOGovernanceEvent.category == "pilot_run",
                    BeeCFOGovernanceEvent.status != "suppressed",
                )
                .order_by(BeeCFOGovernanceEvent.created_at.desc())
                .limit(100)
            )
        ).scalars().all()
        report_ids: list[uuid.UUID] = []
        for event in events:
            try:
                report_ids.append(uuid.UUID(event.event_key))
            except (TypeError, ValueError):
                continue
        report_watch_ids: dict[str, uuid.UUID] = {}
        if report_ids:
            report_rows = (
                await session.execute(select(BeeCFOReport.id, BeeCFOReport.watch_id).where(BeeCFOReport.id.in_(report_ids)))
            ).all()
            report_watch_ids = {str(report_id): report_watch_id for report_id, report_watch_id in report_rows}
    latest: datetime | None = None
    for event in events:
        payload_watch_id = str((event.payload or {}).get("watch_id") or "")
        report_watch_id = report_watch_ids.get(event.event_key)
        if payload_watch_id == str(watch_id) or report_watch_id == watch_id:
            latest = event.created_at
            break
    eligibility = pilot_observation_eligibility(latest_observed_at=latest)
    return {**eligibility, "latest_observed_at": _iso(latest) if latest else None}


async def run_verified_pilot(
    assistant_id: uuid.UUID,
    *,
    watch_id: uuid.UUID,
    force: bool = False,
) -> dict[str, object]:
    """Run one complete, no-send Bee CFO pilot observation.

    It uses the same source contract, renderer and evidence gates as delivery,
    but it does not call ``deliver_report``.  The stored checklist is derived
    from typed receipts rather than operator-provided booleans.
    """
    observation = await _pilot_observation_window(assistant_id, watch_id=watch_id)
    if not observation["eligible"]:
        return {
            "status": "cooldown",
            "assistant_id": str(assistant_id),
            "watch_id": str(watch_id),
            "observation": observation,
            "pilot": await pilot_status(assistant_id),
            "outbound_message_sent": False,
            "scheduler_changed": False,
        }
    result = await run_report(
        assistant_id=assistant_id,
        watch_id=watch_id,
        report_kind="on_demand",
        force=force,
    )
    report = result.get("report") if isinstance(result.get("report"), dict) else None
    if report is None:
        raise ValueError("pilot report was not produced")
    report_id = uuid.UUID(str(report["id"]))
    profile = await get_or_create_profile(assistant_id)
    source_policy = _normalized_source_policy(profile.source_policy)
    analysis_windows = source_policy["analysis_windows"]
    quote = await capture_price_snapshot(
        assistant_id,
        settings=await settings_for_assistant(get_settings(), assistant_id),
        comparison_window_hours=int(analysis_windows["price_comparison_window_hours"]),
        comparison_tolerance_hours=int(analysis_windows["price_comparison_tolerance_hours"]),
        max_relative_spread=float(source_policy["quote_reconciliation"]["max_relative_spread"]),
        require_verifier=bool(source_policy["quote_reconciliation"]["require_verifier"]),
    )
    quality = await evidence_quality_for_report(assistant_id, report_id=report_id)
    canary_result = await prepare_canary(assistant_id, report_id=report_id)
    canary_preview = canary_result.get("preview") if isinstance(canary_result.get("preview"), dict) else {}
    shadow = await record_shadow_run(assistant_id, report_id=report_id)
    checks = build_verified_pilot_checks(
        report=report,
        price_snapshot=quote,
        quality_gate=quality.get("quality_gate") if isinstance(quality.get("quality_gate"), dict) else {},
        canary_preview=canary_preview,
        shadow_run=shadow,
    )
    recorded = await record_pilot_run(assistant_id, report_id=report_id, checks=checks)
    return {
        "status": "recorded",
        "assistant_id": str(assistant_id),
        "report_id": str(report_id),
        "report_status": result.get("status"),
        "checks": {"report_available": True, **checks},
        "quote_source_key": (quote.get("price_source_health") or {}).get("selected_source"),
        "canary_status": canary_preview.get("status"),
        "shadow_status": (shadow.get("run") or {}).get("status"),
        "pilot_run": recorded.get("run"),
        "pilot": recorded.get("pilot"),
        "observation": observation,
        "outbound_message_sent": False,
        "scheduler_changed": False,
    }


async def suppress_pilot_run(
    assistant_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    reason: str,
) -> dict[str, object]:
    """Suppress a demonstrably invalid operator entry without deleting its audit trail.

    Pilot entries are otherwise immutable.  Suppression is deliberately limited
    to failed entries so a valid run or a genuine production failure cannot be
    hidden from the completion calculation.  The original assessment remains
    in the payload alongside the correction metadata.
    """
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("suppression reason is required")
    already_suppressed = False
    async with SessionLocal() as session:
        event = await session.scalar(
            select(BeeCFOGovernanceEvent).where(
                BeeCFOGovernanceEvent.id == run_id,
                BeeCFOGovernanceEvent.assistant_id == assistant_id,
                BeeCFOGovernanceEvent.category == "pilot_run",
            )
        )
        if event is None:
            raise KeyError("pilot run not found")
        if event.status == "suppressed":
            already_suppressed = True
        elif event.status != "failed":
            raise ValueError("only failed pilot entries can be suppressed")
        else:
            payload = dict(event.payload or {})
            payload["suppression"] = {
                "reason": normalized_reason[:500],
                "suppressed_at": datetime.now(timezone.utc).isoformat(),
                "prior_status": event.status,
                "prior_failed_checks": list(payload.get("failed_checks") or []),
            }
            event.payload = payload
            event.status = "suppressed"
            await session.commit()
    return {
        "status": "already_suppressed" if already_suppressed else "suppressed",
        "run_id": str(run_id),
        "pilot": await pilot_status(assistant_id),
    }


async def pilot_status(assistant_id: uuid.UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(BeeCFOGovernanceEvent)
                .where(
                    BeeCFOGovernanceEvent.assistant_id == assistant_id,
                    BeeCFOGovernanceEvent.category == "pilot_run",
                    BeeCFOGovernanceEvent.status != "suppressed",
                )
                .order_by(BeeCFOGovernanceEvent.created_at.desc())
                .limit(200)
            )
        ).scalars().all()
    runs = [
        {
            "occurred_at": item.created_at,
            "valid": bool((item.payload or {}).get("valid")),
            "critical": bool((item.payload or {}).get("critical")),
        }
        for item in rows
    ]
    summary = summarize_pilot_runs(runs, now=datetime.now(timezone.utc))
    return {
        "assistant_id": str(assistant_id),
        "pilot": summary,
        "automatic_scheduler_changed": False,
        "recent_runs": [
            {
                "id": str(item.id),
                "report_id": (item.payload or {}).get("report_id"),
                "status": item.status,
                "failed_checks": (item.payload or {}).get("failed_checks", []),
                "created_at": _iso(item.created_at),
            }
            for item in rows[:30]
        ],
    }


async def record_source_decision(assistant_id: uuid.UUID, payload: dict[str, object]) -> dict[str, object]:
    """Create an auditable source decision. This endpoint cannot activate it."""
    normalized = validate_source_decision(payload)
    async with SessionLocal() as session:
        row = (await session.execute(
            select(BeeCFOIndicatorSource, BeeCFOIndicator)
            .join(BeeCFOIndicator, BeeCFOIndicator.id == BeeCFOIndicatorSource.indicator_id)
            .where(
                BeeCFOIndicatorSource.source_key == normalized["source_key"],
                BeeCFOIndicator.indicator_key == normalized["indicator_key"],
            )
        )).first()
        if row is None:
            raise KeyError("indicator source not found")
        source, indicator = row
    normalized["contract_fingerprint"] = source_contract_fingerprint(indicator=indicator, source=source)
    normalized["contract_revision"] = "bee-cfo-quote-control-1"
    normalized["provider_contract_revision"] = "bee-cfo-provider-contract-1"
    event = await _append_governance_event(
        assistant_id,
        category="source_decision",
        event_key=f"{normalized['indicator_key']}:{normalized['source_key']}",
        status=str(normalized["status"]),
        payload=normalized,
    )
    return {
        "status": "recorded",
        "decision": event,
        "activation_performed": False,
        "activation_requires": ["approved decision", "passed UAT", "separate owner activation"],
    }


async def source_ledger(assistant_id: uuid.UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        sources = (
            await session.execute(
                select(BeeCFOIndicatorSource, BeeCFOIndicator)
                .join(BeeCFOIndicator, BeeCFOIndicator.id == BeeCFOIndicatorSource.indicator_id)
                .order_by(BeeCFOIndicator.display_order, BeeCFOIndicatorSource.priority.desc())
            )
        ).all()
        events = (
            await session.execute(
                select(BeeCFOGovernanceEvent)
                .where(
                    BeeCFOGovernanceEvent.assistant_id == assistant_id,
                    BeeCFOGovernanceEvent.category == "source_decision",
                )
                .order_by(BeeCFOGovernanceEvent.created_at.desc())
            )
        ).scalars().all()
    latest: dict[str, BeeCFOGovernanceEvent] = {}
    for event in events:
        latest.setdefault(event.event_key, event)
    rows = []
    for source, indicator in sources:
        key = f"{indicator.indicator_key}:{source.source_key}"
        decision = latest.get(key)
        decision_payload = dict(decision.payload or {}) if decision else None
        contract = evaluate_source_contract(
            decision_payload,
            current_fingerprint=source_contract_fingerprint(indicator=indicator, source=source),
        )
        rows.append(
            {
                "indicator_key": indicator.indicator_key,
                "source_key": source.source_key,
                "name": source.name,
                "catalog_status": source.status,
                "source_url": source.fetch_url,
                "decision": decision_payload,
                "decision_status": decision.status if decision else "missing",
                "contract": contract,
                "provider_fixture": {
                    "registered": bool(decision_payload and decision_payload.get("provider_fixture")),
                    "enforced": bool(decision_payload and decision_payload.get("provider_fixture_enforced")),
                    "revision": (decision_payload or {}).get("provider_contract_revision"),
                },
                "revalidation_required": contract["revalidation_required"],
                "activation_permitted": False,
            }
        )
    return {"assistant_id": str(assistant_id), "count": len(rows), "sources": rows}


async def record_source_revalidation(assistant_id: uuid.UUID, *, indicator_key: str, source_key: str) -> dict[str, object]:
    """Audit contract drift; it never modifies or activates a source decision."""
    event_key = f"{indicator_key.strip().upper()}:{source_key.strip()}"
    async with SessionLocal() as session:
        row = (await session.execute(
            select(BeeCFOIndicatorSource, BeeCFOIndicator)
            .join(BeeCFOIndicator, BeeCFOIndicator.id == BeeCFOIndicatorSource.indicator_id)
            .where(BeeCFOIndicator.indicator_key == indicator_key.strip().upper(), BeeCFOIndicatorSource.source_key == source_key.strip())
        )).first()
        if row is None:
            raise KeyError("indicator source not found")
        source, indicator = row
        decision = await session.scalar(
            select(BeeCFOGovernanceEvent)
            .where(
                BeeCFOGovernanceEvent.assistant_id == assistant_id,
                BeeCFOGovernanceEvent.category == "source_decision",
                BeeCFOGovernanceEvent.event_key == event_key,
            )
            .order_by(BeeCFOGovernanceEvent.created_at.desc())
        )
    contract = evaluate_source_contract(
        dict(decision.payload or {}) if decision else None,
        current_fingerprint=source_contract_fingerprint(indicator=indicator, source=source),
    )
    audit = await _append_governance_event(
        assistant_id,
        category="source_revalidation",
        event_key=event_key,
        status="passed" if contract["delivery_permitted"] else "failed",
        payload={"contract": contract, "activation_performed": False},
    )
    return {"assistant_id": str(assistant_id), "source": event_key, "contract": contract, "audit": audit, "activation_performed": False}


async def evidence_pack_for_report(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
    state = dict(report.current_state or {})
    pack = state.get("evidence_pack")
    return {
        "assistant_id": str(assistant_id),
        "report_id": str(report_id),
        "verification": verify_evidence_pack(pack),
        "evidence_pack": pack,
    }


async def claim_lifecycle_for_report(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
    lifecycle = (report.current_state or {}).get("media_claim_lifecycle")
    return {"assistant_id": str(assistant_id), "report_id": str(report_id), "lifecycle": lifecycle or {"claims": []}}


async def prepare_canary(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    """Produce a stored observer preview. It does not contact Telegram."""
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
        watch = await session.scalar(select(BeeCFOWatch).where(BeeCFOWatch.id == report.watch_id))
        if watch is None:
            raise KeyError("watch not found")
        report_payload = _report_payload(report)
    preview = build_canary_preview(report=report_payload, watch_name=watch.name)
    audit = await _append_governance_event(
        assistant_id,
        category="canary",
        event_key=f"report:{report_id}",
        status=str(preview["status"]),
        payload={
            "revision": preview["revision"],
            "report_hash": preview["report_hash"],
            "checks": preview["checks"],
            "evidence": preview["evidence"],
            "message_counts": {key: len(value) for key, value in preview["preview"].items()},
            "outbound_message_sent": False,
        },
    )
    return {"assistant_id": str(assistant_id), "report_id": str(report_id), "preview": preview, "audit": audit}


async def approve_canary(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    """Record an owner-controlled promotion; it never sends or schedules delivery."""
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
        watch = await session.scalar(select(BeeCFOWatch).where(BeeCFOWatch.id == report.watch_id))
        latest = await session.scalar(
            select(BeeCFOGovernanceEvent)
            .where(
                BeeCFOGovernanceEvent.assistant_id == assistant_id,
                BeeCFOGovernanceEvent.category == "canary",
                BeeCFOGovernanceEvent.event_key == f"report:{report_id}",
                BeeCFOGovernanceEvent.status == "passed",
            )
            .order_by(BeeCFOGovernanceEvent.created_at.desc())
        )
        if watch is None:
            raise KeyError("watch not found")
        report_payload = _report_payload(report)
    preview = build_canary_preview(report=report_payload, watch_name=watch.name)
    if latest is None or (latest.payload or {}).get("report_hash") != preview["report_hash"] or preview["status"] != "passed":
        raise ValueError("a current successful canary preview is required before approval")
    audit = await _append_governance_event(
        assistant_id,
        category="canary",
        event_key=f"report:{report_id}",
        status="approved",
        payload={
            "revision": preview["revision"],
            "report_hash": preview["report_hash"],
            "approved_from_event": str(latest.id),
            "outbound_message_sent": False,
            "scheduler_changed": False,
        },
    )
    return {"assistant_id": str(assistant_id), "report_id": str(report_id), "approval": audit, "outbound_message_sent": False}


async def canary_status(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        events = (await session.execute(
            select(BeeCFOGovernanceEvent)
            .where(
                BeeCFOGovernanceEvent.assistant_id == assistant_id,
                BeeCFOGovernanceEvent.category == "canary",
                BeeCFOGovernanceEvent.event_key == f"report:{report_id}",
            )
            .order_by(BeeCFOGovernanceEvent.created_at.desc())
            .limit(10)
        )).scalars().all()
    return {
        "assistant_id": str(assistant_id),
        "report_id": str(report_id),
        "events": [
            {"id": str(event.id), "status": event.status, "payload": event.payload, "created_at": _iso(event.created_at)}
            for event in events
        ],
        "outbound_message_sent": False,
    }


async def record_shadow_run(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    """Store an idempotent shadow execution record; no delivery is possible here."""
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
        previous = await session.scalar(
            select(BeeCFOReport)
            .where(
                BeeCFOReport.assistant_id == assistant_id,
                BeeCFOReport.watch_id == report.watch_id,
                BeeCFOReport.as_of < report.as_of,
            )
            .order_by(BeeCFOReport.as_of.desc())
        )
        shadow = build_shadow_run(
            report=_report_payload(report),
            previous_report=_report_payload(previous) if previous is not None else None,
        )
        existing = await session.scalar(
            select(BeeCFOGovernanceEvent)
            .where(
                BeeCFOGovernanceEvent.assistant_id == assistant_id,
                BeeCFOGovernanceEvent.category == "shadow_run",
                BeeCFOGovernanceEvent.event_key == str(shadow["run_key"]),
            )
            .order_by(BeeCFOGovernanceEvent.created_at.desc())
        )
    if existing is not None:
        return {
            "assistant_id": str(assistant_id),
            "report_id": str(report_id),
            "status": "reused",
            "run": {
                "id": str(existing.id), "status": existing.status, "created_at": _iso(existing.created_at),
                "payload": existing.payload,
            },
            "outbound_message_sent": False,
            "scheduler_changed": False,
        }
    audit = await _append_governance_event(
        assistant_id,
        category="shadow_run",
        event_key=str(shadow["run_key"]),
        status=str(shadow["status"]),
        payload=shadow,
    )
    return {
        "assistant_id": str(assistant_id),
        "report_id": str(report_id),
        "status": "recorded",
        "run": audit,
        "outbound_message_sent": False,
        "scheduler_changed": False,
    }


async def shadow_run_status(assistant_id: uuid.UUID, *, report_id: uuid.UUID) -> dict[str, object]:
    """Return recorded shadow runs for one report without touching delivery."""
    async with SessionLocal() as session:
        events = (await session.execute(
            select(BeeCFOGovernanceEvent)
            .where(
                BeeCFOGovernanceEvent.assistant_id == assistant_id,
                BeeCFOGovernanceEvent.category == "shadow_run",
                BeeCFOGovernanceEvent.event_key.like(f"report:{report_id}:output:%"),
            )
            .order_by(BeeCFOGovernanceEvent.created_at.desc())
            .limit(20)
        )).scalars().all()
    return {
        "assistant_id": str(assistant_id),
        "report_id": str(report_id),
        "runs": [
            {"id": str(event.id), "status": event.status, "payload": event.payload, "created_at": _iso(event.created_at)}
            for event in events
        ],
        "outbound_message_sent": False,
        "scheduler_changed": False,
    }


async def get_attention_policy(assistant_id: uuid.UUID) -> dict[str, object]:
    profile = await get_or_create_profile(assistant_id)
    policy = normalize_attention_policy(dict(profile.source_policy or {}).get("attention_policy"))
    return {"assistant_id": str(assistant_id), "policy": policy, "delivery_performed": False}


async def update_attention_policy(assistant_id: uuid.UUID, payload: dict[str, object]) -> dict[str, object]:
    policy = normalize_attention_policy(payload)
    async with SessionLocal() as session:
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
        if profile is None:
            raise KeyError("Bee CFO profile not found")
        source_policy = {**DEFAULT_SOURCE_POLICY, **dict(profile.source_policy or {})}
        source_policy["attention_policy"] = policy
        profile.source_policy = source_policy
        profile.revision = str(policy["revision"])
        await session.commit()
    await _append_governance_event(
        assistant_id,
        category="attention",
        event_key="policy",
        status="recorded",
        payload={"kind": "policy", "policy": policy, "delivery_performed": False},
    )
    return {"assistant_id": str(assistant_id), "policy": policy, "delivery_performed": False}


async def evaluate_attention_candidate(assistant_id: uuid.UUID, candidate: dict[str, object]) -> dict[str, object]:
    policy = (await get_attention_policy(assistant_id))["policy"]
    now = datetime.now(timezone.utc)
    dedup_key = str(candidate.get("dedup_key") or "").strip()
    if not dedup_key:
        raise ValueError("candidate dedup_key is required")
    async with SessionLocal() as session:
        recent = (
            await session.execute(
                select(BeeCFOGovernanceEvent)
                .where(
                    BeeCFOGovernanceEvent.assistant_id == assistant_id,
                    BeeCFOGovernanceEvent.category == "attention",
                    BeeCFOGovernanceEvent.created_at >= now - timedelta(hours=24),
                )
                .order_by(BeeCFOGovernanceEvent.created_at.desc())
            )
        ).scalars().all()
    prior_candidates = [item for item in recent if item.event_key != "policy"]
    duplicate_seen = any(
        item.event_key == dedup_key
        and item.created_at >= now - timedelta(hours=int(policy["dedup_hours"]))
        for item in prior_candidates
    )
    decision = evaluate_attention_budget(
        candidate,
        policy=policy,
        recent_count=sum(item.status == "eligible" for item in prior_candidates),
        duplicate_seen=duplicate_seen,
        now=now,
    )
    event = await _append_governance_event(
        assistant_id,
        category="attention",
        event_key=dedup_key,
        status=str(decision["status"]),
        payload={"candidate": candidate, "decision": decision, "delivery_performed": False},
    )
    return {"assistant_id": str(assistant_id), "decision": decision, "audit": event}


async def market_pack_readiness(assistant_id: uuid.UUID) -> dict[str, object]:
    ledger = await source_ledger(assistant_id)
    by_indicator: dict[str, list[dict[str, object]]] = {}
    for row in ledger["sources"]:
        by_indicator.setdefault(str(row["indicator_key"]), []).append(row)
    packs = []
    for pack in MARKET_PACKS:
        rows = by_indicator.get(str(pack["indicator_key"]), [])
        approved = [
            row for row in rows
            if row.get("decision_status") == "approved"
            and isinstance(row.get("decision"), dict)
            and row["decision"].get("uat_status") == "passed"
        ]
        packs.append(
            {
                **pack,
                "source_decision_ready": bool(approved),
                "approved_source_count": len(approved),
                "activation_performed": False,
                "status": "ready_for_owner_activation" if approved else "blocked_by_source_decision",
            }
        )
    return {
        "assistant_id": str(assistant_id),
        "packs": packs,
        "sequence": [item["pack_key"] for item in MARKET_PACKS],
        "automatic_market_activation": False,
    }


async def why_changed(
    assistant_id: uuid.UUID,
    *,
    report_id: uuid.UUID,
    requestor: str = "api",
) -> dict[str, object]:
    """Explain a stored report delta; never re-runs analysis or forecasts."""
    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(BeeCFOReport.id == report_id, BeeCFOReport.assistant_id == assistant_id)
        )
        if report is None:
            raise KeyError("report not found")
        watch = await session.scalar(select(BeeCFOWatch).where(BeeCFOWatch.id == report.watch_id))
        previous = await session.scalar(
            select(BeeCFOReport)
            .where(
                BeeCFOReport.assistant_id == assistant_id,
                BeeCFOReport.watch_id == report.watch_id,
                BeeCFOReport.as_of < report.as_of,
            )
            .order_by(BeeCFOReport.as_of.desc())
        )
    current_payload = _report_payload(report)
    current_state = dict(report.current_state or {})
    previous_state = dict(previous.current_state or {}) if previous else None
    diff = build_report_diff(previous_state, current_state)
    new_ids = {str(item) for item in diff.get("new_evidence_ids", []) if item}
    current_cards = current_state.get("evidence_cards") if isinstance(current_state.get("evidence_cards"), list) else []
    diff["new_evidence"] = [
        item for item in current_cards
        if isinstance(item, dict) and str(item.get("evidence_id")) in new_ids
    ][:3]
    message = render_why_changed_message(
        diff=diff,
        report=current_payload,
        watch_name=watch.name if watch else "گزارش بازار",
    )
    audit = await _append_governance_event(
        assistant_id,
        category="why_changed",
        event_key=str(report_id),
        status="served",
        payload={
            "report_id": str(report_id),
            "previous_report_id": str(previous.id) if previous else None,
            "requestor": str(requestor)[:128],
            "no_model_rerun": True,
            "evidence_count": len(current_payload.get("citations") or []),
        },
    )
    return {
        "assistant_id": str(assistant_id),
        "report_id": str(report_id),
        "previous_report_id": str(previous.id) if previous else None,
        "diff": diff,
        "message": message,
        "no_model_rerun": True,
        "no_personal_advice": True,
        "audit": audit,
    }


async def why_changed_for_report(report_id: uuid.UUID, *, requestor: str) -> dict[str, object]:
    """Resolve the Bee CFO workspace internally for a typed Telegram command."""
    async with SessionLocal() as session:
        report = await session.get(BeeCFOReport, report_id)
    if report is None:
        raise KeyError("report not found")
    return await why_changed(report.assistant_id, report_id=report_id, requestor=requestor)


async def get_privacy_boundary(assistant_id: uuid.UUID) -> dict[str, object]:
    profile = await get_or_create_profile(assistant_id)
    boundary = normalize_privacy_boundary(dict(profile.source_policy or {}).get("privacy_boundary"))
    return {"assistant_id": str(assistant_id), "boundary": boundary, "personal_data_processed": False}


async def update_privacy_boundary(assistant_id: uuid.UUID, payload: dict[str, object]) -> dict[str, object]:
    boundary = normalize_privacy_boundary(payload)
    async with SessionLocal() as session:
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
        if profile is None:
            raise KeyError("Bee CFO profile not found")
        policy = {**DEFAULT_SOURCE_POLICY, **dict(profile.source_policy or {})}
        policy["privacy_boundary"] = boundary
        profile.source_policy = policy
        profile.revision = str(boundary["revision"])
        await session.commit()
    audit = await _append_governance_event(
        assistant_id,
        category="privacy_boundary",
        event_key="phase_two_design",
        status="recorded",
        payload={"boundary": boundary, "personal_data_processed": False},
    )
    return {"assistant_id": str(assistant_id), "boundary": boundary, "audit": audit, "personal_data_processed": False}


async def deliver_report(
    *,
    assistant_id: uuid.UUID,
    report_id: uuid.UUID,
    repeat: bool = False,
) -> dict[str, object]:
    """Deliver price first, then one outlook card per horizon.

    Normal delivery is idempotent. ``repeat`` is an explicit human-gated
    exception for a requested sample/replay and appends the new Telegram
    message ids to the delivery ledger instead of overwriting its history.
    """
    settings = await settings_for_assistant(get_settings(), assistant_id)
    profile = await get_or_create_profile(assistant_id)
    source_policy = _normalized_source_policy(profile.source_policy)
    analysis_windows = source_policy["analysis_windows"]
    destination = settings.telegram_channel_id
    if settings.telegram_bot_token is None or not destination:
        return {
            "status": "not_configured",
            "report_id": str(report_id),
            "reason": "Bee CFO Telegram token or destination is not configured",
        }
    try:
        destination = validate_telegram_destination(destination)
    except ValueError as exc:
        return {"status": "invalid_destination", "report_id": str(report_id), "reason": str(exc)}

    async with SessionLocal() as session:
        report = await session.scalar(
            select(BeeCFOReport).where(
                BeeCFOReport.id == report_id,
                BeeCFOReport.assistant_id == assistant_id,
            )
        )
        if report is None:
            raise KeyError("report not found")
        watch = await session.scalar(
            select(BeeCFOWatch).where(
                BeeCFOWatch.id == report.watch_id,
                BeeCFOWatch.assistant_id == assistant_id,
            )
        )
        if watch is None:
            raise KeyError("watch not found")
        quality_gate = (report.current_state or {}).get("evidence_quality_gate")
        if not isinstance(quality_gate, dict):
            quality_gate = assess_evidence_quality(dict(report.current_state or {}))
        if not quality_gate.get("publication_permitted"):
            return {
                "status": "evidence_quality_blocked",
                "report_id": str(report.id),
                "reason": "report evidence quality gate did not permit publication",
                "quality_gate": quality_gate,
                "outbound_message_sent": False,
            }
        capacity = (report.current_state or {}).get("capacity_budget")
        if isinstance(capacity, dict) and capacity.get("status") == "blocked":
            return {
                "status": "capacity_blocked",
                "report_id": str(report.id),
                "reason": "report capacity budget exceeded before delivery",
                "capacity": capacity,
                "outbound_message_sent": False,
            }
        if bool(source_policy["canary_policy"].get("enforced")):
            preview = build_canary_preview(report=_report_payload(report), watch_name=watch.name)
            approval = await session.scalar(
                select(BeeCFOGovernanceEvent)
                .where(
                    BeeCFOGovernanceEvent.assistant_id == assistant_id,
                    BeeCFOGovernanceEvent.category == "canary",
                    BeeCFOGovernanceEvent.event_key == f"report:{report.id}",
                    BeeCFOGovernanceEvent.status == "approved",
                )
                .order_by(BeeCFOGovernanceEvent.created_at.desc())
            )
            if preview["status"] != "passed" or approval is None or (approval.payload or {}).get("report_hash") != preview["report_hash"]:
                return {
                    "status": "canary_required",
                    "report_id": str(report.id),
                    "reason": "a current successful canary preview and manual approval are required",
                    "outbound_message_sent": False,
                }

        price_ledger = await session.scalar(
            select(BeeCFOPriceDelivery)
            .where(
                BeeCFOPriceDelivery.assistant_id == assistant_id,
                BeeCFOPriceDelivery.report_id == report.id,
                BeeCFOPriceDelivery.destination_id == destination,
            )
            .with_for_update()
        )
        price_already_sent = bool(price_ledger and price_ledger.status == "sent")
        if price_ledger is None:
            price_ledger = BeeCFOPriceDelivery(
                assistant_id=assistant_id,
                report_id=report.id,
                destination_id=destination,
                status="pending",
                renderer_revision=BEE_CFO_PRICE_RENDERER_REVISION,
            )
            session.add(price_ledger)
        elif not price_already_sent:
            price_ledger.status = "pending"
            price_ledger.error_message = None
            price_ledger.renderer_revision = BEE_CFO_PRICE_RENDERER_REVISION

        ledger = await session.scalar(
            select(BeeCFODelivery)
            .where(
                BeeCFODelivery.assistant_id == assistant_id,
                BeeCFODelivery.report_id == report.id,
                BeeCFODelivery.destination_id == destination,
            )
            .with_for_update()
        )
        previously_sent = bool(ledger and ledger.status == "sent")
        repeat_delivery = bool(repeat and previously_sent)
        if previously_sent and price_already_sent and not repeat_delivery:
            return {
                "status": "duplicate",
                "report_id": str(report.id),
                "destination_id": destination,
                "price_message_ids": list(price_ledger.message_ids or []),
                "media_message_ids": list(ledger.media_message_ids or []),
                "message_ids": list(ledger.message_ids or []),
            }
        if repeat_delivery:
            # Re-render and send both cards while preserving the old ids.
            price_already_sent = False
        if ledger is None:
            ledger = BeeCFODelivery(
                assistant_id=assistant_id,
                report_id=report.id,
                destination_id=destination,
                destination_type="channel" if destination.startswith("-100") else "private_chat",
                status="pending",
                attempt=1,
                renderer_revision=BEE_CFO_RENDERER_REVISION,
            )
            session.add(ledger)
        elif ledger.status != "sent":
            ledger.status = "pending"
            ledger.attempt = int(ledger.attempt or 0) + 1
            ledger.error_message = None
            ledger.renderer_revision = BEE_CFO_RENDERER_REVISION
        elif repeat_delivery:
            ledger.attempt = int(ledger.attempt or 0) + 1
            ledger.error_message = None
            ledger.renderer_revision = BEE_CFO_RENDERER_REVISION
        await session.commit()
        price_ledger_id = price_ledger.id
        ledger_id = ledger.id
        report_payload = _report_payload(report)
        watch_name = watch.name
        report_was_sent = previously_sent and not repeat_delivery
        media_message_ids: list[int] = [] if repeat_delivery else list(ledger.media_message_ids or [])

    telegram = TelegramClient(settings)
    price_snapshot: dict[str, object] | None = None
    price_message_ids: list[int] = list(price_ledger.message_ids or []) if price_already_sent else []
    if not price_already_sent:
        try:
            price_snapshot = await capture_price_snapshot(
                assistant_id,
                settings=settings,
                comparison_window_hours=int(analysis_windows["price_comparison_window_hours"]),
                comparison_tolerance_hours=int(analysis_windows["price_comparison_tolerance_hours"]),
                max_relative_spread=float(source_policy["quote_reconciliation"].get("max_relative_spread", 0.10)),
                require_verifier=bool(source_policy["quote_reconciliation"].get("require_verifier", False)),
            )
            live_state = dict(report_payload.get("current_state") or {})
            live_state["live_price"] = price_snapshot
            live_state["price_comparison"] = price_snapshot.get("comparison") or live_state.get("price_comparison")
            report_payload["current_state"] = live_state
            price_message = render_price_message(snapshot=price_snapshot)
            price_message_ids = await telegram.send_analysis(
                price_message,
                analysis_id=report_id,
                channel_id=destination,
                include_feedback_buttons=False,
                silent=settings.telegram_silent_notifications,
            )
        except (IndicatorSelectionRequired, PriceUnavailable, ValueError) as exc:
            async with SessionLocal() as session:
                price_row = await session.get(BeeCFOPriceDelivery, price_ledger_id)
                if price_row is not None:
                    price_row.status = "failed"
                    price_row.error_message = str(exc)[:1000]
                    await session.commit()
            return {
                "status": "price_unavailable",
                "report_id": str(report_id),
                "destination_id": destination,
                "reason": str(exc)[:500],
            }
        except Exception as exc:
            async with SessionLocal() as session:
                price_row = await session.get(BeeCFOPriceDelivery, price_ledger_id)
                if price_row is not None:
                    price_row.status = "failed"
                    price_row.error_message = f"{type(exc).__name__}: {exc}"[:1000]
                    await session.commit()
            return {
                "status": "price_delivery_failed",
                "report_id": str(report_id),
                "destination_id": destination,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }

        async with SessionLocal() as session:
            price_row = await session.get(BeeCFOPriceDelivery, price_ledger_id)
            if price_row is not None:
                price_row.status = "sent"
                existing_ids = list(price_row.message_ids or [])
                price_row.message_ids = existing_ids + [item for item in price_message_ids if item not in existing_ids]
                price_row.snapshot_id = uuid.UUID(str(price_snapshot["id"])) if price_snapshot else None
                price_row.sent_at = datetime.now(timezone.utc)
                price_row.error_message = None
            await session.commit()

    if report_was_sent:
        return {
            "status": "price_backfill_sent",
            "report_id": str(report_id),
            "destination_id": destination,
            "price_message_ids": list(price_message_ids),
            "media_message_ids": list(media_message_ids),
            "renderer_revision": BEE_CFO_PRICE_RENDERER_REVISION,
        }

    if not media_message_ids:
        try:
            media_message_ids = []
            # The established price and media-outlook cards are rendered
            # first and unchanged.  Follow-up cards are strictly append-only.
            post_price_messages = [
                *render_media_outlook_messages(report=report_payload, watch_name=watch_name),
                *render_followup_messages(report=report_payload, watch_name=watch_name),
            ]
            for media_message in post_price_messages:
                message_limit = (
                    BEE_CFO_FOLLOWUP_MESSAGE_LIMIT
                    if media_message.startswith(("🧩", "🔭", "🎯", "🧪", "🗓"))
                    else BEE_CFO_MEDIA_MESSAGE_LIMIT
                )
                media_message_ids.extend(
                    await telegram.send_analysis(
                        media_message,
                        analysis_id=report_id,
                        channel_id=destination,
                        include_feedback_buttons=False,
                        silent=settings.telegram_silent_notifications,
                        message_limit=message_limit,
                    )
                )
        except Exception as exc:
            async with SessionLocal() as session:
                ledger = await session.get(BeeCFODelivery, ledger_id)
                if ledger is not None:
                    ledger.status = "failed"
                    ledger.error_message = f"media: {type(exc).__name__}: {exc}"[:1000]
                    await session.commit()
            return {
                "status": "media_delivery_failed",
                "report_id": str(report_id),
                "destination_id": destination,
                "price_message_ids": list(price_message_ids),
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        async with SessionLocal() as session:
            ledger = await session.get(BeeCFODelivery, ledger_id)
            if ledger is not None:
                existing_ids = list(ledger.media_message_ids or [])
                ledger.media_message_ids = existing_ids + [item for item in media_message_ids if item not in existing_ids]
                ledger.error_message = None
                await session.commit()

    if not media_message_ids:
        async with SessionLocal() as session:
            ledger = await session.get(BeeCFODelivery, ledger_id)
            if ledger is not None:
                ledger.status = "failed"
                ledger.error_message = "media delivery returned no Telegram message ids"
                await session.commit()
        return {
            "status": "media_delivery_failed",
            "report_id": str(report_id),
            "destination_id": destination,
            "price_message_ids": list(price_message_ids),
            "media_message_ids": [],
            "error": "media delivery returned no Telegram message ids",
        }

    sent_at = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        ledger = await session.get(BeeCFODelivery, ledger_id)
        report = await session.get(BeeCFOReport, report_id)
        if ledger is not None:
            ledger.status = "sent"
            # The approved channel contract has no third, generic report
            # message. Keep any historical ids intact, but do not create new
            # ones for this delivery.
            ledger.message_ids = list(ledger.message_ids or [])
            existing_media_ids = list(ledger.media_message_ids or [])
            ledger.media_message_ids = existing_media_ids + [
                item for item in media_message_ids if item not in existing_media_ids
            ]
            ledger.sent_at = sent_at
            ledger.error_message = None
        if report is not None:
            report.status = "published"
        await session.commit()
    return {
        "status": "sent",
        "report_id": str(report_id),
        "destination_id": destination,
        "price_message_ids": list(price_message_ids),
        "media_message_ids": list(media_message_ids),
        "message_ids": [],
        "renderer_revision": BEE_CFO_RENDERER_REVISION,
        "price_renderer_revision": BEE_CFO_PRICE_RENDERER_REVISION,
        "repeated": repeat_delivery,
    }


async def run_scheduled_reports(*, assistant_id: uuid.UUID, now: datetime | None = None) -> dict[str, object]:
    """Run all active watches for one already-claimed schedule slot."""
    async with SessionLocal() as session:
        profile = await session.scalar(select(BeeCFOProfile).where(BeeCFOProfile.assistant_id == assistant_id))
        if profile is None or profile.status != "active":
            return {"status": "profile_not_active", "assistant_id": str(assistant_id), "watch_count": 0, "reports": []}
        watches = (await session.execute(select(BeeCFOWatch).where(BeeCFOWatch.assistant_id == assistant_id, BeeCFOWatch.status == "active"))).scalars().all()
    results = []
    for watch in watches:
        result = await run_report(assistant_id=assistant_id, watch_id=watch.id, report_kind="scheduled")
        report_payload = result.get("report") if isinstance(result.get("report"), dict) else {}
        report_id = report_payload.get("id")
        if report_id:
            result["delivery"] = await deliver_report(
                assistant_id=assistant_id,
                report_id=uuid.UUID(str(report_id)),
            )
        results.append(result)
    return {"status": "completed", "assistant_id": str(assistant_id), "watch_count": len(watches), "reports": results}
