"""Add the isolated Bee CFO Telegram delivery ledger."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_bee_cfo_telegram_delivery"
down_revision = "0016_bee_cfo_market_analyst"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "bee_cfo_deliveries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "assistant_id",
            UUID,
            sa.ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "report_id",
            UUID,
            sa.ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("destination_id", sa.String(64), nullable=False),
        sa.Column("destination_type", sa.String(24), nullable=False, server_default="telegram"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("message_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("renderer_revision", sa.String(64), nullable=False, server_default="bee-cfo-telegram-1"),
        sa.Column("error_message", sa.Text),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name=op.f("ck_mi_bee_cfo_deliveries_status"),
        ),
        sa.UniqueConstraint(
            "assistant_id", "report_id", "destination_id",
            name="uq_mi_bee_cfo_deliveries_report_destination",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_bee_cfo_deliveries_status_created",
        "bee_cfo_deliveries",
        ["assistant_id", "status", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_mi_bee_cfo_deliveries_status_created", table_name="bee_cfo_deliveries", schema=SCHEMA)
    op.drop_table("bee_cfo_deliveries", schema=SCHEMA)
