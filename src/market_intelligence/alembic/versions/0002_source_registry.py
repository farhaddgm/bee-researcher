"""Add the MI-003 source registry and ingestion cursor tables."""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_source_registry"
down_revision = "0001_market_intelligence"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_key", sa.String(16), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("homepage_url", sa.String(2048), nullable=False),
        sa.Column("fetch_url", sa.String(2048), nullable=False),
        sa.Column("adapter", sa.String(16), nullable=False),
        sa.Column("item_url_pattern", sa.String(512), nullable=True),
        sa.Column("item_title_class_pattern", sa.String(512), nullable=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="fa"),
        sa.Column("region", sa.String(16), nullable=False, server_default="IR"),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "access_policy",
            sa.String(32),
            nullable=False,
            server_default="public_only",
        ),
        sa.Column("access_notes", sa.Text(), nullable=True),
        sa.Column(
            "robots_policy", sa.String(16), nullable=False, server_default="respect"
        ),
        sa.Column(
            "rate_limit_seconds", sa.SmallInteger(), nullable=False, server_default="60"
        ),
        sa.Column(
            "request_timeout_seconds",
            sa.SmallInteger(),
            nullable=False,
            server_default="20",
        ),
        sa.Column("max_retries", sa.SmallInteger(), nullable=False, server_default="2"),
        sa.Column("etag", sa.String(512), nullable=True),
        sa.Column("last_modified", sa.String(512), nullable=True),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.SmallInteger(), nullable=True),
        sa.Column(
            "health_status", sa.String(16), nullable=False, server_default="unknown"
        ),
        sa.Column(
            "consecutive_failures", sa.SmallInteger(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "adapter IN ('rss', 'html', 'json')",
            name=op.f("ck_mi_sources_adapter"),
        ),
        sa.CheckConstraint(
            "access_policy IN ('public_only')",
            name=op.f("ck_mi_sources_access_policy"),
        ),
        sa.CheckConstraint(
            "robots_policy IN ('respect', 'disabled')",
            name=op.f("ck_mi_sources_robots_policy"),
        ),
        sa.CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'degraded', 'disabled')",
            name=op.f("ck_mi_sources_health_status"),
        ),
        sa.CheckConstraint(
            "priority BETWEEN 1 AND 5",
            name=op.f("ck_mi_sources_priority"),
        ),
        sa.CheckConstraint(
            "rate_limit_seconds BETWEEN 1 AND 3600",
            name=op.f("ck_mi_sources_rate_limit_seconds"),
        ),
        sa.UniqueConstraint(
            "source_key", name=op.f("uq_mi_sources_source_key")
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_sources_enabled_priority",
        "sources",
        ["enabled", "priority"],
        schema=SCHEMA,
    )
    op.create_table(
        "source_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.sources.id",
                name=op.f("fk_mi_source_items_source_id_sources"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "raw_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint(
            "fingerprint", name=op.f("uq_mi_source_items_fingerprint")
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_source_items_source_published",
        "source_items",
        ["source_id", "published_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "source_fetch_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.sources.id",
                name=op.f("fk_mi_source_fetch_runs_source_id_sources"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("items_seen", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("items_inserted", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'not_modified', "
            "'rate_limited', 'robots_denied', 'skipped_locked')",
            name=op.f("ck_mi_source_fetch_runs_status"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_source_fetch_runs_source_started",
        "source_fetch_runs",
        ["source_id", "started_at"],
        schema=SCHEMA,
    )

    sources = sa.table(
        "sources",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("source_key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("homepage_url", sa.String()),
        sa.column("fetch_url", sa.String()),
        sa.column("adapter", sa.String()),
        sa.column("item_url_pattern", sa.String()),
        sa.column("item_title_class_pattern", sa.String()),
        sa.column("language", sa.String()),
        sa.column("region", sa.String()),
        sa.column("priority", sa.SmallInteger()),
        sa.column("rate_limit_seconds", sa.SmallInteger()),
        sa.column("request_timeout_seconds", sa.SmallInteger()),
        sa.column("max_retries", sa.SmallInteger()),
        sa.column("access_notes", sa.Text()),
        schema=SCHEMA,
    )
    seed_rows = [
        (
            "S-001",
            "راه پرداخت",
            "https://way2pay.ir/",
            "https://way2pay.ir/feed/",
            "rss",
            None,
            None,
            5,
            "Public feed candidate; live availability is monitored independently.",
        ),
        (
            "S-002",
            "دیجیاتو",
            "https://digiato.com/",
            "https://digiato.com/feed",
            "rss",
            None,
            None,
            4,
            "Public RSS confirmed during MI-003 development.",
        ),
        (
            "S-003",
            "پیوست",
            "https://peivast.com/",
            "https://peivast.com/feed",
            "rss",
            None,
            None,
            5,
            "Public RSS confirmed during MI-003 development.",
        ),
        (
            "S-004",
            "زومیت",
            "https://www.zoomit.ir/",
            "https://www.zoomit.ir/feed/",
            "rss",
            None,
            None,
            3,
            "Public RSS confirmed during MI-003 development.",
        ),
        (
            "S-005",
            "رده",
            "https://www.rade.ir/",
            "https://www.rade.ir/mag/",
            "html",
            r"^/[0-9]+-",
            r"(^|\s)rade-color(\s|$)",
            4,
            "Public homepage HTML adapter; no login or access bypass.",
        ),
    ]
    op.bulk_insert(
        sources,
        [
            {
                "id": uuid.UUID(f"00000000-0000-4000-8000-{index:012d}"),
                "source_key": key,
                "name": name,
                "homepage_url": homepage,
                "fetch_url": fetch_url,
                "adapter": adapter,
                "item_url_pattern": item_url_pattern,
                "item_title_class_pattern": item_title_class_pattern,
                "language": "fa",
                "region": "IR",
                "priority": priority,
                "rate_limit_seconds": 60,
                "request_timeout_seconds": 20,
                "max_retries": 2,
                "access_notes": notes,
            }
            for index, (
                key,
                name,
                homepage,
                fetch_url,
                adapter,
                item_url_pattern,
                item_title_class_pattern,
                priority,
                notes,
            )
            in enumerate(seed_rows, 1)
        ],
    )
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.service_state "
            "SET service_version='0.3.0', config_revision='mi-003', "
            "updated_at=CURRENT_TIMESTAMP WHERE id=1"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mi_source_fetch_runs_source_started",
        table_name="source_fetch_runs",
        schema=SCHEMA,
    )
    op.drop_table("source_fetch_runs", schema=SCHEMA)
    op.drop_index(
        "ix_mi_source_items_source_published",
        table_name="source_items",
        schema=SCHEMA,
    )
    op.drop_table("source_items", schema=SCHEMA)
    op.drop_index(
        "ix_mi_sources_enabled_priority",
        table_name="sources",
        schema=SCHEMA,
    )
    op.drop_table("sources", schema=SCHEMA)
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.service_state "
            "SET service_version='0.2.0', config_revision='mi-002', "
            "updated_at=CURRENT_TIMESTAMP WHERE id=1"
        )
    )
