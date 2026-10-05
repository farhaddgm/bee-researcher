"""Scope weekly report identity to its workspace; retain all existing rows."""
from alembic import op
import sqlalchemy as sa

revision = "0040_workspace_reports"
down_revision = "0039_workspace_ingestion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_mi_weekly_reports_assistant_period", "weekly_reports", ["assistant_id", "period_start", "period_end"], schema="market_intelligence")
    op.drop_constraint("uq_mi_weekly_reports_period", "weekly_reports", type_="unique", schema="market_intelligence")


def downgrade():
    duplicate = op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM market_intelligence.weekly_reports GROUP BY period_start, period_end HAVING count(*) > 1)")).scalar()
    if duplicate:
        raise RuntimeError("Cannot restore global report identity without data loss; roll forward")
    op.create_unique_constraint("uq_mi_weekly_reports_period", "weekly_reports", ["period_start", "period_end"], schema="market_intelligence")
    op.drop_constraint("uq_mi_weekly_reports_assistant_period", "weekly_reports", type_="unique", schema="market_intelligence")
