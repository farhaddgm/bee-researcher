"""Add external display-only business links; do not modify local AI profiles."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0041_contenter_business"
down_revision = "0040_workspace_reports"
branch_labels = None
depends_on = None


def upgrade():
    schema = "market_intelligence"
    op.create_table("contenter_business_links",
        sa.Column("assistant_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_business_id", sa.String(128), nullable=False),
        sa.Column("business_name", sa.String(160), nullable=False),
        sa.Column("generation", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(48)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{schema}.assistant_workspaces.id"], ondelete="CASCADE"), schema=schema)
    op.create_table("contenter_business_snapshots",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("assistant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("external_business_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{schema}.assistant_workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("assistant_id", "version", name="uq_mi_contenter_snapshot_version"), schema=schema)
    op.create_index("ix_mi_contenter_snapshots_assistant", "contenter_business_snapshots", ["assistant_id", "external_business_id"], schema=schema)


def downgrade():
    # Explicit downgrade is destructive; code rollback can leave these additive tables in place.
    raise RuntimeError("Preserve external profile history; roll back code without dropping these tables")
