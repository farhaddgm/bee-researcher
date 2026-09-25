from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.models import Base


@dataclass(frozen=True, slots=True)
class InfrastructureDecision:
    status: str
    reuse: tuple[str, ...]
    isolate: tuple[str, ...]
    forbidden_dependencies: tuple[str, ...]
    ui_scope: str
    separability: str


def run_infrastructure_audit() -> dict[str, Any]:
    """Return a deterministic reuse decision before any shared adapter runs."""
    table_names = set(Base.metadata.tables)
    bee_tables = sorted(name for name in table_names if name.startswith("market_intelligence.bee_cfo_"))
    required_tables = {
        "market_intelligence.bee_cfo_profiles",
        "market_intelligence.bee_cfo_sources",
        "market_intelligence.bee_cfo_watches",
        "market_intelligence.bee_cfo_snapshots",
        "market_intelligence.bee_cfo_reports",
        "market_intelligence.bee_cfo_forecasts",
        "market_intelligence.bee_cfo_forecast_evaluations",
        "market_intelligence.bee_cfo_factor_attributions",
        "market_intelligence.bee_cfo_price_forecasts",
        "market_intelligence.bee_cfo_price_forecast_evaluations",
        "market_intelligence.bee_cfo_alerts",
        "market_intelligence.bee_cfo_infrastructure_audits",
    }
    decision = InfrastructureDecision(
        status="passed" if required_tables.issubset(table_names) else "blocked",
        reuse=(
            "app.fetchers: public URL validation, robots, retries and bounded fetch",
            "app.article_extraction: canonical extraction and quality/provenance metadata",
            "market_intelligence Redis/PostgreSQL physical services only",
        ),
        isolate=(
            "bee_cfo_* persistence tables",
            "assistant_id workspace boundary",
            "Bee CFO output/scenario/forecast contracts",
            "Bee CFO scheduler and report idempotency keys",
        ),
        forbidden_dependencies=(
            "app.consultant_bee",
            "research_* tables or queues",
            "user holdings, goals, risk profile or personalized recommendations in phase one",
            "back-office UI/UX changes",
        ),
        ui_scope="no_backoffice_ui",
        separability="adapter_boundary_ready",
    )
    return {
        "status": decision.status,
        "decision": asdict(decision),
        "isolation_contract": {
            "tables": bee_tables,
            "queue_prefix": "market-intelligence:bee_cfo_",
            "environment_prefix": "MARKET_INTELLIGENCE_",
            "shared_runtime_state": False,
        },
    }
