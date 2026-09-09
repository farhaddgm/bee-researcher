"""Add explicit display ordering for media and topics."""

from alembic import op
import sqlalchemy as sa


SCHEMA = "market_intelligence"
revision = "0009_backoffice_ordering"
down_revision = "0008_default_workspace_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1000"),
        schema=SCHEMA,
    )
    op.add_column(
        "topics",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1000"),
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            f"""
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY assistant_id ORDER BY priority DESC, source_key) * 10 AS position
                FROM {SCHEMA}.sources
            )
            UPDATE {SCHEMA}.sources AS source
            SET display_order = ranked.position
            FROM ranked
            WHERE source.id = ranked.id
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY assistant_id ORDER BY importance DESC, topic_key) * 10 AS position
                FROM {SCHEMA}.topics
            )
            UPDATE {SCHEMA}.topics AS topic
            SET display_order = ranked.position
            FROM ranked
            WHERE topic.id = ranked.id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("topics", "display_order", schema=SCHEMA)
    op.drop_column("sources", "display_order", schema=SCHEMA)
