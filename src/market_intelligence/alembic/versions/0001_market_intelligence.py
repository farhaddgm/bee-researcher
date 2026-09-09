"""Create the isolated Market Intelligence runtime schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_market_intelligence"
down_revision = None
branch_labels = ("market_intelligence",)
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    op.create_table(
        "service_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("service_version", sa.String(32), nullable=False),
        sa.Column("config_revision", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "id = 1",
            name=op.f("ck_mi_service_state_singleton"),
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "job_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_mi_job_runs_status"),
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_mi_job_runs_idempotency_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_job_runs_status_scheduled",
        "job_runs",
        ["status", "scheduled_for"],
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.service_state
                (id, service_version, config_revision)
            VALUES (1, '0.2.0', 'mi-002')
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mi_job_runs_status_scheduled",
        table_name="job_runs",
        schema=SCHEMA,
    )
    op.drop_table("job_runs", schema=SCHEMA)
    op.drop_table("service_state", schema=SCHEMA)
    # The schema and its independent Alembic version table are intentionally kept.
