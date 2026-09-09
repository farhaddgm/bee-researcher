"""Repair legacy pipeline rows and preserve workspace ownership on inserts."""

from alembic import op
import sqlalchemy as sa


SCHEMA = "market_intelligence"
revision = "0012_pipeline_scope"
down_revision = "0011_workspace_catalog_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older pipeline inserts relied on the database default assistant id for
    # derived rows. Reattach those rows to the workspace of their source item
    # or parent article before the corrected insert path is used.
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.normalized_articles AS article
        SET assistant_id = item.assistant_id
        FROM {SCHEMA}.source_items AS item
        WHERE article.source_item_id = item.id
          AND article.assistant_id <> item.assistant_id
    """))
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.article_topics AS scored
        SET assistant_id = article.assistant_id
        FROM {SCHEMA}.normalized_articles AS article
        WHERE scored.article_id = article.id
          AND scored.assistant_id <> article.assistant_id
    """))
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.event_clusters AS cluster
        SET assistant_id = article.assistant_id
        FROM {SCHEMA}.normalized_articles AS article
        WHERE cluster.representative_article_id = article.id
          AND cluster.assistant_id <> article.assistant_id
    """))
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.cluster_members AS member
        SET assistant_id = article.assistant_id
        FROM {SCHEMA}.normalized_articles AS article
        WHERE member.article_id = article.id
          AND member.assistant_id <> article.assistant_id
    """))
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.article_analyses AS analysis
        SET assistant_id = article.assistant_id
        FROM {SCHEMA}.normalized_articles AS article
        WHERE analysis.article_id = article.id
          AND analysis.assistant_id <> article.assistant_id
    """))
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.publications AS publication
        SET assistant_id = analysis.assistant_id
        FROM {SCHEMA}.article_analyses AS analysis
        WHERE publication.analysis_id = analysis.id
          AND publication.assistant_id <> analysis.assistant_id
    """))
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.feedback AS feedback
        SET assistant_id = analysis.assistant_id
        FROM {SCHEMA}.article_analyses AS analysis
        WHERE feedback.analysis_id = analysis.id
          AND feedback.assistant_id <> analysis.assistant_id
    """))


def downgrade() -> None:
    # Ownership repair is intentionally not reversible: reverting would
    # recreate the cross-workspace data leak this migration fixes.
    pass
