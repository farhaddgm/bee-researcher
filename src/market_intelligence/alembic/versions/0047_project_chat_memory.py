"""Explicitly saved reader conversations, scoped to user and project."""
from alembic import op
import sqlalchemy as sa

revision = "0047_project_chat_memory"
down_revision = "0046_report_portal"
branch_labels = depends_on = None
S = "market_intelligence"


def upgrade():
    op.add_column("news_chat_conversations", sa.Column("saved_at", sa.DateTime(timezone=True)), schema=S)
    op.create_index("ix_news_chat_project_memory", "news_chat_conversations",
                    ["user_id", "assistant_id", "saved_at", "id"], schema=S,
                    postgresql_where=sa.text("saved_at IS NOT NULL AND deleted_at IS NULL"))


def downgrade():
    raise RuntimeError("Preserve saved project conversations; roll back the application without dropping memory")
