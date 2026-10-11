import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, SCHEMA


def uid(target=None, nullable=False, cascade='CASCADE', primary=False):
    args=[UUID(as_uuid=True)]
    if target: args.append(ForeignKey(f'{SCHEMA}.{target}.id', ondelete=cascade))
    return mapped_column(*args, nullable=nullable, primary_key=primary, default=uuid.uuid4 if primary else None)


class VoicePolicy(Base):
    __tablename__='reader_voice_policy'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class VoiceSession(Base):
    __tablename__='reader_voice_sessions'
    __table_args__=(Index('uq_voice_session_request','user_id','idempotency_key',unique=True),
        Index('uq_voice_session_active','user_id',unique=True,postgresql_where=text("status IN ('created','running')")),)
    id: Mapped[uuid.UUID] = uid(primary=True)
    user_id: Mapped[uuid.UUID] = uid('admin_users')
    assistant_id: Mapped[uuid.UUID] = uid('assistant_workspaces')
    conversation_id: Mapped[uuid.UUID] = uid('news_chat_conversations')
    usage_id: Mapped[uuid.UUID] = uid('reader_voice_usage')
    idempotency_key: Mapped[str] = mapped_column(String(64))
    session_hash: Mapped[str] = mapped_column(String(128))
    ticket_hash: Mapped[str] = mapped_column(String(64))
    ticket_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default='created')
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    transcript: Mapped[str] = mapped_column(Text, default='')
    generation_id: Mapped[uuid.UUID | None] = uid('news_chat_generations',nullable=True,cascade='SET NULL')
    audio_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceUsage(Base):
    __tablename__='reader_voice_usage'
    __table_args__=(Index('ix_voice_usage_day','created_at'),Index('uq_voice_usage_request','user_id','idempotency_key',unique=True),)
    id: Mapped[uuid.UUID] = uid(primary=True)
    user_id: Mapped[uuid.UUID | None] = uid('admin_users',nullable=True,cascade='SET NULL')
    assistant_id: Mapped[uuid.UUID | None] = uid('assistant_workspaces',nullable=True,cascade='SET NULL')
    conversation_id: Mapped[uuid.UUID | None] = uid('news_chat_conversations',nullable=True,cascade='SET NULL')
    idempotency_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16),default='reserved')
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(18,8))
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric(18,8))
    units: Mapped[Decimal] = mapped_column(Numeric(18,4),default=0)
    price: Mapped[dict] = mapped_column(JSONB,default=dict)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())


class VoiceAudio(Base):
    __tablename__='reader_voice_audio'
    __table_args__=(Index('uq_voice_audio_identity','user_id','assistant_id','identity',unique=True),
        Index('ix_voice_audio_memory','user_id','assistant_id','saved_at','id'),)
    id: Mapped[uuid.UUID] = uid(primary=True)
    user_id: Mapped[uuid.UUID] = uid('admin_users')
    assistant_id: Mapped[uuid.UUID] = uid('assistant_workspaces')
    conversation_id: Mapped[uuid.UUID] = uid('news_chat_conversations')
    generation_id: Mapped[uuid.UUID | None] = uid('news_chat_generations',nullable=True,cascade='SET NULL')
    usage_id: Mapped[uuid.UUID | None] = uid('reader_voice_usage',nullable=True,cascade='SET NULL')
    identity: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16),default='preparing')
    title: Mapped[str] = mapped_column(String(180),default='')
    object_key: Mapped[str | None] = mapped_column(String(36))
    sha256: Mapped[str | None] = mapped_column(String(64))
    byte_count: Mapped[int] = mapped_column(Integer,default=0)
    duration_ms: Mapped[int] = mapped_column(Integer,default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB,default=dict)
    version: Mapped[int] = mapped_column(Integer,default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())


class VoiceSegment(Base):
    __tablename__='reader_voice_segments'
    id: Mapped[uuid.UUID] = uid(primary=True)
    asset_id: Mapped[uuid.UUID] = uid('reader_voice_audio')
    generation_id: Mapped[uuid.UUID | None] = uid('news_chat_generations',nullable=True,cascade='SET NULL')
    position: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(8))
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict] = mapped_column(JSONB,default=dict)


class VoiceSaveJob(Base):
    __tablename__='reader_voice_save_jobs'
    __table_args__=(Index('uq_voice_save_request','user_id','idempotency_key',unique=True),)
    id: Mapped[uuid.UUID] = uid(primary=True)
    user_id: Mapped[uuid.UUID] = uid('admin_users')
    assistant_id: Mapped[uuid.UUID] = uid('assistant_workspaces')
    conversation_id: Mapped[uuid.UUID] = uid('news_chat_conversations')
    asset_id: Mapped[uuid.UUID | None] = uid('reader_voice_audio',nullable=True,cascade='SET NULL')
    idempotency_key: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16),default='preparing')
    error_code: Mapped[str | None] = mapped_column(String(64))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB,default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())


class VoiceDeletion(Base):
    __tablename__='reader_voice_deletion_outbox'
    id: Mapped[uuid.UUID] = uid(primary=True)
    # No FK: work must survive cascading parent/account deletion.
    object_key: Mapped[str] = mapped_column(String(36),unique=True)
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    status: Mapped[str] = mapped_column(String(16),default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())
