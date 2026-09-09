"""Add the isolated Bee CFO phase-one market analyst domain."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_bee_cfo_market_analyst"
down_revision = "0015_admin_user_preferences"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
NOW = sa.text("CURRENT_TIMESTAMP")
EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_ARRAY = sa.text("'[]'::jsonb")
ASSISTANT_FK = f"{SCHEMA}.assistant_workspaces.id"


def _assistant_id_column() -> sa.Column:
    return sa.Column(
        "assistant_id",
        UUID,
        sa.ForeignKey(ASSISTANT_FK, ondelete="CASCADE"),
        nullable=False,
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )


def upgrade() -> None:
    op.create_table(
        "bee_cfo_profiles",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("phase", sa.String(32), nullable=False, server_default="market_analyst"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Tehran"),
        sa.Column("schedule_slots", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("selected_market_ids", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("output_contract", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("source_policy", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("revision", sa.String(64), nullable=False, server_default="bee-cfo-1"),
        *_timestamps(),
        sa.UniqueConstraint("assistant_id", name="uq_mi_bee_cfo_profiles_assistant"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'active', 'paused')",
            name=op.f("ck_mi_bee_cfo_profiles_status"),
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_profiles_status", "bee_cfo_profiles", ["status"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_sources",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("source_key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("homepage_url", sa.String(2048), nullable=False),
        sa.Column("fetch_url", sa.String(2048), nullable=False),
        sa.Column("adapter", sa.String(16), nullable=False, server_default="rss"),
        sa.Column("origin", sa.String(16), nullable=False, server_default="user"),
        sa.Column("discovery_path", sa.String(64), nullable=False, server_default="user_provided"),
        sa.Column("authority", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("priority", sa.SmallInteger, nullable=False, server_default="3"),
        sa.Column("freshness_hours", sa.SmallInteger, nullable=False, server_default="72"),
        sa.Column("language", sa.String(16), nullable=False, server_default="fa"),
        sa.Column("region", sa.String(32), nullable=False, server_default="global"),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        *_timestamps(),
        sa.UniqueConstraint("assistant_id", "source_key", name="uq_mi_bee_cfo_sources_assistant_key"),
        sa.CheckConstraint("origin IN ('user', 'discovered')", name=op.f("ck_mi_bee_cfo_sources_origin")),
        sa.CheckConstraint(
            "authority IN ('official', 'specialist', 'news', 'exploratory', 'unknown')",
            name=op.f("ck_mi_bee_cfo_sources_authority"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'disabled', 'rejected')",
            name=op.f("ck_mi_bee_cfo_sources_status"),
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name=op.f("ck_mi_bee_cfo_sources_priority")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_bee_cfo_sources_enabled_priority",
        "bee_cfo_sources",
        ["assistant_id", "status", "priority"],
        schema=SCHEMA,
    )

    op.create_table(
        "bee_cfo_watches",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("watch_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("market", sa.String(80), nullable=False),
        sa.Column("asset_class", sa.String(80), nullable=False),
        sa.Column("region", sa.String(32), nullable=False, server_default="global"),
        sa.Column("currency", sa.String(16)),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("indicator_keys", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("source_keys", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("source_revision", sa.String(64), nullable=False, server_default="bee-cfo-1"),
        *_timestamps(),
        sa.UniqueConstraint("assistant_id", "watch_key", name="uq_mi_bee_cfo_watches_assistant_key"),
        sa.CheckConstraint("status IN ('draft', 'active', 'paused')", name=op.f("ck_mi_bee_cfo_watches_status")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_watches_enabled", "bee_cfo_watches", ["assistant_id", "status"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_snapshots",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("watch_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_state", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("provenance", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("data_quality", sa.Float, nullable=False, server_default="0"),
        sa.Column("change_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("watch_id", "as_of", name="uq_mi_bee_cfo_snapshots_watch_asof"),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_snapshots_watch_asof", "bee_cfo_snapshots", ["assistant_id", "watch_id", "as_of"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_reports",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("watch_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_kind", sa.String(24), nullable=False, server_default="scheduled"),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("current_state", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("scenarios", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("changes", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("uncertainties", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("citations", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("model", sa.String(80), nullable=False, server_default="deterministic-fallback"),
        sa.Column("output_contract_revision", sa.String(64), nullable=False, server_default="bee-cfo-1"),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('draft', 'ready', 'published', 'failed')", name=op.f("ck_mi_bee_cfo_reports_status")),
        sa.UniqueConstraint("watch_id", "as_of", "report_kind", name="uq_mi_bee_cfo_reports_watch_asof_kind"),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_reports_assistant_created", "bee_cfo_reports", ["assistant_id", "created_at"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_forecasts",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("report_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("watch_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scenario_key", sa.String(32), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("probability", sa.Float, nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_change", sa.Text, nullable=False),
        sa.Column("triggers", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("invalidation", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("probability BETWEEN 0 AND 1", name=op.f("ck_mi_bee_cfo_forecasts_probability")),
        sa.CheckConstraint("status IN ('open', 'evaluated', 'void')", name=op.f("ck_mi_bee_cfo_forecasts_status")),
        sa.UniqueConstraint("report_id", "scenario_key", name="uq_mi_bee_cfo_forecasts_report_scenario"),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_forecasts_due", "bee_cfo_forecasts", ["assistant_id", "horizon_end", "status"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_forecast_evaluations",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("forecast_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_forecasts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("actual_state", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("error_score", sa.Float),
        sa.Column("calibration_bucket", sa.String(24)),
        sa.Column("lesson", sa.Text, nullable=False, server_default=""),
        sa.Column("provenance", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.CheckConstraint(
            "outcome IN ('hit', 'miss', 'partial', 'not_evaluable')",
            name=op.f("ck_mi_bee_cfo_forecast_evaluations_outcome"),
        ),
        sa.CheckConstraint(
            "error_score IS NULL OR error_score BETWEEN 0 AND 1",
            name=op.f("ck_mi_bee_cfo_forecast_evaluations_error"),
        ),
        sa.UniqueConstraint("forecast_id", name="uq_mi_bee_cfo_forecast_evaluations_forecast"),
        schema=SCHEMA,
    )

    op.create_table(
        "bee_cfo_alerts",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("watch_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_key", sa.String(64), nullable=False),
        sa.Column("dedup_key", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="watch"),
        sa.Column("kind", sa.String(32), nullable=False, server_default="state_change"),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("delta", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "severity IN ('info', 'watch', 'important', 'critical')",
            name=op.f("ck_mi_bee_cfo_alerts_severity"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'sent', 'acknowledged', 'suppressed')",
            name=op.f("ck_mi_bee_cfo_alerts_status"),
        ),
        sa.UniqueConstraint("assistant_id", "dedup_key", name="uq_mi_bee_cfo_alerts_dedup"),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_alerts_open", "bee_cfo_alerts", ["assistant_id", "status", "created_at"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_infrastructure_audits",
        sa.Column("id", UUID, primary_key=True),
        _assistant_id_column(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decision", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("isolation_contract", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('passed', 'blocked')", name=op.f("ck_mi_bee_cfo_infrastructure_audits_status")),
        sa.UniqueConstraint("assistant_id", name="uq_mi_bee_cfo_infrastructure_audits_assistant"),
        schema=SCHEMA,
    )

    # Create a draft project boundary without enabling ingestion or delivery.
    op.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.assistant_workspaces "
            "(id, slug, name, description, business_name, status, config) "
            "VALUES ('00000000-0000-0000-0000-000000000002'::uuid, "
            "'bee-cfo', 'Bee CFO', 'Phase-one market analyst', 'Bee CFO', 'draft', "
            "jsonb_build_object('product', 'bee_cfo', 'runtime', "
            "jsonb_build_object('schedule_slots', '[]'::jsonb, 'bootstrap_pending', false))) "
            "ON CONFLICT (slug) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_table("bee_cfo_infrastructure_audits", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_alerts_open", table_name="bee_cfo_alerts", schema=SCHEMA)
    op.drop_table("bee_cfo_alerts", schema=SCHEMA)
    op.drop_table("bee_cfo_forecast_evaluations", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_forecasts_due", table_name="bee_cfo_forecasts", schema=SCHEMA)
    op.drop_table("bee_cfo_forecasts", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_reports_assistant_created", table_name="bee_cfo_reports", schema=SCHEMA)
    op.drop_table("bee_cfo_reports", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_snapshots_watch_asof", table_name="bee_cfo_snapshots", schema=SCHEMA)
    op.drop_table("bee_cfo_snapshots", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_watches_enabled", table_name="bee_cfo_watches", schema=SCHEMA)
    op.drop_table("bee_cfo_watches", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_sources_enabled_priority", table_name="bee_cfo_sources", schema=SCHEMA)
    op.drop_table("bee_cfo_sources", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_profiles_status", table_name="bee_cfo_profiles", schema=SCHEMA)
    op.drop_table("bee_cfo_profiles", schema=SCHEMA)
