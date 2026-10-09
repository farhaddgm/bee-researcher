from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, SCHEMA


class ChatPolicy(Base):
    __tablename__ = "news_chat_policy"
    __table_args__ = (CheckConstraint("id = 1", name="news_chat_policy_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class ChatConversation(Base):
    __tablename__ = "news_chat_conversations"
    __table_args__ = (Index("ix_news_chat_thread_page", "user_id", "publication_id", "created_at", "id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="CASCADE"), index=True)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"))
    publication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.publications.id", ondelete="CASCADE"))
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatGeneration(Base):
    __tablename__ = "news_chat_generations"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','stopped','failed','unknown')", name="news_chat_status"),
        CheckConstraint("reserved_usd >= 0 AND (actual_usd IS NULL OR actual_usd >= 0)", name="news_chat_cost"),
        Index("uq_news_chat_idempotency", "user_id", "idempotency_key", unique=True),
        Index("uq_news_chat_active_user", "user_id", unique=True, postgresql_where=text("status IN ('queued','running')")),
        Index("ix_news_chat_created", "created_at"),
        Index("ix_news_chat_history_page", "conversation_id", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.news_chat_conversations.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="SET NULL"))
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    session_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    model: Mapped[dict] = mapped_column(JSONB, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feedback: Mapped[int | None] = mapped_column(Integer)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
