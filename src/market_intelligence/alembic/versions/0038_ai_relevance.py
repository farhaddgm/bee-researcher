"""Auditable preselection relevance, without reinterpreting old lexical scores."""
from alembic import op
import sqlalchemy as sa

revision = "0038_ai_relevance"
down_revision = "0037_owner_email_google_login"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("article_topics", sa.Column("ai_score", sa.Float(), nullable=True), schema="market_intelligence")
    op.add_column("article_topics", sa.Column("context_hash", sa.String(64), nullable=True), schema="market_intelligence")
    op.create_check_constraint("article_topics_ai_score", "article_topics", "ai_score IS NULL OR ai_score BETWEEN 0 AND 1", schema="market_intelligence")


def downgrade():
    op.drop_constraint("article_topics_ai_score", "article_topics", type_="check", schema="market_intelligence")
    op.drop_column("article_topics", "context_hash", schema="market_intelligence")
    op.drop_column("article_topics", "ai_score", schema="market_intelligence")
