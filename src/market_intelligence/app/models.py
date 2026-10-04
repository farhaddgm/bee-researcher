from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


SCHEMA = "market_intelligence"
NAMING_CONVENTION = {
    "ix": "ix_mi_%(table_name)s_%(column_0_name)s",
    "uq": "uq_mi_%(table_name)s_%(column_0_name)s",
    "ck": "ck_mi_%(constraint_name)s",
    "fk": "fk_mi_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_mi_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)


class ServiceState(Base):
    __tablename__ = "service_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="service_state_singleton"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    service_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssistantWorkspace(Base):
    """Configuration boundary for one independent market-research assistant."""

    __tablename__ = "assistant_workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_mi_assistant_workspaces_slug"),
        CheckConstraint(
            "status IN ('draft', 'testing', 'active', 'paused', 'archived')",
            name="assistant_workspaces_status",
        ),
        Index("ix_mi_assistant_workspaces_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_mi_admin_users_username"),
        UniqueConstraint("email", name="uq_mi_admin_users_email"),
        UniqueConstraint("google_sub", name="uq_mi_admin_users_google_sub"),
        CheckConstraint("login_method IN ('password', 'google', 'both')", name="admin_users_login_method"),
        CheckConstraint("role IN ('admin', 'assistant_admin', 'editor', 'analyst', 'viewer')", name="admin_users_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    # Normalized Gmail address (see app.google_auth.normalize_gmail). Only the
    # owner can attach an address; the owner is the account whose address
    # equals Settings.owner_email.
    email: Mapped[str | None] = mapped_column(String(320))
    google_sub: Mapped[str | None] = mapped_column(String(255))
    login_method: Mapped[str] = mapped_column(String(16), nullable=False, default="password", server_default="password")
    # Empty for Google-only accounts.
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssistantMember(Base):
    """Explicit user-to-workspace assignment used by the backoffice RBAC boundary."""

    __tablename__ = "assistant_members"
    __table_args__ = (
        UniqueConstraint("assistant_id", "user_id", name="uq_mi_assistant_members_assistant_user"),
        CheckConstraint(
            "role IN ('admin', 'assistant_admin', 'editor', 'analyst', 'viewer')",
            name="assistant_members_role",
        ),
        Index("ix_mi_assistant_members_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    __table_args__ = (Index("ix_mi_admin_sessions_expires", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Password authentication creates an unverified session when MFA is
    # enforced for the account.  Existing sessions remain trusted through the
    # server default so this additive migration is safe during rollout.
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (Index("ix_mi_admin_audit_logs_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="SET NULL"))
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="success")
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SupportTicket(Base):
    """Small, owner-routed support inbox for back-office users."""

    __tablename__ = "support_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_user', 'answered', 'resolved', 'closed')",
            name="support_tickets_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="support_tickets_priority",
        ),
        Index("ix_mi_support_tickets_status_created", "status", "created_at"),
        Index("ix_mi_support_tickets_creator_created", "created_by", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="SET NULL"), nullable=True
    )
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="other", server_default="other")
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    owner_reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportTicketMessage(Base):
    """Immutable chronological messages belonging to a support ticket."""

    __tablename__ = "support_ticket_messages"
    __table_args__ = (
        CheckConstraint(
            "author_role IN ('owner', 'requester')",
            name="support_ticket_messages_author_role",
        ),
        Index("ix_mi_support_ticket_messages_ticket_created", "ticket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.support_tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_role: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="job_runs_status",
        ),
        UniqueConstraint("idempotency_key", name="uq_mi_job_runs_idempotency_key"),
        Index("ix_mi_job_runs_status_scheduled", "status", "scheduled_for"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "adapter IN ('rss', 'html', 'json', 'telegram_public', 'telegram_private', 'instagram_public', 'instagram_private', 'x_public', 'x_private')",
            name="sources_adapter",
        ),
        CheckConstraint(
            "access_policy IN ('public_only', 'private_authenticated')",
            name="sources_access_policy",
        ),
        CheckConstraint(
            "robots_policy IN ('respect', 'disabled')",
            name="sources_robots_policy",
        ),
        CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'degraded', 'disabled')",
            name="sources_health_status",
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="sources_priority"),
        CheckConstraint(
            "output_language IN ('source', 'fa', 'en', 'tr', 'ar', 'it', 'es', 'de', 'fr')",
            name="sources_output_language",
        ),
        CheckConstraint(
            "rate_limit_seconds BETWEEN 1 AND 3600",
            name="sources_rate_limit_seconds",
        ),
        UniqueConstraint("assistant_id", "source_key", name="uq_mi_sources_assistant_source_key"),
        Index("ix_mi_sources_enabled_priority", "enabled", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    source_key: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    homepage_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    fetch_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    item_url_pattern: Mapped[str | None] = mapped_column(String(512))
    item_title_class_pattern: Mapped[str | None] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="fa")
    # Language used for generated summaries and published messages. ``source``
    # keeps the historical behavior and follows the source/article language.
    output_language: Mapped[str] = mapped_column(String(16), nullable=False, default="source")
    region: Mapped[str] = mapped_column(String(16), nullable=False, default="IR")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    access_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="public_only"
    )
    access_notes: Mapped[str | None] = mapped_column(Text)
    # These are non-secret environment variable names and account handles/IDs.
    credential_ref: Mapped[str | None] = mapped_column(String(128))
    account_ref: Mapped[str | None] = mapped_column(String(256))
    robots_policy: Mapped[str] = mapped_column(
        String(16), nullable=False, default="respect"
    )
    rate_limit_seconds: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=60
    )
    request_timeout_seconds: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=20
    )
    max_retries: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(512))
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(SmallInteger)
    health_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceItem(Base):
    __tablename__ = "source_items"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_mi_source_items_fingerprint"),
        Index("ix_mi_source_items_source_published", "source_id", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SourceFetchRun(Base):
    __tablename__ = "source_fetch_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'not_modified', "
            "'rate_limited', 'robots_denied', 'skipped_locked')",
            name="source_fetch_runs_status",
        ),
        Index("ix_mi_source_fetch_runs_source_started", "source_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    items_seen: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    items_inserted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BusinessProfile(Base):
    __tablename__ = "business_profiles"
    # Profiles are scoped to an assistant.  The original MVP used a singleton
    # row (id=1), which made the back-office incapable of managing more than
    # one business.  IDs remain small integers for backwards compatibility;
    # assistant_id is the ownership boundary.
    __table_args__ = (Index("ix_mi_business_profiles_assistant", "assistant_id"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    products_services: Mapped[str] = mapped_column(Text, nullable=False)
    target_customers: Mapped[str] = mapped_column(Text, nullable=False)
    markets: Mapped[str] = mapped_column(Text, nullable=False)
    revenue_model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strategic_goals: Mapped[str] = mapped_column(Text, nullable=False, default="")
    competitors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sensitivities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output_language: Mapped[str] = mapped_column(String(16), nullable=False, default="fa")
    output_tone: Mapped[str] = mapped_column(Text, nullable=False)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        CheckConstraint("threshold BETWEEN 0 AND 1", name="topics_threshold"),
        UniqueConstraint("assistant_id", "topic_key", name="uq_mi_topics_assistant_topic_key"),
        Index("ix_mi_topics_enabled_importance", "enabled", "importance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    topic_key: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    positive_terms: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    negative_terms: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.45)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NormalizedArticle(Base):
    __tablename__ = "normalized_articles"
    __table_args__ = (
        CheckConstraint(
            "extraction_status IN ('complete', 'partial', 'failed', 'blocked')",
            name="normalized_articles_status",
        ),
        UniqueConstraint(
            "source_item_id", name="uq_mi_normalized_articles_source_item_id"
        ),
        Index("ix_mi_normalized_articles_status_extracted", "extraction_status", "extracted_at"),
        Index("ix_mi_normalized_articles_content_hash", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.source_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="fa")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_html: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extraction_status: Mapped[str] = mapped_column(String(16), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ArticleTopic(Base):
    __tablename__ = "article_topics"
    __table_args__ = (
        CheckConstraint("lexical_score BETWEEN 0 AND 1", name="article_topics_lexical"),
        CheckConstraint(
            "semantic_score IS NULL OR semantic_score BETWEEN 0 AND 1",
            name="article_topics_semantic",
        ),
        CheckConstraint("combined_score BETWEEN 0 AND 1", name="article_topics_combined"),
        UniqueConstraint("article_id", "topic_id", name="uq_mi_article_topics_article_topic"),
        Index("ix_mi_article_topics_selected_score", "selected", "combined_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.normalized_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    lexical_score: Mapped[float] = mapped_column(Float, nullable=False)
    ai_score: Mapped[float | None] = mapped_column(Float)
    context_hash: Mapped[str | None] = mapped_column(String(64))
    semantic_score: Mapped[float | None] = mapped_column(Float)
    combined_score: Mapped[float] = mapped_column(Float, nullable=False)
    matched_positive: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    matched_negative: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventCluster(Base):
    __tablename__ = "event_clusters"
    __table_args__ = (
        UniqueConstraint("cluster_key", name="uq_mi_event_clusters_cluster_key"),
        Index("ix_mi_event_clusters_updated", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False)
    representative_article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.normalized_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    source_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClusterMember(Base):
    __tablename__ = "cluster_members"
    __table_args__ = (
        UniqueConstraint("article_id", name="uq_mi_cluster_members_article_id"),
        UniqueConstraint(
            "cluster_id", "article_id", name="uq_mi_cluster_members_cluster_article"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.event_clusters.id", ondelete="CASCADE"),
        nullable=False,
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.normalized_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ArticleAnalysis(Base):
    __tablename__ = "article_analyses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'fallback', 'failed')",
            name="article_analyses_status",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="article_analyses_confidence"),
        UniqueConstraint("article_id", name="uq_mi_article_analyses_article_id"),
        Index("ix_mi_article_analyses_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.normalized_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    news_summary: Mapped[str] = mapped_column(Text, nullable=False)
    business_connection: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    facts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    inferences: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    topic_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('preview', 'publishing', 'published', 'edited', 'deleted', 'failed', 'archived', 'rejected')",
            name="publications_status",
        ),
        UniqueConstraint("idempotency_key", name="uq_mi_publications_idempotency_key"),
        Index("ix_mi_publications_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.article_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_id_hash: Mapped[str | None] = mapped_column(String(64))
    message_id: Mapped[int | None] = mapped_column(Integer)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    audit: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("value IN ('up', 'down')", name="feedback_value"),
        UniqueConstraint(
            "analysis_id", "actor_key", name="uq_mi_feedback_analysis_actor"
        ),
        Index("ix_mi_feedback_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.article_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(String(8), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('preview', 'published', 'failed')",
            name="weekly_reports_status",
        ),
        UniqueConstraint("period_start", "period_end", name="uq_mi_weekly_reports_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    trends: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    competitor_mentions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BeeCFOProfile(Base):
    """Product contract for the phase-one Bee CFO market analyst.

    This is deliberately separate from the legacy business profile.  Bee CFO
    phase one has no user holdings, goals, risk profile, or personalized
    recommendation data.
    """

    __tablename__ = "bee_cfo_profiles"
    __table_args__ = (
        UniqueConstraint("assistant_id", name="uq_mi_bee_cfo_profiles_assistant"),
        CheckConstraint(
            "status IN ('draft', 'testing', 'active', 'paused')",
            name="bee_cfo_profiles_status",
        ),
        Index("ix_mi_bee_cfo_profiles_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="market_analyst")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Tehran")
    schedule_slots: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    selected_market_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output_contract: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOMarket(Base):
    """Product-owner controlled market catalog for Bee CFO selections."""

    __tablename__ = "bee_cfo_markets"
    __table_args__ = (
        UniqueConstraint("market_key", name="uq_mi_bee_cfo_markets_key"),
        CheckConstraint("status IN ('draft', 'active', 'disabled')", name="bee_cfo_markets_status"),
        Index("ix_mi_bee_cfo_markets_status_order", "status", "display_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False, default="global")
    currency: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOIndicator(Base):
    """Product-owner controlled quote/index catalog."""

    __tablename__ = "bee_cfo_indicators"
    __table_args__ = (
        UniqueConstraint("indicator_key", name="uq_mi_bee_cfo_indicators_key"),
        CheckConstraint("status IN ('draft', 'active', 'disabled')", name="bee_cfo_indicators_status"),
        Index("ix_mi_bee_cfo_indicators_market_status", "market_key", "status", "display_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_key: Mapped[str] = mapped_column(String(64), nullable=False)
    indicator_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quote_unit: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="IRR")
    parser_key: Mapped[str] = mapped_column(String(48), nullable=False, default="generic")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOIndicatorSource(Base):
    """Owner-approved direct price reference for one catalog indicator."""

    __tablename__ = "bee_cfo_indicator_sources"
    __table_args__ = (
        UniqueConstraint("indicator_id", "source_key", name="uq_mi_bee_cfo_indicator_sources_key"),
        CheckConstraint("adapter IN ('html', 'json')", name="bee_cfo_indicator_sources_adapter"),
        CheckConstraint("status IN ('draft', 'active', 'disabled')", name="bee_cfo_indicator_sources_status"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="bee_cfo_indicator_sources_priority"),
        Index("ix_mi_bee_cfo_indicator_sources_active", "indicator_id", "status", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_indicators.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    homepage_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    fetch_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    adapter: Mapped[str] = mapped_column(String(16), nullable=False, default="html")
    parser_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOAssistantIndicatorSelection(Base):
    """One market/index selection per Bee CFO Assistant workspace."""

    __tablename__ = "bee_cfo_assistant_indicator_selections"
    __table_args__ = (
        UniqueConstraint("assistant_id", name="uq_mi_bee_cfo_indicator_selection_assistant"),
        CheckConstraint("status IN ('draft', 'active', 'paused')", name="bee_cfo_indicator_selection_status"),
        Index("ix_mi_bee_cfo_indicator_selection_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    market_key: Mapped[str] = mapped_column(String(64), nullable=False)
    indicator_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-indicator-1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOPriceSnapshot(Base):
    """Auditable quote snapshot used for change reporting and replay."""

    __tablename__ = "bee_cfo_price_snapshots"
    __table_args__ = (
        Index("ix_mi_bee_cfo_price_snapshots_assistant_indicator_observed", "assistant_id", "indicator_key", "observed_at"),
        UniqueConstraint("assistant_id", "indicator_key", "observed_at", name="uq_mi_bee_cfo_price_snapshot_observed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    indicator_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_indicator_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    previous_value: Mapped[float | None] = mapped_column(Numeric(24, 8))
    change_value: Mapped[float | None] = mapped_column(Numeric(24, 8))
    change_percent: Mapped[float | None] = mapped_column(Numeric(18, 8))
    quote_unit: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_quote: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOPriceDelivery(Base):
    """Idempotency ledger for the price message sent before a report."""

    __tablename__ = "bee_cfo_price_deliveries"
    __table_args__ = (
        UniqueConstraint("assistant_id", "report_id", "destination_id", name="uq_mi_bee_cfo_price_delivery_destination"),
        CheckConstraint("status IN ('pending', 'sent', 'failed', 'skipped')", name="bee_cfo_price_deliveries_status"),
        Index("ix_mi_bee_cfo_price_deliveries_status_created", "assistant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_price_snapshots.id", ondelete="SET NULL"),
    )
    destination_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    message_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    renderer_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-price-1")
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOSource(Base):
    """Auditable source registry; discovered sources never auto-promote."""

    __tablename__ = "bee_cfo_sources"
    __table_args__ = (
        UniqueConstraint("assistant_id", "source_key", name="uq_mi_bee_cfo_sources_assistant_key"),
        CheckConstraint(
            "origin IN ('user', 'discovered')",
            name="bee_cfo_sources_origin",
        ),
        CheckConstraint(
            "authority IN ('official', 'specialist', 'news', 'exploratory', 'unknown')",
            name="bee_cfo_sources_authority",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'disabled', 'rejected')",
            name="bee_cfo_sources_status",
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="bee_cfo_sources_priority"),
        Index("ix_mi_bee_cfo_sources_enabled_priority", "assistant_id", "status", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    homepage_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    fetch_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    adapter: Mapped[str] = mapped_column(String(16), nullable=False, default="rss")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    discovery_path: Mapped[str] = mapped_column(String(64), nullable=False, default="user_provided")
    authority: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    freshness_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=72)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="fa")
    region: Mapped[str] = mapped_column(String(32), nullable=False, default="global")
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOWatch(Base):
    """A market/asset universe item with no personal portfolio context."""

    __tablename__ = "bee_cfo_watches"
    __table_args__ = (
        UniqueConstraint("assistant_id", "watch_key", name="uq_mi_bee_cfo_watches_assistant_key"),
        CheckConstraint("status IN ('draft', 'active', 'paused')", name="bee_cfo_watches_status"),
        Index("ix_mi_bee_cfo_watches_enabled", "assistant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    watch_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    market: Mapped[str] = mapped_column(String(80), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(80), nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False, default="global")
    currency: Mapped[str | None] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    indicator_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOSnapshot(Base):
    """Immutable-as-of market state used for delta detection and replay."""

    __tablename__ = "bee_cfo_snapshots"
    __table_args__ = (
        Index("ix_mi_bee_cfo_snapshots_watch_asof", "assistant_id", "watch_id", "as_of"),
        UniqueConstraint("watch_id", "as_of", name="uq_mi_bee_cfo_snapshots_watch_asof"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"),
        nullable=False,
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    data_quality: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    change_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOReport(Base):
    """Structured, source-grounded report; recommendation fields are absent."""

    __tablename__ = "bee_cfo_reports"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'ready', 'published', 'failed')", name="bee_cfo_reports_status"),
        UniqueConstraint("watch_id", "as_of", "report_kind", name="uq_mi_bee_cfo_reports_watch_asof_kind"),
        Index("ix_mi_bee_cfo_reports_assistant_created", "assistant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="scheduled")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    current_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    scenarios: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    changes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    uncertainties: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="deterministic-fallback")
    output_contract_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-1")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFODelivery(Base):
    """Idempotent delivery ledger for Bee CFO report destinations."""

    __tablename__ = "bee_cfo_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="bee_cfo_deliveries_status",
        ),
        UniqueConstraint(
            "assistant_id", "report_id", "destination_id",
            name="uq_mi_bee_cfo_deliveries_report_destination",
        ),
        Index("ix_mi_bee_cfo_deliveries_status_created", "assistant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    destination_id: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_type: Mapped[str] = mapped_column(String(24), nullable=False, default="telegram")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    message_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    media_message_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    renderer_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-telegram-1")
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOForecast(Base):
    """A testable scenario with a horizon and explicit invalidation rule."""

    __tablename__ = "bee_cfo_forecasts"
    __table_args__ = (
        CheckConstraint("probability BETWEEN 0 AND 1", name="bee_cfo_forecasts_probability"),
        CheckConstraint("status IN ('open', 'evaluated', 'void')", name="bee_cfo_forecasts_status"),
        UniqueConstraint("report_id", "scenario_key", name="uq_mi_bee_cfo_forecasts_report_scenario"),
        Index("ix_mi_bee_cfo_forecasts_due", "assistant_id", "horizon_end", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"),
        nullable=False,
    )
    scenario_key: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_change: Mapped[str] = mapped_column(Text, nullable=False)
    triggers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    invalidation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOForecastEvaluation(Base):
    """Post-horizon outcome record for calibration and lessons learned."""

    __tablename__ = "bee_cfo_forecast_evaluations"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('hit', 'miss', 'partial', 'not_evaluable')",
            name="bee_cfo_forecast_evaluations_outcome",
        ),
        CheckConstraint("error_score IS NULL OR error_score BETWEEN 0 AND 1", name="bee_cfo_forecast_evaluations_error"),
        UniqueConstraint("forecast_id", name="uq_mi_bee_cfo_forecast_evaluations_forecast"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    forecast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_forecasts.id", ondelete="CASCADE"),
        nullable=False,
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    actual_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_score: Mapped[float | None] = mapped_column(Float)
    calibration_bucket: Mapped[str | None] = mapped_column(String(24))
    lesson: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provenance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class BeeCFOFactorAttribution(Base):
    """Explainable factor cards attached to one immutable market report."""

    __tablename__ = "bee_cfo_factor_attributions"
    __table_args__ = (
        CheckConstraint("direction IN ('up', 'down', 'flat', 'unknown')", name="bee_cfo_factor_attributions_direction"),
        CheckConstraint("strength IN ('strong', 'medium', 'weak', 'unknown')", name="bee_cfo_factor_attributions_strength"),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 1", name="bee_cfo_factor_attributions_score"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="bee_cfo_factor_attributions_confidence"),
        UniqueConstraint("report_id", "factor_key", name="uq_mi_bee_cfo_factor_attributions_report_factor"),
        Index("ix_mi_bee_cfo_factor_attributions_assistant_report", "assistant_id", "report_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_snapshots.id", ondelete="SET NULL"))
    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False)
    factor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    strength: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    score: Mapped[float | None] = mapped_column(Float)
    evidence_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    source_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    horizon: Mapped[str] = mapped_column(String(80), nullable=False, default="نامشخص")
    invalidation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attribution_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="co_movement")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-factors-1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOPriceForecast(Base):
    """Numeric point/range forecast for one indicator and horizon."""

    __tablename__ = "bee_cfo_price_forecasts"
    __table_args__ = (
        CheckConstraint("horizon_days IN (1, 7, 30)", name="bee_cfo_price_forecasts_horizon"),
        CheckConstraint("probability_up BETWEEN 0 AND 1 AND probability_down BETWEEN 0 AND 1 AND probability_flat BETWEEN 0 AND 1", name="bee_cfo_price_forecasts_probabilities"),
        CheckConstraint("quality_status IN ('available', 'limited', 'no_call')", name="bee_cfo_price_forecasts_quality"),
        CheckConstraint("status IN ('open', 'evaluated', 'void')", name="bee_cfo_price_forecasts_status"),
        UniqueConstraint("report_id", "horizon_days", name="uq_mi_bee_cfo_price_forecasts_report_horizon"),
        Index("ix_mi_bee_cfo_price_forecasts_due", "assistant_id", "forecast_for", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False)
    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False)
    indicator_key: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    forecast_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_value: Mapped[float | None] = mapped_column(Numeric(24, 8))
    point_value: Mapped[float | None] = mapped_column(Numeric(24, 8))
    lower_value: Mapped[float | None] = mapped_column(Numeric(24, 8))
    upper_value: Mapped[float | None] = mapped_column(Numeric(24, 8))
    probability_up: Mapped[float] = mapped_column(Float, nullable=False)
    probability_down: Mapped[float] = mapped_column(Float, nullable=False)
    probability_flat: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="no_call")
    components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOPriceForecastEvaluation(Base):
    """Realized outcome used to measure error, coverage and calibration."""

    __tablename__ = "bee_cfo_price_forecast_evaluations"
    __table_args__ = (
        CheckConstraint("percentage_error IS NULL OR percentage_error >= 0", name="bee_cfo_price_forecast_evaluations_percentage_error"),
        CheckConstraint("brier_score IS NULL OR brier_score BETWEEN 0 AND 1", name="bee_cfo_price_forecast_evaluations_brier"),
        UniqueConstraint("forecast_id", name="uq_mi_bee_cfo_price_forecast_evaluations_forecast"),
        Index("ix_mi_bee_cfo_price_forecast_evaluations_assistant_date", "assistant_id", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    forecast_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_price_forecasts.id", ondelete="CASCADE"), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_value: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    absolute_error: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    percentage_error: Mapped[float | None] = mapped_column(Numeric(18, 8))
    direction_outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    direction_hit: Mapped[bool | None] = mapped_column(Boolean)
    interval_covered: Mapped[bool | None] = mapped_column(Boolean)
    brier_score: Mapped[float | None] = mapped_column(Float)
    actual_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    lesson: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BeeCFOAlert(Base):
    """Explainable change alert with deduplication and escalation state."""

    __tablename__ = "bee_cfo_alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'watch', 'important', 'critical')", name="bee_cfo_alerts_severity"),
        CheckConstraint("status IN ('open', 'sent', 'acknowledged', 'suppressed')", name="bee_cfo_alerts_status"),
        UniqueConstraint("assistant_id", "dedup_key", name="uq_mi_bee_cfo_alerts_dedup"),
        Index("ix_mi_bee_cfo_alerts_open", "assistant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.bee_cfo_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="watch")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="state_change")
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    delta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOAlertRule(Base):
    """Owner-configured Koyfin-style trigger; draft by default."""

    __tablename__ = "bee_cfo_alert_rules"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'paused')", name="bee_cfo_alert_rules_status"),
        UniqueConstraint("assistant_id", "watch_id", "rule_key", name="uq_mi_bee_cfo_alert_rules_key"),
        Index("ix_mi_bee_cfo_alert_rules_active", "assistant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False)
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    revision: Mapped[str] = mapped_column(String(64), nullable=False, default="bee-cfo-alerts-1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOMarketEvent(Base):
    """Deduplicated event ledger owned by a Bee CFO watch."""

    __tablename__ = "bee_cfo_market_events"
    __table_args__ = (
        UniqueConstraint("assistant_id", "event_key", name="uq_mi_bee_cfo_market_events_key"),
        Index("ix_mi_bee_cfo_market_events_watch_time", "assistant_id", "watch_id", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="SET NULL"))
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str | None] = mapped_column(Text)
    actual: Mapped[str | None] = mapped_column(Text)
    previous: Mapped[str | None] = mapped_column(Text)
    source_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_urls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="observed")
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOCoverageSnapshot(Base):
    """Completeness score for one immutable report."""

    __tablename__ = "bee_cfo_coverage_snapshots"
    __table_args__ = (UniqueConstraint("report_id", name="uq_mi_bee_cfo_coverage_snapshots_report"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False)
    indicator_key: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="insufficient")
    components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOMediaForecastEvaluation(Base):
    """Delayed 48h/7d media-outlook evaluation; no score before 20 samples."""

    __tablename__ = "bee_cfo_media_forecast_evaluations"
    __table_args__ = (
        UniqueConstraint("report_id", "source_key", "horizon_days", name="uq_mi_bee_cfo_media_eval_key"),
        Index("ix_mi_bee_cfo_media_eval_source", "assistant_id", "source_key", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    expected_stance: Mapped[str] = mapped_column(String(16), nullable=False)
    actual_direction: Mapped[str | None] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="not_evaluable")
    direction_hit: Mapped[bool | None] = mapped_column(Boolean)
    brier_score: Mapped[float | None] = mapped_column(Float)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BeeCFOMediaForecast(Base):
    """One article-level media statement; never collapsed to one row per outlet."""

    __tablename__ = "bee_cfo_media_forecasts"
    __table_args__ = (
        UniqueConstraint("report_id", "forecast_id", name="uq_mi_bee_cfo_media_forecast_key"),
        Index("ix_mi_bee_cfo_media_forecasts_source_horizon", "assistant_id", "source_key", "horizon_key", "published_at"),
        CheckConstraint("stance IN ('up', 'down', 'flat', 'unknown')", name="bee_cfo_media_forecasts_stance"),
        CheckConstraint("status IN ('active', 'expired', 'conflicted', 'syndicated')", name="bee_cfo_media_forecasts_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False)
    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_watches.id", ondelete="CASCADE"), nullable=False)
    forecast_id: Mapped[str] = mapped_column(String(64), nullable=False)
    article_id: Mapped[str] = mapped_column(String(64), nullable=False)
    statement_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    analyst_name: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    view: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text)
    stance: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    horizon_key: Mapped[str] = mapped_column(String(24), nullable=False, default="unspecified")
    horizon_label: Mapped[str] = mapped_column(String(80), nullable=False, default="بدون افق مشخص")
    horizon_days: Mapped[int | None] = mapped_column(SmallInteger)
    horizon_explicit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    conflict_status: Mapped[str] = mapped_column(String(32), nullable=False, default="clear")
    conflict_group: Mapped[str | None] = mapped_column(String(64))
    narrative_key: Mapped[str | None] = mapped_column(String(64))
    independence_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOMediaForecastOutcome(Base):
    """Article-level outcome ledger used for media/analyst/horizon scorecards."""

    __tablename__ = "bee_cfo_media_forecast_outcomes"
    __table_args__ = (
        UniqueConstraint("forecast_id", name="uq_mi_bee_cfo_media_outcome_forecast"),
        Index("ix_mi_bee_cfo_media_outcomes_source_horizon", "assistant_id", "source_key", "horizon_key", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False)
    forecast_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_media_forecasts.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    analyst_name: Mapped[str | None] = mapped_column(String(500))
    horizon_key: Mapped[str] = mapped_column(String(24), nullable=False)
    horizon_days: Mapped[int | None] = mapped_column(SmallInteger)
    expected_stance: Mapped[str] = mapped_column(String(16), nullable=False)
    actual_direction: Mapped[str | None] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="not_evaluable")
    direction_hit: Mapped[bool | None] = mapped_column(Boolean)
    brier_score: Mapped[float | None] = mapped_column(Float)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BeeCFOMediaWeightingAudit(Base):
    """Immutable audit trail for owner weighting scenarios and resets."""

    __tablename__ = "bee_cfo_media_weighting_audits"
    __table_args__ = (
        Index("ix_mi_bee_cfo_media_weighting_audits_assistant_created", "assistant_id", "created_at"),
        CheckConstraint("mode IN ('user_scenario', 'reset')", name="bee_cfo_media_weighting_audits_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    revision: Mapped[str] = mapped_column(String(64), nullable=False)
    weighting: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BeeCFOInfrastructureAudit(Base):
    """Recorded reuse decision and isolation evidence for the project."""

    __tablename__ = "bee_cfo_infrastructure_audits"
    __table_args__ = (
        UniqueConstraint("assistant_id", name="uq_mi_bee_cfo_infrastructure_audits_assistant"),
        CheckConstraint("status IN ('passed', 'blocked')", name="bee_cfo_infrastructure_audits_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    isolation_contract: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BeeCFOGovernanceEvent(Base):
    """Append-only governance evidence for the post-phase-one Bee CFO work.

    The table contains configuration and verification metadata only.  It never
    stores a customer's holdings, goals, identity attributes, or advice.
    """

    __tablename__ = "bee_cfo_governance_events"
    __table_args__ = (
        CheckConstraint(
            "category IN ('pilot_run', 'source_decision', 'source_revalidation', 'provider_contract', 'capacity', 'canary', 'shadow_run', 'attention', 'why_changed', 'privacy_boundary')",
            name="bee_cfo_governance_events_category",
        ),
        CheckConstraint(
            "status IN ('recorded', 'passed', 'failed', 'draft', 'approved', 'rejected', 'expired', 'eligible', 'suppressed', 'served')",
            name="bee_cfo_governance_events_status",
        ),
        Index("ix_mi_bee_cfo_governance_events_assistant_category_created", "assistant_id", "category", "created_at"),
        Index("ix_mi_bee_cfo_governance_events_lookup", "assistant_id", "category", "event_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    event_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
