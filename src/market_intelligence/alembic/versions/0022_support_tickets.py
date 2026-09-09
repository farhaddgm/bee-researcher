"""Add the owner-routed back-office support inbox."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_support_tickets"
down_revision = "0021_bee_cfo_media_delivery"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    op.create_table(
        "support_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("owner_reply", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_user', 'resolved', 'closed')",
            name="support_tickets_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="support_tickets_priority",
        ),
        sa.ForeignKeyConstraint(["created_by"], [f"{SCHEMA}.admin_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_support_tickets_status_created",
        "support_tickets",
        ["status", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_support_tickets_creator_created",
        "support_tickets",
        ["created_by", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_mi_support_tickets_creator_created", table_name="support_tickets", schema=SCHEMA)
    op.drop_index("ix_mi_support_tickets_status_created", table_name="support_tickets", schema=SCHEMA)
    op.drop_table("support_tickets", schema=SCHEMA)
