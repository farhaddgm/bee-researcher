"""Add isolated Bee CFO benchmark capability ledgers."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_bee_cfo_benchmark"
down_revision = "0022_support_tickets"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "bee_cfo_alert_rules",
        sa.Column("id", UUID, nullable=False), sa.Column("assistant_id", UUID, nullable=False), sa.Column("watch_id", UUID, nullable=False),
        sa.Column("rule_key", sa.String(64), nullable=False), sa.Column("kind", sa.String(40), nullable=False), sa.Column("threshold", sa.Float),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("revision", sa.String(64), nullable=False, server_default="bee-cfo-alerts-1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watch_id"], [f"{SCHEMA}.bee_cfo_watches.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('draft', 'active', 'paused')", name="bee_cfo_alert_rules_status"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("assistant_id", "watch_id", "rule_key", name="uq_mi_bee_cfo_alert_rules_key"), schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_alert_rules_active", "bee_cfo_alert_rules", ["assistant_id", "status"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_market_events",
        sa.Column("id", UUID, nullable=False), sa.Column("assistant_id", UUID, nullable=False), sa.Column("watch_id", UUID, nullable=False), sa.Column("report_id", UUID),
        sa.Column("event_key", sa.String(64), nullable=False), sa.Column("event_type", sa.String(40), nullable=False), sa.Column("title", sa.Text, nullable=False),
        sa.Column("expected", sa.Text), sa.Column("actual", sa.Text), sa.Column("previous", sa.Text), sa.Column("source_keys", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_urls", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("novelty_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="observed"), sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["watch_id"], [f"{SCHEMA}.bee_cfo_watches.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["report_id"], [f"{SCHEMA}.bee_cfo_reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("assistant_id", "event_key", name="uq_mi_bee_cfo_market_events_key"), schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_market_events_watch_time", "bee_cfo_market_events", ["assistant_id", "watch_id", "published_at"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_coverage_snapshots",
        sa.Column("id", UUID, nullable=False), sa.Column("assistant_id", UUID, nullable=False), sa.Column("report_id", UUID, nullable=False), sa.Column("indicator_key", sa.String(64)),
        sa.Column("score", sa.Float, nullable=False, server_default="0"), sa.Column("status", sa.String(24), nullable=False, server_default="insufficient"), sa.Column("components", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("missing", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["report_id"], [f"{SCHEMA}.bee_cfo_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("report_id", name="uq_mi_bee_cfo_coverage_snapshots_report"), schema=SCHEMA,
    )

    op.create_table(
        "bee_cfo_media_forecast_evaluations",
        sa.Column("id", UUID, nullable=False), sa.Column("assistant_id", UUID, nullable=False), sa.Column("report_id", UUID, nullable=False), sa.Column("source_key", sa.String(64), nullable=False), sa.Column("horizon_days", sa.SmallInteger, nullable=False),
        sa.Column("expected_stance", sa.String(16), nullable=False), sa.Column("actual_direction", sa.String(16)), sa.Column("outcome", sa.String(24), nullable=False, server_default="not_evaluable"), sa.Column("direction_hit", sa.Boolean), sa.Column("brier_score", sa.Float), sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("provenance", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["assistant_id"], [f"{SCHEMA}.assistant_workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["report_id"], [f"{SCHEMA}.bee_cfo_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("report_id", "source_key", "horizon_days", name="uq_mi_bee_cfo_media_eval_key"), schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_media_eval_source", "bee_cfo_media_forecast_evaluations", ["assistant_id", "source_key", "evaluated_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_mi_bee_cfo_media_eval_source", table_name="bee_cfo_media_forecast_evaluations", schema=SCHEMA)
    op.drop_table("bee_cfo_media_forecast_evaluations", schema=SCHEMA)
    op.drop_table("bee_cfo_coverage_snapshots", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_market_events_watch_time", table_name="bee_cfo_market_events", schema=SCHEMA)
    op.drop_table("bee_cfo_market_events", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_alert_rules_active", table_name="bee_cfo_alert_rules", schema=SCHEMA)
    op.drop_table("bee_cfo_alert_rules", schema=SCHEMA)
