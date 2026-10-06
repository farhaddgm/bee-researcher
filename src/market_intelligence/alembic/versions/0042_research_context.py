"""Explicit approved business contexts, previews and evidence-backed assessments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0042_research_context"
down_revision = "0041_contenter_business"
branch_labels = None
depends_on = None


def upgrade():
    schema = "market_intelligence"
    project_fk = lambda: sa.ForeignKeyConstraint(["assistant_id"], [f"{schema}.assistant_workspaces.id"], ondelete="CASCADE")
    op.create_table("project_research_contexts",
        sa.Column("assistant_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("rollout", sa.String(8), nullable=False), sa.Column("local_business_id", sa.SmallInteger()),
        sa.Column("external_business_id", sa.String(128)), sa.Column("link_generation", pg.UUID(as_uuid=True)),
        sa.Column("snapshot_version", sa.Integer()), sa.Column("business_threshold", sa.Float(), nullable=False),
        sa.Column("brief", pg.JSONB(), nullable=False), sa.Column("semantic_hash", sa.String(64), nullable=False),
        sa.Column("style", pg.JSONB(), nullable=False), sa.Column("previous_live", pg.JSONB()), sa.Column("activated_by", pg.UUID(as_uuid=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('none','local','contenter')", name="research_context_source"),
        sa.CheckConstraint("mode IN ('topics','contextual','focused')", name="research_context_mode"),
        sa.CheckConstraint("rollout IN ('shadow','live')", name="research_context_rollout"),
        sa.CheckConstraint("business_threshold BETWEEN 0 AND 1", name="research_context_threshold"), project_fk(), schema=schema)
    op.create_table("research_context_previews",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True), sa.Column("assistant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), nullable=False), sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False), sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), project_fk(), schema=schema)
    op.create_index("ix_mi_research_previews_expiry", "research_context_previews", ["expires_at"], schema=schema)
    op.create_table("news_business_assessments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True), sa.Column("assistant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", pg.UUID(as_uuid=True), nullable=False), sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), project_fk(),
        sa.ForeignKeyConstraint(["article_id"], [f"{schema}.normalized_articles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("assistant_id", "article_id", "context_hash", "content_hash", name="uq_mi_business_assessment"), schema=schema)
    op.add_column("article_analyses", sa.Column("research_provenance", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), schema=schema)


def downgrade():
    raise RuntimeError("Keep additive context history; roll back application code instead of dropping audit data")
