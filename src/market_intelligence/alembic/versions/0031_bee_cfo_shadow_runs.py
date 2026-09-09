"""Add an isolated no-send shadow-run category to Bee CFO's audit ledger."""

from alembic import op


revision = "0031_bee_cfo_shadow_runs"
down_revision = "0030_bee_cfo_quality_gates"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_mi_bee_cfo_governance_events_category"),
        "bee_cfo_governance_events",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "bee_cfo_governance_events_category",
        "bee_cfo_governance_events",
        "category IN ('pilot_run', 'source_decision', 'source_revalidation', 'canary', 'shadow_run', 'attention', 'why_changed', 'privacy_boundary')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_mi_bee_cfo_governance_events_category"),
        "bee_cfo_governance_events",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "bee_cfo_governance_events_category",
        "bee_cfo_governance_events",
        "category IN ('pilot_run', 'source_decision', 'source_revalidation', 'canary', 'attention', 'why_changed', 'privacy_boundary')",
        schema=SCHEMA,
    )
