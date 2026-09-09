"""Backoffice workspace, admin session and audit foundation.

Revision ID: 0004_backoffice
Revises: 0003_full_pipeline
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

SCHEMA = "market_intelligence"
revision = "0004_backoffice"
down_revision = "0003_full_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("business_name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("slug", name="uq_mi_assistant_workspaces_slug"),
        sa.CheckConstraint("status IN ('draft','testing','active','paused','archived')", name="ck_mi_assistant_workspaces_status"),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_assistant_workspaces_status", "assistant_workspaces", ["status"], schema=SCHEMA)
    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="admin"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("username", name="uq_mi_admin_users_username"),
        schema=SCHEMA,
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_admin_sessions_expires", "admin_sessions", ["expires_at"], schema=SCHEMA)
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="SET NULL")),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False, server_default="success"),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_admin_audit_logs_created", "admin_audit_logs", ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_mi_admin_audit_logs_created", table_name="admin_audit_logs", schema=SCHEMA)
    op.drop_table("admin_audit_logs", schema=SCHEMA)
    op.drop_index("ix_mi_admin_sessions_expires", table_name="admin_sessions", schema=SCHEMA)
    op.drop_table("admin_sessions", schema=SCHEMA)
    op.drop_table("admin_users", schema=SCHEMA)
    op.drop_index("ix_mi_assistant_workspaces_status", table_name="assistant_workspaces", schema=SCHEMA)
    op.drop_table("assistant_workspaces", schema=SCHEMA)
