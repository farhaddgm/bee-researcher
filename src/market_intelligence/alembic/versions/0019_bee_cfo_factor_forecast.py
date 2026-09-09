"""Add explainable factors, numeric forecasts and forecast evaluation."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_bee_cfo_factor_forecast"
down_revision = "0018_bee_cfo_indicator_catalog"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
NOW = sa.text("CURRENT_TIMESTAMP")
EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_ARRAY = sa.text("'[]'::jsonb")
ASSISTANT_FK = f"{SCHEMA}.assistant_workspaces.id"


def upgrade() -> None:
    op.create_table(
        "bee_cfo_factor_attributions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assistant_id", UUID, sa.ForeignKey(ASSISTANT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_snapshots.id", ondelete="SET NULL")),
        sa.Column("watch_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("factor_key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("strength", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("score", sa.Float),
        sa.Column("evidence_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("source_keys", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("evidence", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("horizon", sa.String(80), nullable=False, server_default="نامشخص"),
        sa.Column("invalidation", sa.Text, nullable=False, server_default=""),
        sa.Column("attribution_kind", sa.String(32), nullable=False, server_default="co_movement"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("model_revision", sa.String(64), nullable=False, server_default="bee-cfo-factors-1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("report_id", "factor_key", name="uq_mi_bee_cfo_factor_attributions_report_factor"),
        sa.CheckConstraint("direction IN ('up', 'down', 'flat', 'unknown')", name=op.f("ck_mi_bee_cfo_factor_attributions_direction")),
        sa.CheckConstraint("strength IN ('strong', 'medium', 'weak', 'unknown')", name=op.f("ck_mi_bee_cfo_factor_attributions_strength")),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 0 AND 1", name=op.f("ck_mi_bee_cfo_factor_attributions_score")),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_mi_bee_cfo_factor_attributions_confidence")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_factor_attributions_assistant_report", "bee_cfo_factor_attributions", ["assistant_id", "report_id"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_price_forecasts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assistant_id", UUID, sa.ForeignKey(ASSISTANT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("watch_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("indicator_key", sa.String(64), nullable=False),
        sa.Column("horizon_days", sa.SmallInteger, nullable=False),
        sa.Column("forecast_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_cutoff", sa.DateTime(timezone=True)),
        sa.Column("baseline_value", sa.Numeric(24, 8)),
        sa.Column("point_value", sa.Numeric(24, 8)),
        sa.Column("lower_value", sa.Numeric(24, 8)),
        sa.Column("upper_value", sa.Numeric(24, 8)),
        sa.Column("probability_up", sa.Float, nullable=False),
        sa.Column("probability_down", sa.Float, nullable=False),
        sa.Column("probability_flat", sa.Float, nullable=False),
        sa.Column("method", sa.String(80), nullable=False),
        sa.Column("model_revision", sa.String(64), nullable=False),
        sa.Column("sample_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("quality_status", sa.String(24), nullable=False, server_default="no_call"),
        sa.Column("components", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("metrics", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("report_id", "horizon_days", name="uq_mi_bee_cfo_price_forecasts_report_horizon"),
        sa.CheckConstraint("horizon_days IN (1, 7, 30)", name=op.f("ck_mi_bee_cfo_price_forecasts_horizon")),
        sa.CheckConstraint("probability_up BETWEEN 0 AND 1 AND probability_down BETWEEN 0 AND 1 AND probability_flat BETWEEN 0 AND 1", name=op.f("ck_mi_bee_cfo_price_forecasts_probabilities")),
        sa.CheckConstraint("quality_status IN ('available', 'limited', 'no_call')", name=op.f("ck_mi_bee_cfo_price_forecasts_quality")),
        sa.CheckConstraint("status IN ('open', 'evaluated', 'void')", name=op.f("ck_mi_bee_cfo_price_forecasts_status")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_price_forecasts_due", "bee_cfo_price_forecasts", ["assistant_id", "forecast_for", "status"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_price_forecast_evaluations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assistant_id", UUID, sa.ForeignKey(ASSISTANT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("forecast_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_price_forecasts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("absolute_error", sa.Numeric(24, 8), nullable=False),
        sa.Column("percentage_error", sa.Numeric(18, 8)),
        sa.Column("direction_outcome", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("direction_hit", sa.Boolean),
        sa.Column("interval_covered", sa.Boolean),
        sa.Column("brier_score", sa.Float),
        sa.Column("actual_state", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("lesson", sa.Text, nullable=False, server_default=""),
        sa.Column("provenance", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.UniqueConstraint("forecast_id", name="uq_mi_bee_cfo_price_forecast_evaluations_forecast"),
        sa.CheckConstraint("percentage_error IS NULL OR percentage_error >= 0", name=op.f("ck_mi_bee_cfo_price_forecast_evaluations_percentage_error")),
        sa.CheckConstraint("brier_score IS NULL OR brier_score BETWEEN 0 AND 1", name=op.f("ck_mi_bee_cfo_price_forecast_evaluations_brier")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_price_forecast_evaluations_assistant_date", "bee_cfo_price_forecast_evaluations", ["assistant_id", "evaluated_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_mi_bee_cfo_price_forecast_evaluations_assistant_date", table_name="bee_cfo_price_forecast_evaluations", schema=SCHEMA)
    op.drop_table("bee_cfo_price_forecast_evaluations", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_price_forecasts_due", table_name="bee_cfo_price_forecasts", schema=SCHEMA)
    op.drop_table("bee_cfo_price_forecasts", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_factor_attributions_assistant_report", table_name="bee_cfo_factor_attributions", schema=SCHEMA)
    op.drop_table("bee_cfo_factor_attributions", schema=SCHEMA)
