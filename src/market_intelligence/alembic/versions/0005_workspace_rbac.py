"""Versioned assistant templates and explicit workspace membership."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

SCHEMA = "market_intelligence"
revision = "0005_workspace_rbac"
down_revision = "0004_backoffice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("assistant_id", "user_id", name="uq_mi_assistant_members_assistant_user"),
        sa.CheckConstraint("role IN ('admin','assistant_admin','editor','analyst','viewer')", name="ck_mi_assistant_members_role"),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_assistant_members_user", "assistant_members", ["user_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_mi_assistant_members_user", table_name="assistant_members", schema=SCHEMA)
    op.drop_table("assistant_members", schema=SCHEMA)
