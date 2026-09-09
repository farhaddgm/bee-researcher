"""Scope media and topic keys to their assistant workspace."""

from alembic import op
import sqlalchemy as sa


SCHEMA = "market_intelligence"
revision = "0011_workspace_catalog_keys"
down_revision = "0010_multi_business_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(f"ALTER TABLE {SCHEMA}.sources DROP CONSTRAINT IF EXISTS uq_mi_sources_source_key"))
    op.execute(sa.text(f"ALTER TABLE {SCHEMA}.topics DROP CONSTRAINT IF EXISTS uq_mi_topics_topic_key"))
    op.create_unique_constraint(
        "uq_mi_sources_assistant_source_key", "sources", ["assistant_id", "source_key"], schema=SCHEMA
    )
    op.create_unique_constraint(
        "uq_mi_topics_assistant_topic_key", "topics", ["assistant_id", "topic_key"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_constraint("uq_mi_sources_assistant_source_key", "sources", schema=SCHEMA, type_="unique")
    op.drop_constraint("uq_mi_topics_assistant_topic_key", "topics", schema=SCHEMA, type_="unique")
    op.create_unique_constraint("uq_mi_sources_source_key", "sources", ["source_key"], schema=SCHEMA)
    op.create_unique_constraint("uq_mi_topics_topic_key", "topics", ["topic_key"], schema=SCHEMA)
