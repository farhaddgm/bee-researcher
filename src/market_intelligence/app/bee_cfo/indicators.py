from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.database import SessionLocal
from app.models import (
    AssistantWorkspace,
    BeeCFOAssistantIndicatorSelection,
    BeeCFOGovernanceEvent,
    BeeCFOIndicator,
    BeeCFOIndicatorSource,
    BeeCFOMarket,
    BeeCFOPriceSnapshot,
)

from .governance import source_decision_allows_delivery
from .price import PriceQuote, fetch_price_quote, validate_quote_delta
from .operations import build_price_source_health
from .quote_control import build_provider_fixture, evaluate_provider_response, reconcile_quotes, source_contract_fingerprint, sources_independent
from .windows import (
    DEFAULT_PRICE_COMPARISON_TOLERANCE_HOURS,
    DEFAULT_PRICE_COMPARISON_WINDOW_HOURS,
)


class IndicatorSelectionRequired(ValueError):
    pass


class PriceUnavailable(ValueError):
    pass


def _source_payload(source: BeeCFOIndicatorSource) -> dict[str, object]:
    return {
        "id": str(source.id),
        "source_key": source.source_key,
        "name": source.name,
        "homepage_url": source.homepage_url,
        "fetch_url": source.fetch_url,
        "adapter": source.adapter,
        "priority": source.priority,
        "status": source.status,
        "last_checked_at": source.last_checked_at.isoformat() if source.last_checked_at else None,
        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
        "last_error": source.last_error,
    }


def _source_uat_state(source: BeeCFOIndicatorSource) -> str:
    """Classify direct-price-source readiness without probing or mutating it."""
    if source.status == "disabled":
        return "disabled"
    if source.status == "draft":
        return "approval_required"
    if source.last_success_at is not None:
        return "passed"
    return "pending_uat"


def _catalog_option_readiness(
    *,
    market: BeeCFOMarket,
    indicator: BeeCFOIndicator,
    sources: list[BeeCFOIndicatorSource],
    selected: bool,
    approved_source_keys: set[str] | None = None,
) -> dict[str, object]:
    """Build a secret-free, explainable readiness card for one catalog option."""
    active_sources = [source for source in sources if source.status == "active"]
    source_states = [_source_uat_state(source) for source in sources]
    delivery_sources = [source for source in active_sources if approved_source_keys is None or source.source_key in approved_source_keys]
    delivery_source_keys = {source.source_key for source in delivery_sources}
    if not active_sources:
        status = "approval_required" if any(state == "approval_required" for state in source_states) else "blocked"
    elif not delivery_sources:
        status = "approval_required"
    elif any(_source_uat_state(source) == "passed" for source in delivery_sources):
        status = "ready"
    else:
        status = "pending_uat"
    blockers: list[str] = []
    warnings: list[str] = []
    if market.status != "active":
        blockers.append("market is not active")
    if indicator.status != "active":
        blockers.append("indicator is not active")
    if not active_sources:
        blockers.append("no owner-approved active direct price source")
    elif not delivery_sources:
        blockers.append("no active direct source has an approved, passed owner decision")
    elif not any(_source_uat_state(source) == "passed" for source in delivery_sources):
        blockers.append("at least one active direct source needs a live UAT probe")
    if any(state == "approval_required" for state in source_states):
        message = "a draft direct source needs explicit owner approval before activation"
        if active_sources:
            warnings.append(message)
        else:
            blockers.append(message)
    return {
        "market_key": market.market_key,
        "indicator_key": indicator.indicator_key,
        "display_name": indicator.display_name,
        "selected": selected,
        "status": status,
        "ready_for_delivery": status == "ready",
        "blockers": blockers,
        "warnings": warnings,
        "sources": [
            {
                **_source_payload(source),
                "uat_state": _source_uat_state(source),
                "probe_required": source.status == "active" and source.last_success_at is None,
                "delivery_eligible": source.source_key in delivery_source_keys,
            }
            for source in sources
        ],
    }


