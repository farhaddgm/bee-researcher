from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, SCHEMA


class Lens(Base):
    __tablename__ = 'analysis_lenses'
    __table_args__ = (ForeignKeyConstraint(['id', 'active_revision'], [f'{SCHEMA}.analysis_lens_revisions.lens_id', f'{SCHEMA}.analysis_lens_revisions.revision'], name='analysis_lens_active_revision', use_alter=True),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    active_revision: Mapped[int | None] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Revision(Base):
    __tablename__ = 'analysis_lens_revisions'
    __table_args__ = (UniqueConstraint('lens_id', 'revision', name='uq_analysis_lens_revision'), CheckConstraint("status IN ('draft','published','revoked')", name='analysis_lens_revision_status'))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lens_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.analysis_lenses.id', ondelete='CASCADE'))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='draft', nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.admin_users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LensPolicy(Base):
    __tablename__ = 'analysis_lens_policy'
    __table_args__ = (CheckConstraint('id = 1', name='analysis_lens_policy_singleton'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)


class DiscoverySnapshot(Base):
    __tablename__ = 'analysis_discovery_snapshots'
    __table_args__ = (Index('ix_analysis_discovery_expiry', 'expires_at'),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.admin_users.id', ondelete='CASCADE'))
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.assistant_workspaces.id', ondelete='CASCADE'))
    publication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.publications.id', ondelete='CASCADE'))
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PreviewRun(Base):
    __tablename__ = 'analysis_lens_preview_runs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.admin_users.id', ondelete='SET NULL'))
    lens_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.analysis_lenses.id', ondelete='CASCADE'))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.news_chat_conversations.id', ondelete='SET NULL'))
    generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.news_chat_generations.id', ondelete='SET NULL'))
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Audit(Base):
    __tablename__ = 'analysis_lens_audit'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.admin_users.id', ondelete='SET NULL'))
    lens_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.analysis_lenses.id', ondelete='CASCADE'))
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    definition_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
