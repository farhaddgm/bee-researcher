from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, SCHEMA


class TokenLimit(Base):
    __tablename__ = 'reader_token_limits'
    __table_args__ = (
        CheckConstraint("(id = 'default' AND assistant_id IS NULL AND user_id IS NULL AND NOT inherit) OR "
                        "(assistant_id IS NOT NULL AND user_id IS NULL AND id = 'project:' || assistant_id::text) OR "
                        "(assistant_id IS NOT NULL AND user_id IS NOT NULL AND id = 'user:' || assistant_id::text || ':' || user_id::text)",
                        name='reader_token_limit_scope'),
        CheckConstraint('version > 0', name='reader_token_limit_version'),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.assistant_workspaces.id', ondelete='CASCADE'))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.admin_users.id', ondelete='CASCADE'))
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    inherit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f'{SCHEMA}.admin_users.id', ondelete='SET NULL'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