async def _approved_source_keys(
    assistant_id: uuid.UUID,
    *,
    sources: list[BeeCFOIndicatorSource],
    indicators_by_id: dict[uuid.UUID, BeeCFOIndicator],
) -> set[str]:
    """Read the latest source-decision ledger without mutating catalog state."""
    return set((await _approved_source_decisions(
        assistant_id, sources=sources, indicators_by_id=indicators_by_id,
    )).keys())


async def _approved_source_decisions(
    assistant_id: uuid.UUID,
    *,
    sources: list[BeeCFOIndicatorSource],
    indicators_by_id: dict[uuid.UUID, BeeCFOIndicator],
) -> dict[str, dict[str, object]]:
    """Return pinned owner decisions keyed by source without changing state."""
    source_pairs = {
        f"{indicators_by_id[source.indicator_id].indicator_key}:{source.source_key}": source
        for source in sources
        if source.indicator_id in indicators_by_id
    }
    if not source_pairs:
        return {}
    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(BeeCFOGovernanceEvent)
                .where(
                    BeeCFOGovernanceEvent.assistant_id == assistant_id,
                    BeeCFOGovernanceEvent.category == "source_decision",
                    BeeCFOGovernanceEvent.event_key.in_(list(source_pairs)),
                )
                .order_by(BeeCFOGovernanceEvent.created_at.desc())
            )
        ).scalars().all()
    latest: dict[str, BeeCFOGovernanceEvent] = {}
    for event in events:
        latest.setdefault(event.event_key, event)
    allowed: dict[str, dict[str, object]] = {}
    for event_key, source in source_pairs.items():
        event = latest.get(event_key)
        indicator = indicators_by_id[source.indicator_id]
        if event and source_decision_allows_delivery(
            event.status,
            event.payload,
            indicator_key=indicator.indicator_key,
            source_key=source.source_key,
            current_contract_fingerprint=source_contract_fingerprint(indicator=indicator, source=source),
        ):
            allowed[source.source_key] = dict(event.payload or {})
    return allowed


def _indicator_payload(indicator: BeeCFOIndicator, sources: list[BeeCFOIndicatorSource]) -> dict[str, object]:
    return {
        "id": str(indicator.id),
        "market_key": indicator.market_key,
        "indicator_key": indicator.indicator_key,
        "name": indicator.name,
        "display_name": indicator.display_name,
        "quote_unit": indicator.quote_unit,
        "currency": indicator.currency,
        "parser_key": indicator.parser_key,
        "status": indicator.status,
        "display_order": indicator.display_order,
        "sources": [_source_payload(source) for source in sources],
    }


def _selection_payload(selection: BeeCFOAssistantIndicatorSelection | None, *, indicator: BeeCFOIndicator | None = None, market: BeeCFOMarket | None = None) -> dict[str, object] | None:
    if selection is None:
        return None
    return {
        "id": str(selection.id),
        "assistant_id": str(selection.assistant_id),
        "market_key": selection.market_key,
        "market_name": market.display_name if market else selection.market_key,
        "indicator_key": selection.indicator_key,
        "indicator_name": indicator.display_name if indicator else selection.indicator_key,
        "status": selection.status,
        "revision": selection.revision,
        "updated_at": selection.updated_at.isoformat() if selection.updated_at else None,
    }


async def list_indicator_catalog(*, include_disabled: bool = False) -> dict[str, object]:
    async with SessionLocal() as session:
        market_query = select(BeeCFOMarket).order_by(BeeCFOMarket.display_order, BeeCFOMarket.market_key)
        indicator_query = select(BeeCFOIndicator).order_by(BeeCFOIndicator.display_order, BeeCFOIndicator.indicator_key)
        if not include_disabled:
            market_query = market_query.where(BeeCFOMarket.status != "disabled")
            indicator_query = indicator_query.where(BeeCFOIndicator.status != "disabled")
        markets = (await session.execute(market_query)).scalars().all()
        indicators = (await session.execute(indicator_query)).scalars().all()
        sources = (
            await session.execute(
                select(BeeCFOIndicatorSource).where(
                    BeeCFOIndicatorSource.indicator_id.in_([item.id for item in indicators])
                ).order_by(BeeCFOIndicatorSource.priority.desc(), BeeCFOIndicatorSource.source_key)
            )
        ).scalars().all() if indicators else []
    by_indicator: dict[uuid.UUID, list[BeeCFOIndicatorSource]] = {}
    for source in sources:
        by_indicator.setdefault(source.indicator_id, []).append(source)
    return {
        "markets": [
            {
                "id": str(market.id),
                "market_key": market.market_key,
                "name": market.name,
                "display_name": market.display_name,
                "region": market.region,
                "currency": market.currency,
                "status": market.status,
                "indicators": [
                    _indicator_payload(indicator, by_indicator.get(indicator.id, []))
                    for indicator in indicators
                    if indicator.market_key == market.market_key
                ],
            }
            for market in markets
        ],
        "selection_rule": "one market and one indicator per Bee CFO Assistant; only admin-defined active catalog entries can be selected",
        "default_options": ["GOLD_18K", "USD_FREE", "BTC_USDT"],
    }


