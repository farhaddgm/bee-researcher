"""Add Bee CFO media weighting scenario audit trail."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_bee_cfo_weight_audit"
down_revision = "0025_bee_cfo_media_ledger"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "bee_cfo_media_weighting_audits",
        sa.Column("id", UUID, nullable=False),
        sa.Column("assistant_id", UUID, nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("weighting", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint("mode IN ('user_scenario', 'reset')", name="bee_cfo_media_weighting_audits_mode"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_bee_cfo_media_weighting_audits_assistant_created",
        "bee_cfo_media_weighting_audits",
        ["assistant_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mi_bee_cfo_media_weighting_audits_assistant_created",
        table_name="bee_cfo_media_weighting_audits",
        schema=SCHEMA,
    )
    op.drop_table("bee_cfo_media_weighting_audits", schema=SCHEMA)
