"""Deduplicate collected content inside, not across, assistant workspaces."""

from alembic import op
import sqlalchemy as sa

revision = "0039_workspace_ingestion"
down_revision = "0038_ai_relevance"
branch_labels = None
depends_on = None


def upgrade():
    # Build the replacement before removing the stronger old constraint.
    # Existing rows are already globally unique: no data rewrite is needed.
    op.create_unique_constraint(
        "uq_mi_source_items_assistant_fingerprint", "source_items",
        ["assistant_id", "fingerprint"], schema="market_intelligence",
    )
    op.drop_constraint("uq_mi_source_items_fingerprint", "source_items", type_="unique", schema="market_intelligence")
    # Old probes may already have acknowledged content that was never stored.
    # Clear only operational conditional-cache validators once. Deduplication
    # prevents repeat rows when the next scheduled run reads the full feed.
    op.execute(sa.text("UPDATE market_intelligence.sources SET etag=NULL, last_modified=NULL WHERE etag IS NOT NULL OR last_modified IS NOT NULL"))


def downgrade():
    # A downgrade must never delete another workspace's collected articles.
    duplicates = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM market_intelligence.source_items "
        "GROUP BY fingerprint HAVING count(*) > 1)"
    )).scalar()
    if duplicates:
        raise RuntimeError("Cannot restore global deduplication without data loss; retain this migration and roll forward")
    op.create_unique_constraint("uq_mi_source_items_fingerprint", "source_items", ["fingerprint"], schema="market_intelligence")
    op.drop_constraint("uq_mi_source_items_assistant_fingerprint", "source_items", type_="unique", schema="market_intelligence")