async def get_indicator_selection(assistant_id: uuid.UUID) -> dict[str, object] | None:
    async with SessionLocal() as session:
        selection = await session.scalar(
            select(BeeCFOAssistantIndicatorSelection).where(
                BeeCFOAssistantIndicatorSelection.assistant_id == assistant_id
            )
        )
        if selection is None:
            return None
        indicator = await session.scalar(
            select(BeeCFOIndicator).where(BeeCFOIndicator.indicator_key == selection.indicator_key)
        )
        market = await session.scalar(
            select(BeeCFOMarket).where(BeeCFOMarket.market_key == selection.market_key)
        )
    return _selection_payload(selection, indicator=indicator, market=market)


async def indicator_catalog_readiness(assistant_id: uuid.UUID) -> dict[str, object]:
    """Return per-option UAT readiness for the assistant's selected indicator.

    This is deliberately a read-only gate. It never changes a catalog status,
    activates a source, captures a snapshot, or sends a Telegram message.
    """
    selection = await get_indicator_selection(assistant_id)
    selected_key = str(selection.get("indicator_key")) if selection else None
    async with SessionLocal() as session:
        markets = (
            await session.execute(
                select(BeeCFOMarket)
                .where(BeeCFOMarket.status != "disabled")
                .order_by(BeeCFOMarket.display_order, BeeCFOMarket.market_key)
            )
        ).scalars().all()
        indicators = (
            await session.execute(
                select(BeeCFOIndicator)
                .where(BeeCFOIndicator.status != "disabled")
                .order_by(BeeCFOIndicator.display_order, BeeCFOIndicator.indicator_key)
            )
        ).scalars().all()
        sources = (
            await session.execute(
                select(BeeCFOIndicatorSource)
                .where(
                    BeeCFOIndicatorSource.indicator_id.in_([item.id for item in indicators])
                )
                .order_by(BeeCFOIndicatorSource.priority.desc(), BeeCFOIndicatorSource.source_key)
            )
        ).scalars().all() if indicators else []
    markets_by_key = {market.market_key: market for market in markets}
    indicators_by_id = {indicator.id: indicator for indicator in indicators}
    sources_by_indicator: dict[uuid.UUID, list[BeeCFOIndicatorSource]] = {}
    for source in sources:
        sources_by_indicator.setdefault(source.indicator_id, []).append(source)
    approved_source_keys = await _approved_source_keys(
        assistant_id,
        sources=sources,
        indicators_by_id=indicators_by_id,
    )
    options: list[dict[str, object]] = []
    for indicator in indicators:
        market = markets_by_key.get(indicator.market_key)
        if market is None:
            continue
        options.append(
            _catalog_option_readiness(
                market=market,
                indicator=indicator,
                sources=sources_by_indicator.get(indicator.id, []),
                selected=indicator.indicator_key == selected_key,
                approved_source_keys=approved_source_keys,
            )
        )
    selected_option = next((item for item in options if item["selected"]), None)
    return {
        "assistant_id": str(assistant_id),
        "selection": selection,
        "status": "ready" if selected_option and selected_option["ready_for_delivery"] else "blocked",
        "ready_for_selected_assistant": bool(selected_option and selected_option["ready_for_delivery"]),
        "read_only": True,
        "options": options,
        "next_actions": [
            {
                "indicator_key": item["indicator_key"],
                "status": item["status"],
                "blockers": item["blockers"],
            }
            for item in options
            if item["status"] != "ready"
        ],
    }


