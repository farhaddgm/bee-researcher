from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, SCHEMA


class ResearchProfile(Base):
    __tablename__ = "reader_research_profiles"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="CASCADE"), primary_key=True)
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchRecord(Base):
    __tablename__ = "reader_research_records"
    __table_args__ = (
        CheckConstraint("kind IN ('topic','watch','action','decision','shared')", name="reader_research_kind"),
        CheckConstraint("version > 0", name="reader_research_version"),
        Index("ix_reader_research_page", "assistant_id", "kind", "created_at", "id"),
        Index("ix_reader_research_owner", "user_id", "assistant_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.admin_users.id", ondelete="CASCADE"))
    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assistant_workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    publication_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.news_chat_conversations.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
