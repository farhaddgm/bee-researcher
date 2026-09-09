"""Add immutable threaded support-ticket messages and the answered state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0035_support_ticket_messages"
down_revision = "0034_mfa_sessions"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    # Depending on the Alembic naming convention used by the installation,
    # the original check is either the explicit name or the generated
    # ``ck_mi_*`` name. Drop both variants so the migration is idempotent on
    # existing databases as well as clean installations.
    op.execute(
        "ALTER TABLE market_intelligence.support_tickets "
        "DROP CONSTRAINT IF EXISTS support_tickets_status"
    )
    op.execute(
        "ALTER TABLE market_intelligence.support_tickets "
        "DROP CONSTRAINT IF EXISTS ck_mi_support_tickets_status"
    )
    op.create_check_constraint(
        "support_tickets_status",
        "support_tickets",
        "status IN ('open', 'in_progress', 'waiting_user', 'answered', 'resolved', 'closed')",
        schema=SCHEMA,
    )
    op.create_table(
        "support_ticket_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("author_role", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "author_role IN ('owner', 'requester')",
            name="support_ticket_messages_author_role",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], [f"{SCHEMA}.support_tickets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], [f"{SCHEMA}.admin_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_support_ticket_messages_ticket_created",
        "support_ticket_messages",
        ["ticket_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mi_support_ticket_messages_ticket_created",
        table_name="support_ticket_messages",
        schema=SCHEMA,
    )
    op.drop_table("support_ticket_messages", schema=SCHEMA)
    op.execute(
        "ALTER TABLE market_intelligence.support_tickets "
        "DROP CONSTRAINT IF EXISTS support_tickets_status"
    )
    op.execute(
        "ALTER TABLE market_intelligence.support_tickets "
        "DROP CONSTRAINT IF EXISTS ck_mi_support_tickets_status"
    )
    op.create_check_constraint(
        "support_tickets_status",
        "support_tickets",
        "status IN ('open', 'in_progress', 'waiting_user', 'resolved', 'closed')",
        schema=SCHEMA,
    )
