"""Add Bee CFO provider-contract and capacity audit categories."""

from alembic import op
import sqlalchemy as sa


revision = "0032_bee_cfo_provider_capacity_controls"
down_revision = "0031_bee_cfo_shadow_runs"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    # Earlier Bee CFO revisions fit the legacy 32-character Alembic metadata
    # column. This revision id does not; widen only migration metadata before
    # Alembic records the new head.
    op.alter_column(
        "alembic_version",
        "version_num",
        schema=SCHEMA,
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.drop_constraint(op.f("ck_mi_bee_cfo_governance_events_category"), "bee_cfo_governance_events", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "bee_cfo_governance_events_category",
        "bee_cfo_governance_events",
        "category IN ('pilot_run', 'source_decision', 'source_revalidation', 'provider_contract', 'capacity', 'canary', 'shadow_run', 'attention', 'why_changed', 'privacy_boundary')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_mi_bee_cfo_governance_events_category"), "bee_cfo_governance_events", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "bee_cfo_governance_events_category",
        "category IN ('pilot_run', 'source_decision', 'source_revalidation', 'canary', 'shadow_run', 'attention', 'why_changed', 'privacy_boundary')",
        schema=SCHEMA,
    )
    op.alter_column(
        "alembic_version",
        "version_num",
        schema=SCHEMA,
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
