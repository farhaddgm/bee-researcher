"""Add Bee CFO post-phase-one governance evidence ledger."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0029_bee_cfo_governance"
down_revision = "0028_bee_cfo_price_deltas"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "bee_cfo_governance_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("assistant_id", UUID, nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "category IN ('pilot_run', 'source_decision', 'attention', 'why_changed', 'privacy_boundary')",
            name="bee_cfo_governance_events_category",
        ),
        sa.CheckConstraint(
            "status IN ('recorded', 'passed', 'failed', 'draft', 'approved', 'rejected', 'expired', 'eligible', 'suppressed', 'served')",
            name="bee_cfo_governance_events_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_bee_cfo_governance_events_assistant_category_created",
        "bee_cfo_governance_events",
        ["assistant_id", "category", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_bee_cfo_governance_events_lookup",
        "bee_cfo_governance_events",
        ["assistant_id", "category", "event_key", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_mi_bee_cfo_governance_events_lookup", table_name="bee_cfo_governance_events", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_governance_events_assistant_category_created", table_name="bee_cfo_governance_events", schema=SCHEMA)
    op.drop_table("bee_cfo_governance_events", schema=SCHEMA)