async def probe_indicator_sources(
    *,
    settings: Settings,
    indicator_key: str | None = None,
) -> dict[str, object]:
    """Probe active direct sources and record health, never snapshots or delivery.

    Draft sources are intentionally excluded. This gives the owner a safe UAT
    action for USD and any future catalog option without silently activating a
    reference or changing the Assistant's selected indicator.
    """
    normalized_key = str(indicator_key).strip().upper() if indicator_key else None
    async with SessionLocal() as session:
        query = select(BeeCFOIndicator).where(BeeCFOIndicator.status == "active")
        if normalized_key:
            query = query.where(BeeCFOIndicator.indicator_key == normalized_key)
        indicators = (await session.execute(query.order_by(BeeCFOIndicator.display_order))).scalars().all()
        source_rows = (
            await session.execute(
                select(BeeCFOIndicatorSource).where(
                    BeeCFOIndicatorSource.indicator_id.in_([item.id for item in indicators]),
                    BeeCFOIndicatorSource.status == "active",
                ).order_by(BeeCFOIndicatorSource.priority.desc(), BeeCFOIndicatorSource.source_key)
            )
        ).scalars().all() if indicators else []
    indicators_by_id = {indicator.id: indicator for indicator in indicators}
    results: list[dict[str, object]] = []
    for source in source_rows:
        indicator = indicators_by_id[source.indicator_id]
        checked_at = datetime.now(timezone.utc)
        try:
            quote = await fetch_price_quote(indicator=indicator, source=source, settings=settings)
            async with SessionLocal() as session:
                row = await session.get(BeeCFOIndicatorSource, source.id)
                if row is not None:
                    row.last_checked_at = quote.observed_at
                    row.last_success_at = quote.observed_at
                    row.last_error = None
                    await session.commit()
            results.append(
                {
                    "indicator_key": indicator.indicator_key,
                    "source_key": source.source_key,
                    "status": "passed",
                    "value": quote.value,
                    "observed_at": quote.observed_at.isoformat(),
                    "provider_signature": quote.raw.get("provider_signature") if isinstance(quote.raw, dict) else None,
                    "provider_fixture_candidate": build_provider_fixture(quote.raw["provider_signature"])
                    if isinstance(quote.raw, dict) and isinstance(quote.raw.get("provider_signature"), dict) else None,
                }
            )
        except Exception as exc:
            async with SessionLocal() as session:
                row = await session.get(BeeCFOIndicatorSource, source.id)
                if row is not None:
                    row.last_checked_at = checked_at
                    row.last_error = str(exc)[:500]
                    await session.commit()
            results.append(
                {
                    "indicator_key": indicator.indicator_key,
                    "source_key": source.source_key,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                    "observed_at": checked_at.isoformat(),
                }
            )
    by_indicator: dict[str, list[dict[str, object]]] = {}
    for item in results:
        by_indicator.setdefault(str(item["indicator_key"]), []).append(item)
    passed_groups = sum(
        1 for items in by_indicator.values() if any(item["status"] == "passed" for item in items)
    )
    if not results or passed_groups == 0:
        probe_status = "failed"
    elif passed_groups == len(by_indicator):
        probe_status = "passed"
    else:
        probe_status = "partial"
    return {
        "status": probe_status,
        "read_only": False,
        "selection_changed": False,
        "snapshots_created": 0,
        "deliveries_created": 0,
        "results": results,
    }


