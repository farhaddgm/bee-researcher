"""Add the approved MI-004 through MI-010 processing and delivery pipeline."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_full_pipeline"
down_revision = "0002_source_registry"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def _sql_string(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sql_json(value: object) -> str:
    return _sql_string(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "business_profiles",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("business_name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("products_services", sa.Text(), nullable=False),
        sa.Column("target_customers", sa.Text(), nullable=False),
        sa.Column("markets", sa.Text(), nullable=False),
        sa.Column("revenue_model", sa.Text(), nullable=False, server_default=""),
        sa.Column("strategic_goals", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "competitors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sensitivities",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("output_language", sa.String(16), nullable=False, server_default="fa"),
        sa.Column("output_tone", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.String(64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "id = 1", name=op.f("ck_mi_business_profiles_singleton")
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("topic_key", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column(
            "positive_terms",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "negative_terms",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("importance", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("threshold", sa.Float(), nullable=False, server_default="0.45"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_revision", sa.String(64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "threshold BETWEEN 0 AND 1", name=op.f("ck_mi_topics_threshold")
        ),
        sa.UniqueConstraint("topic_key", name=op.f("uq_mi_topics_topic_key")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_topics_enabled_importance",
        "topics",
        ["enabled", "importance"],
        schema=SCHEMA,
    )
    op.create_table(
        "normalized_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.source_items.id",
                name=op.f("fk_mi_normalized_articles_source_item_id_source_items"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.String(500), nullable=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="fa"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("extraction_status", sa.String(16), nullable=False),
        sa.Column("extraction_method", sa.String(32), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "extraction_status IN ('complete', 'partial', 'failed', 'blocked')",
            name=op.f("ck_mi_normalized_articles_status"),
        ),
        sa.UniqueConstraint(
            "source_item_id",
            name=op.f("uq_mi_normalized_articles_source_item_id"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_normalized_articles_status_extracted",
        "normalized_articles",
        ["extraction_status", "extracted_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_normalized_articles_content_hash",
        "normalized_articles",
        ["content_hash"],
        schema=SCHEMA,
    )
    op.create_table(
        "article_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.normalized_articles.id",
                name=op.f("fk_mi_article_topics_article_id_normalized_articles"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.topics.id",
                name=op.f("fk_mi_article_topics_topic_id_topics"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("lexical_score", sa.Float(), nullable=False),
        sa.Column("semantic_score", sa.Float(), nullable=True),
        sa.Column("combined_score", sa.Float(), nullable=False),
        sa.Column(
            "matched_positive",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "matched_negative",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "lexical_score BETWEEN 0 AND 1",
            name=op.f("ck_mi_article_topics_lexical"),
        ),
        sa.CheckConstraint(
            "semantic_score IS NULL OR semantic_score BETWEEN 0 AND 1",
            name=op.f("ck_mi_article_topics_semantic"),
        ),
        sa.CheckConstraint(
            "combined_score BETWEEN 0 AND 1",
            name=op.f("ck_mi_article_topics_combined"),
        ),
        sa.UniqueConstraint(
            "article_id",
            "topic_id",
            name=op.f("uq_mi_article_topics_article_topic"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_article_topics_selected_score",
        "article_topics",
        ["selected", "combined_score"],
        schema=SCHEMA,
    )
    op.create_table(
        "event_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cluster_key", sa.String(64), nullable=False),
        sa.Column(
            "representative_article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.normalized_articles.id",
                name=op.f(
                    "fk_mi_event_clusters_representative_article_id_normalized_articles"
                ),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("source_count", sa.SmallInteger(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint(
            "cluster_key", name=op.f("uq_mi_event_clusters_cluster_key")
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_event_clusters_updated",
        "event_clusters",
        ["updated_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "cluster_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.event_clusters.id",
                name=op.f("fk_mi_cluster_members_cluster_id_event_clusters"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.normalized_articles.id",
                name=op.f("fk_mi_cluster_members_article_id_normalized_articles"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "article_id", name=op.f("uq_mi_cluster_members_article_id")
        ),
        sa.UniqueConstraint(
            "cluster_id",
            "article_id",
            name=op.f("uq_mi_cluster_members_cluster_article"),
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "article_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.normalized_articles.id",
                name=op.f("fk_mi_article_analyses_article_id_normalized_articles"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("news_summary", sa.Text(), nullable=False),
        sa.Column("business_connection", sa.Text(), nullable=False),
        sa.Column("opportunity", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=False),
        sa.Column("time_horizon", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("facts", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("inferences", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("topic_scores", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'fallback', 'failed')",
            name=op.f("ck_mi_article_analyses_status"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name=op.f("ck_mi_article_analyses_confidence"),
        ),
        sa.UniqueConstraint(
            "article_id", name=op.f("uq_mi_article_analyses_article_id")
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_article_analyses_created",
        "article_analyses",
        ["created_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.article_analyses.id",
                name=op.f("fk_mi_publications_analysis_id_article_analyses"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("channel_id_hash", sa.String(64), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("telegram_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("audit", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('preview', 'published', 'edited', 'deleted', 'failed')",
            name=op.f("ck_mi_publications_status"),
        ),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_mi_publications_idempotency_key")
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_publications_status_created",
        "publications",
        ["status", "created_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.article_analyses.id",
                name=op.f("fk_mi_feedback_analysis_id_article_analyses"),
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("actor_key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(8), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="api"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "value IN ('up', 'down')", name=op.f("ck_mi_feedback_value")
        ),
        sa.UniqueConstraint(
            "analysis_id",
            "actor_key",
            name=op.f("uq_mi_feedback_analysis_actor"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_mi_feedback_created", "feedback", ["created_at"], schema=SCHEMA
    )
    op.create_table(
        "weekly_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("trends", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("competitor_mentions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('preview', 'published', 'failed')",
            name=op.f("ck_mi_weekly_reports_status"),
        ),
        sa.UniqueConstraint(
            "period_start",
            "period_end",
            name=op.f("uq_mi_weekly_reports_period"),
        ),
        schema=SCHEMA,
    )

    profile_values = [
        "1",
        _sql_string("داتین"),
        _sql_string("شرکت خدمات نرم‌افزاری در حوزه مالی در ایران"),
        _sql_string("محصولات و خدمات معرفی‌شده در https://dotin.ir/"),
        _sql_string("کسب‌وکارهای مالی ایران، از جمله بانک‌ها"),
        _sql_string("ایران"),
        _sql_string("فروش نرم‌افزار و خدمات پشتیبانی"),
        _sql_string("محرمانه؛ در تحلیل از هدف مشخصی استنباط نشود"),
        _sql_json(["شرکت خدمات انفورماتیک", "توسن"]),
        _sql_json([]),
        _sql_string("fa"),
        _sql_string("کوتاه، تحلیلی، اجرایی و رسمی"),
        _sql_string("sheet-2026-08-10"),
    ]
    op.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.business_profiles "
            "(id, business_name, description, products_services, target_customers, "
            "markets, revenue_model, strategic_goals, competitors, sensitivities, "
            "output_language, output_tone, source_revision) VALUES ("
            + ", ".join(profile_values)
            + ")"
        )
    )
    seed_topics = [
        (
            "T-001",
            "خدمات مالی",
            "محصولات و زیرساخت‌های پرداخت، اعتبار، فین‌تک و خدمات مالی دیجیتال",
            ["خدمات مالی", "پرداخت", "پرداخت الکترونیک", "فین‌تک", "کیف پول", "اعتبار", "اعتبارسنجی", "شاپرک", "شتاب", "کارتخوان", "درگاه پرداخت", "لندتک"],
        ),
        (
            "T-002",
            "خدمات بانکی",
            "بانکداری، محصولات بانکی، زیرساخت نرم‌افزاری بانک و تجربه مشتری بانکی",
            ["بانک", "بانکی", "بانکداری", "تسهیلات", "سپرده", "وام", "کوربنکینگ", "بانکداری دیجیتال", "نئوبانک", "موبایل بانک", "اینترنت بانک"],
        ),
        (
            "T-003",
            "بانک مرکزی",
            "تصمیم‌ها، سیاست‌ها و اقدامات بانک مرکزی جمهوری اسلامی ایران",
            ["بانک مرکزی", "بانک مرکزی جمهوری اسلامی ایران", "رئیس کل بانک مرکزی", "هیئت عالی بانک مرکزی", "سیاست پولی", "نرخ سود بانکی"],
        ),
        (
            "T-004",
            "قوانین و دستورالعمل‌های مالی ایران",
            "قوانین، مقررات، بخشنامه‌ها و دستورالعمل‌های نهادهای سیاست‌گذار مالی ایران",
            ["بخشنامه", "دستورالعمل", "مصوبه", "قانون", "مقررات", "الزام", "نهاد ناظر", "وزارت اقتصاد", "سازمان بورس", "شورای پول و اعتبار", "مبارزه با پولشویی"],
        ),
    ]
    for index, (key, name, definition, positive_terms) in enumerate(
        seed_topics, start=1
    ):
        topic_id = f"10000000-0000-4000-8000-{index:012d}"
        importance = 5 if key in {"T-002", "T-003", "T-004"} else 4
        op.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.topics "
                "(id, topic_key, name, definition, positive_terms, negative_terms, "
                "importance, threshold, source_revision) VALUES ("
                + ", ".join(
                    [
                        _sql_string(topic_id),
                        _sql_string(key),
                        _sql_string(name),
                        _sql_string(definition),
                        _sql_json(positive_terms),
                        _sql_json([]),
                        str(importance),
                        "0.45",
                        _sql_string("sheet-2026-08-10"),
                    ]
                )
                + ")"
            )
        )
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.service_state "
            "SET service_version='1.0.0', config_revision='mi-010', "
            "updated_at=CURRENT_TIMESTAMP WHERE id=1"
        )
    )


def downgrade() -> None:
    for table in (
        "weekly_reports",
        "feedback",
        "publications",
        "article_analyses",
        "cluster_members",
        "event_clusters",
        "article_topics",
        "normalized_articles",
        "topics",
        "business_profiles",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.service_state "
            "SET service_version='0.3.0', config_revision='mi-003', "
            "updated_at=CURRENT_TIMESTAMP WHERE id=1"
        )
    )
