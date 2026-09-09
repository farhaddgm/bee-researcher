"""Add Bee CFO article-level media forecast and outcome ledgers."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_bee_cfo_media_ledger"
down_revision = "0024_support_ticket_categories"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "bee_cfo_media_forecasts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("assistant_id", UUID, nullable=False),
        sa.Column("report_id", UUID, nullable=False),
        sa.Column("watch_id", UUID, nullable=False),
        sa.Column("forecast_id", sa.String(64), nullable=False),
        sa.Column("article_id", sa.String(64), nullable=False),
        sa.Column("statement_index", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("analyst_name", sa.String(500)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("view", sa.Text, nullable=False),
        sa.Column("snippet", sa.Text),
        sa.Column("stance", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("horizon_key", sa.String(24), nullable=False, server_default="unspecified"),
        sa.Column("horizon_label", sa.String(80), nullable=False, server_default="بدون افق مشخص"),
        sa.Column("horizon_days", sa.SmallInteger),
        sa.Column("horizon_explicit", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("conflict_status", sa.String(32), nullable=False, server_default="clear"),
        sa.Column("conflict_group", sa.String(64)),
        sa.Column("narrative_key", sa.String(64)),
        sa.Column("independence_weight", sa.Float, nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("provenance", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], [f"{SCHEMA}.bee_cfo_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watch_id"], [f"{SCHEMA}.bee_cfo_watches.id"], ondelete="CASCADE"),
        sa.CheckConstraint("stance IN ('up', 'down', 'flat', 'unknown')", name="bee_cfo_media_forecasts_stance"),
        sa.CheckConstraint("status IN ('active', 'expired', 'conflicted', 'syndicated')", name="bee_cfo_media_forecasts_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "forecast_id", name="uq_mi_bee_cfo_media_forecast_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_bee_cfo_media_forecasts_source_horizon",
        "bee_cfo_media_forecasts",
        ["assistant_id", "source_key", "horizon_key", "published_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "bee_cfo_media_forecast_outcomes",
        sa.Column("id", UUID, nullable=False),
        sa.Column("assistant_id", UUID, nullable=False),
        sa.Column("forecast_id", UUID, nullable=False),
        sa.Column("report_id", UUID, nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("analyst_name", sa.String(500)),
        sa.Column("horizon_key", sa.String(24), nullable=False),
        sa.Column("horizon_days", sa.SmallInteger),
        sa.Column("expected_stance", sa.String(16), nullable=False),
        sa.Column("actual_direction", sa.String(16)),
        sa.Column("outcome", sa.String(24), nullable=False, server_default="not_evaluable"),
        sa.Column("direction_hit", sa.Boolean),
        sa.Column("brier_score", sa.Float),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["forecast_id"], [f"{SCHEMA}.bee_cfo_media_forecasts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], [f"{SCHEMA}.bee_cfo_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("forecast_id", name="uq_mi_bee_cfo_media_outcome_forecast"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_bee_cfo_media_outcomes_source_horizon",
        "bee_cfo_media_forecast_outcomes",
        ["assistant_id", "source_key", "horizon_key", "evaluated_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_mi_bee_cfo_media_outcomes_source_horizon", table_name="bee_cfo_media_forecast_outcomes", schema=SCHEMA)
    op.drop_table("bee_cfo_media_forecast_outcomes", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_media_forecasts_source_horizon", table_name="bee_cfo_media_forecasts", schema=SCHEMA)
    op.drop_table("bee_cfo_media_forecasts", schema=SCHEMA)