async def set_indicator_selection(
    assistant_id: uuid.UUID,
    *,
    market_key: str,
    indicator_key: str,
    status: str = "active",
    revision: str = "bee-cfo-indicator-1",
) -> dict[str, object]:
    market_key, indicator_key, status = _normalize_selection_keys(
        market_key=market_key,
        indicator_key=indicator_key,
        status=status,
    )
    async with SessionLocal() as session:
        if await session.get(AssistantWorkspace, assistant_id) is None:
            raise KeyError("assistant workspace not found")
        market, indicator = await _load_valid_selection(
            session,
            market_key=market_key,
            indicator_key=indicator_key,
            status=status,
        )
        selection = await session.scalar(
            select(BeeCFOAssistantIndicatorSelection).where(
                BeeCFOAssistantIndicatorSelection.assistant_id == assistant_id
            )
        )
        if selection is None:
            selection = BeeCFOAssistantIndicatorSelection(
                assistant_id=assistant_id,
                market_key=market_key,
                indicator_key=indicator_key,
                status=status,
                revision=revision[:64],
            )
            session.add(selection)
        else:
            selection.market_key = market_key
            selection.indicator_key = indicator_key
            selection.status = status
            selection.revision = revision[:64]
        await session.commit()
        await session.refresh(selection)
    return _selection_payload(selection, indicator=indicator, market=market) or {}


def _normalize_selection_keys(*, market_key: str, indicator_key: str, status: str) -> tuple[str, str, str]:
    normalized_market = str(market_key).strip().upper()
    normalized_indicator = str(indicator_key).strip().upper()
    normalized_status = str(status).strip().lower()
    if normalized_status not in {"draft", "active", "paused"}:
        raise ValueError("indicator selection status is invalid")
    return normalized_market, normalized_indicator, normalized_status


async def _load_valid_selection(
    session,
    *,
    market_key: str,
    indicator_key: str,
    status: str,
) -> tuple[BeeCFOMarket, BeeCFOIndicator]:
    market = await session.scalar(
        select(BeeCFOMarket).where(BeeCFOMarket.market_key == market_key)
    )
    indicator = await session.scalar(
        select(BeeCFOIndicator).where(BeeCFOIndicator.indicator_key == indicator_key)
    )
    if market is None or market.status != "active":
        raise ValueError("market is not an active admin-defined catalog option")
    if indicator is None or indicator.status != "active":
        raise ValueError("indicator is not an active admin-defined catalog option")
    if indicator.market_key != market.market_key:
        raise ValueError("indicator does not belong to the selected market")
    if status == "active":
        active_source = await session.scalar(
            select(BeeCFOIndicatorSource.id).where(
                BeeCFOIndicatorSource.indicator_id == indicator.id,
                BeeCFOIndicatorSource.status == "active",
            ).limit(1)
        )
        if active_source is None:
            raise ValueError("indicator has no owner-approved active price source")
    return market, indicator


async def validate_indicator_selection(
    assistant_id: uuid.UUID,
    *,
    market_key: str,
    indicator_key: str,
    status: str = "active",
) -> None:
    """Validate a selection without writing it, for atomic configuration sync."""
    market_key, indicator_key, status = _normalize_selection_keys(
        market_key=market_key,
        indicator_key=indicator_key,
        status=status,
    )
    async with SessionLocal() as session:
        if await session.get(AssistantWorkspace, assistant_id) is None:
            raise KeyError("assistant workspace not found")
        await _load_valid_selection(
            session,
            market_key=market_key,
            indicator_key=indicator_key,
            status=status,
        )


