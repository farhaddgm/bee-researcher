"""Add an explicit workspace owner to operational records.

The legacy single-workspace data is assigned to the stable default workspace;
new writes receive the same default at the database boundary until a caller
selects another workspace explicitly.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

SCHEMA = "market_intelligence"
revision = "0006_assistant_data_scope"
down_revision = "0005_workspace_rbac"
branch_labels = None
depends_on = None
DEFAULT_ASSISTANT = "00000000-0000-0000-0000-000000000001"

TABLES = (
    "job_runs", "sources", "source_items", "source_fetch_runs", "business_profiles",
    "topics", "normalized_articles", "article_topics", "event_clusters", "cluster_members",
    "article_analyses", "publications", "feedback", "weekly_reports",
)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.assistant_workspaces "
            "(id, slug, name, description, business_name, status, config) "
            f"VALUES ('{DEFAULT_ASSISTANT}'::uuid, 'default', 'Default workspace', 'Legacy single-workspace data', 'داتین', 'active', '{{}}'::jsonb) "
            "ON CONFLICT (slug) DO NOTHING"
        )
    )
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "assistant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
                nullable=False,
                server_default=sa.text(f"'{DEFAULT_ASSISTANT}'::uuid"),
            ),
            schema=SCHEMA,
        )
        op.create_index(f"ix_mi_{table}_assistant_id", table, ["assistant_id"], schema=SCHEMA)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_mi_{table}_assistant_id", table_name=table, schema=SCHEMA)
        op.drop_column(table, "assistant_id", schema=SCHEMA)
