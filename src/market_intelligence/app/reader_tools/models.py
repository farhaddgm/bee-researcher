from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, SCHEMA


def ref(target):
    return ForeignKey(f'{SCHEMA}.{target}.id', ondelete='CASCADE')


class NewsMonitor(Base):
    __tablename__ = 'reader_news_monitors'
    publication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('publications'), primary_key=True)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('assistant_workspaces'))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    report_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_hash: Mapped[str | None] = mapped_column(String(64))
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default='')
    source_title: Mapped[str] = mapped_column(Text, nullable=False, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    __table_args__ = (Index('ix_reader_news_due', 'next_check_at', 'publication_id'),)


class NewsRevision(Base):
    __tablename__ = 'reader_news_revisions'
    __table_args__ = (CheckConstraint("channel IN ('report','source')", name='reader_revision_channel'),
        Index('ix_reader_revision_page', 'publication_id', 'version'),
        UniqueConstraint('publication_id','version',name='uq_reader_revision_version'))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('publications'))
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('assistant_workspaces'))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    before_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    after_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    before_text: Mapped[str] = mapped_column(Text, nullable=False)
    after_text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    notice: Mapped[str] = mapped_column(String(24), nullable=False, default='changed')
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsWatch(Base):
    __tablename__ = 'reader_news_watches'
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('admin_users'), primary_key=True)
    publication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('publications'), primary_key=True)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('assistant_workspaces'))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    seen_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index('ix_reader_watch_owner', 'user_id', 'assistant_id'),)


class ExpertRequest(Base):
    __tablename__ = 'reader_expert_requests'
    __table_args__ = (CheckConstraint("status IN ('open','answered','closed','cancelled')", name='reader_expert_status'),
        CheckConstraint('requester_id <> assignee_id', name='reader_expert_colleague'),
        Index('ix_reader_expert_inbox', 'assistant_id', 'created_at', 'id'),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('assistant_workspaces'))
    requester_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('admin_users'))
    assignee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('admin_users'))
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default='')
    publication_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    source_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='open')
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requester_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assignee_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpertReply(Base):
    __tablename__ = 'reader_expert_replies'
    __table_args__ = (Index('ix_reader_expert_thread', 'request_id', 'created_at', 'id'),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('reader_expert_requests'))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ref('admin_users'))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