async def capture_price_snapshot(
    assistant_id: uuid.UUID,
    *,
    settings: Settings,
    observed_at: datetime | None = None,
    comparison_window_hours: int = DEFAULT_PRICE_COMPARISON_WINDOW_HOURS,
    comparison_tolerance_hours: int = DEFAULT_PRICE_COMPARISON_TOLERANCE_HOURS,
    max_relative_spread: float = 0.10,
    require_verifier: bool = False,
) -> dict[str, object]:
    """Fetch and persist the latest quote for the Assistant's one selection."""
    selection_data = await get_indicator_selection(assistant_id)
    if not selection_data or selection_data.get("status") != "active":
        raise IndicatorSelectionRequired("one active market/index selection is required before Telegram delivery")
    async with SessionLocal() as session:
        indicator = await session.scalar(
            select(BeeCFOIndicator).where(BeeCFOIndicator.indicator_key == selection_data["indicator_key"])
        )
        sources = (
            await session.execute(
                select(BeeCFOIndicatorSource).where(
                    BeeCFOIndicatorSource.indicator_id == indicator.id,
                    BeeCFOIndicatorSource.status == "active",
                ).order_by(BeeCFOIndicatorSource.priority.desc(), BeeCFOIndicatorSource.source_key)
            )
        ).scalars().all() if indicator else []
    approved_decisions = await _approved_source_decisions(
        assistant_id,
        sources=sources,
        indicators_by_id={indicator.id: indicator} if indicator else {},
    )
    sources = [source for source in sources if source.source_key in approved_decisions]
    if indicator is None or not sources:
        raise PriceUnavailable("the selected indicator has no active direct price source with an approved, passed owner decision")

    quote: PriceQuote | None = None
    selected_source: BeeCFOIndicatorSource | None = None
    errors: list[str] = []
    attempted_sources: list[str] = []
    for source in sources:
        attempted_sources.append(source.source_key)
        try:
            quote = await fetch_price_quote(indicator=indicator, source=source, settings=settings)
            provider_contract = evaluate_provider_response(
                approved_decisions[source.source_key].get("provider_fixture"),
                quote.raw.get("provider_signature") if isinstance(quote.raw, dict) else None,
                enforced=bool(approved_decisions[source.source_key].get("provider_fixture_enforced", False)),
            )
            if not provider_contract["delivery_permitted"]:
                async with SessionLocal() as session:
                    session.add(BeeCFOGovernanceEvent(
                        assistant_id=assistant_id,
                        category="provider_contract",
                        event_key=f"{indicator.indicator_key}:{source.source_key}",
                        status="failed",
                        payload={
                            "provider_contract": provider_contract,
                            "outbound_message_sent": False,
                            "scheduler_changed": False,
                        },
                    ))
                    await session.commit()
                raise PriceUnavailable("provider contract drift detected; delivery quarantined pending owner revalidation")
            quote.raw["provider_contract"] = provider_contract
            selected_source = source
            async with SessionLocal() as session:
                row = await session.get(BeeCFOIndicatorSource, source.id)
                if row is not None:
                    row.last_checked_at = quote.observed_at
                    row.last_success_at = quote.observed_at
                    row.last_error = None
                    await session.commit()
            break
        except Exception as exc:
            errors.append(f"{source.source_key}: {type(exc).__name__}: {exc}"[:240])
            async with SessionLocal() as session:
                row = await session.get(BeeCFOIndicatorSource, source.id)
                if row is not None:
                    row.last_checked_at = datetime.now(timezone.utc)
                    row.last_error = str(exc)[:500]
                    await session.commit()
    if quote is None:
        raise PriceUnavailable("; ".join(errors)[:1000] or "no approved price source returned a quote")

    verifier: PriceQuote | None = None
    verifier_source: BeeCFOIndicatorSource | None = None
    for candidate in sources:
        if not sources_independent(selected_source, candidate):
            continue
        attempted_sources.append(candidate.source_key)
        try:
            verifier = await fetch_price_quote(indicator=indicator, source=candidate, settings=settings)
            verifier_source = candidate
            break
        except Exception as exc:
            errors.append(f"{candidate.source_key}: verifier {type(exc).__name__}: {exc}"[:240])
    reconciliation = reconcile_quotes(quote, verifier, max_relative_spread=max_relative_spread)
    if require_verifier and verifier is None:
        reconciliation = {**reconciliation, "status": "verifier_required", "delivery_permitted": False}
    if not reconciliation["delivery_permitted"]:
        raise PriceUnavailable("independent price-source reconciliation failed; delivery held for review")

    source_health = build_price_source_health(
        attempted_sources=attempted_sources,
        selected_source=quote.source_key,
        errors=errors,
    )

    as_of = observed_at or quote.observed_at
    comparison_target = as_of - timedelta(hours=int(comparison_window_hours))
    comparison_lower_bound = comparison_target - timedelta(hours=int(comparison_tolerance_hours))
    comparison_upper_bound = comparison_target + timedelta(hours=int(comparison_tolerance_hours))
    async with SessionLocal() as session:
        previous_candidates = (await session.execute(
            select(BeeCFOPriceSnapshot).where(
                BeeCFOPriceSnapshot.assistant_id == assistant_id,
                BeeCFOPriceSnapshot.indicator_key == indicator.indicator_key,
                BeeCFOPriceSnapshot.observed_at >= comparison_lower_bound,
                BeeCFOPriceSnapshot.observed_at <= comparison_upper_bound,
            )
        )).scalars().all()
        # Be tolerant of slight timing drift in scheduled collections while
        # retaining a deterministic preference for an earlier exact-distance
        # match.
        previous = min(
            previous_candidates,
            key=lambda row: (
                abs((row.observed_at - comparison_target).total_seconds()),
                row.observed_at > comparison_target,
                -row.observed_at.timestamp(),
            ),
        ) if previous_candidates else None
        previous_conversion = (previous.raw_quote or {}).get("unit_conversion") if previous is not None else None
        previous_is_trusted = (
            isinstance(previous_conversion, dict)
            and str(previous_conversion.get("target_unit") or "") == str(indicator.quote_unit)
            and bool(previous_conversion.get("source_unit"))
        )
        previous_value = float(previous.value) if previous is not None and previous_is_trusted else None
        try:
            validate_quote_delta(previous_value, quote.value)
        except ValueError as exc:
            raise PriceUnavailable(str(exc)) from exc
        change_value = quote.value - previous_value if previous_value is not None else None
        change_percent = (change_value / previous_value * 100) if previous_value not in (None, 0) else None
        comparison = {
            "status": "available" if previous_value is not None else "unavailable",
            "window_hours": int(comparison_window_hours),
            "target_at": comparison_target.isoformat(),
            "tolerance_hours": int(comparison_tolerance_hours),
            "policy": "nearest_observation_within_tolerance",
            "current_observed_at": as_of.isoformat(),
            "current_value": float(quote.value),
            "baseline_observed_at": previous.observed_at.isoformat() if previous is not None and previous_value is not None else None,
            "baseline_value": previous_value,
            "change_value": change_value,
            "change_percent": change_percent,
            "baseline_age_hours": round((comparison_target - previous.observed_at).total_seconds() / 3600, 3) if previous is not None and previous_value is not None else None,
            "reason": None if previous_value is not None else "no_observation_within_tolerance",
        }
        snapshot = BeeCFOPriceSnapshot(
            assistant_id=assistant_id,
            indicator_key=indicator.indicator_key,
            source_id=selected_source.id,
            observed_at=as_of,
            value=quote.value,
            previous_value=previous_value,
            change_value=change_value,
            change_percent=change_percent,
            quote_unit=indicator.quote_unit,
            currency=indicator.currency,
            raw_quote={**quote.raw, "price_source_health": source_health, "quote_reconciliation": reconciliation},
            provenance={
                "source_key": quote.source_key,
                "source_name": quote.source_name,
                "source_url": quote.source_url,
                "fetched_at": quote.observed_at.isoformat(),
                "reuse_boundary": "bee_cfo.price -> shared public fetch/robots/retry",
                "comparison": comparison,
                "contract_fingerprint": source_contract_fingerprint(indicator=indicator, source=selected_source),
                "quote_reconciliation": reconciliation,
                "verifier_source_key": verifier_source.source_key if verifier_source else None,
            },
        )
        session.add(snapshot)
        await session.commit()
        await session.refresh(snapshot)
    return {
        "id": str(snapshot.id),
        "assistant_id": str(assistant_id),
        "market_key": selection_data["market_key"],
        "market_name": selection_data["market_name"],
        "indicator_key": indicator.indicator_key,
        "indicator_name": indicator.display_name,
        "value": float(snapshot.value),
        "previous_value": float(snapshot.previous_value) if snapshot.previous_value is not None else None,
        "change_value": float(snapshot.change_value) if snapshot.change_value is not None else None,
        "change_percent": float(snapshot.change_percent) if snapshot.change_percent is not None else None,
        "quote_unit": snapshot.quote_unit,
        "currency": snapshot.currency,
        "observed_at": snapshot.observed_at.isoformat(),
        "source_name": quote.source_name,
        "source_url": quote.source_url,
        "price_source_health": source_health,
        "comparison": comparison,
    }
