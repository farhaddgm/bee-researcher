"""Frozen, additive reader audio; independent storage and deletion outbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision='0049_reader_voice'
down_revision='0048_reader_research'
branch_labels=depends_on=None
S='market_intelligence'


def uid(name, target=None, nullable=False, primary=False, ondelete='CASCADE'):
    args=[name,pg.UUID(as_uuid=True)]
    if target: args.append(sa.ForeignKey(f'{S}.{target}.id',ondelete=ondelete))
    return sa.Column(*args,nullable=nullable,primary_key=primary)


def string(name, size, nullable=False):return sa.Column(name,sa.String(size),nullable=nullable)
def timestamp(name, nullable=False):return sa.Column(name,sa.DateTime(timezone=True),nullable=nullable)
def js(name):return sa.Column(name,pg.JSONB(),nullable=False)
def created():return sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now())
def owner():return [uid('user_id','admin_users'),uid('assistant_id','assistant_workspaces'),uid('conversation_id','news_chat_conversations')]


def upgrade():
    op.create_table('reader_voice_policy',sa.Column('id',sa.Integer(),primary_key=True),js('config'),
        sa.CheckConstraint('id = 1',name='voice_policy_singleton'),schema=S)
    op.create_table('reader_voice_usage',uid('id',primary=True),
        uid('user_id','admin_users',nullable=True,ondelete='SET NULL'),
        uid('assistant_id','assistant_workspaces',nullable=True,ondelete='SET NULL'),
        uid('conversation_id','news_chat_conversations',nullable=True,ondelete='SET NULL'),
        string('idempotency_key',64),string('kind',8),string('status',16),
        sa.Column('reserved_usd',sa.Numeric(18,8),nullable=False),sa.Column('actual_usd',sa.Numeric(18,8)),
        sa.Column('units',sa.Numeric(18,4),nullable=False),js('price'),timestamp('deadline'),created(),
        sa.CheckConstraint("kind IN ('stt','tts')",name='voice_usage_kind'),
        sa.CheckConstraint('reserved_usd >= 0 AND (actual_usd IS NULL OR actual_usd >= 0) AND units >= 0',name='voice_usage_cost'),schema=S)
    op.create_index('ix_voice_usage_day','reader_voice_usage',['created_at'],schema=S)
    op.create_index('uq_voice_usage_request','reader_voice_usage',['user_id','idempotency_key'],unique=True,schema=S)
    op.create_table('reader_voice_sessions',uid('id',primary=True),*owner(),uid('usage_id','reader_voice_usage'),
        string('idempotency_key',64),string('session_hash',128),string('ticket_hash',64),
        timestamp('ticket_expires_at'),timestamp('deadline'),string('status',16),js('config'),
        sa.Column('transcript',sa.Text(),nullable=False),
        uid('generation_id','news_chat_generations',nullable=True,ondelete='SET NULL'),uid('audio_id',nullable=True),created(),schema=S)
    op.create_index('uq_voice_session_request','reader_voice_sessions',['user_id','idempotency_key'],unique=True,schema=S)
    op.create_index('uq_voice_session_active','reader_voice_sessions',['user_id'],unique=True,
        postgresql_where=sa.text("status IN ('created','running')"),schema=S)
    op.create_table('reader_voice_audio',uid('id',primary=True),*owner(),
        uid('generation_id','news_chat_generations',nullable=True,ondelete='SET NULL'),
        uid('usage_id','reader_voice_usage',nullable=True,ondelete='SET NULL'),string('identity',64),
        string('scope',16),string('status',16),string('title',180),string('object_key',36,True),string('sha256',64,True),
        sa.Column('byte_count',sa.Integer(),nullable=False),sa.Column('duration_ms',sa.Integer(),nullable=False),
        js('metadata_json'),sa.Column('version',sa.Integer(),nullable=False),timestamp('expires_at'),
        timestamp('saved_at',True),timestamp('deleted_at',True),created(),
        sa.CheckConstraint('byte_count >= 0 AND duration_ms >= 0 AND version >= 0',name='voice_audio_size'),schema=S)
    op.create_index('uq_voice_audio_identity','reader_voice_audio',['user_id','assistant_id','identity'],unique=True,schema=S)
    op.create_index('ix_voice_audio_memory','reader_voice_audio',['user_id','assistant_id','saved_at','id'],schema=S)
    op.create_table('reader_voice_segments',uid('id',primary=True),uid('asset_id','reader_voice_audio'),
        uid('generation_id','news_chat_generations',nullable=True,ondelete='SET NULL'),
        sa.Column('position',sa.Integer(),nullable=False),string('speaker',8),
        sa.Column('start_ms',sa.Integer(),nullable=False),sa.Column('end_ms',sa.Integer(),nullable=False),js('manifest'),schema=S)
    op.create_table('reader_voice_save_jobs',uid('id',primary=True),*owner(),
        uid('asset_id','reader_voice_audio',nullable=True,ondelete='SET NULL'),string('idempotency_key',64),
        string('payload_hash',64),string('status',16),string('error_code',64,True),timestamp('deadline'),js('payload'),created(),schema=S)
    op.create_index('uq_voice_save_request','reader_voice_save_jobs',['user_id','idempotency_key'],unique=True,schema=S)
    op.create_table('reader_voice_deletion_outbox',uid('id',primary=True),string('object_key',36),
        sa.Column('attempts',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('status',sa.String(16),nullable=False,server_default='pending'),created(),
        sa.UniqueConstraint('object_key',name='uq_voice_delete_object'),schema=S)
    # Database cascade must enqueue byte cleanup even if the deleting caller
    # belongs to an older app or deletes a user/publication directly.
    op.execute(sa.text(f"""CREATE FUNCTION {S}.reader_voice_enqueue_delete() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.object_key IS NOT NULL THEN
        INSERT INTO {S}.reader_voice_deletion_outbox(id,object_key,attempts,status)
        VALUES(gen_random_uuid(),OLD.object_key,0,'pending') ON CONFLICT(object_key) DO NOTHING;
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$"""))
    op.execute(sa.text(f"""CREATE TRIGGER reader_voice_delete BEFORE DELETE ON {S}.reader_voice_audio
        FOR EACH ROW EXECUTE FUNCTION {S}.reader_voice_enqueue_delete()"""))
    op.execute(sa.text(f"""CREATE TRIGGER reader_voice_tombstone BEFORE UPDATE ON {S}.reader_voice_audio
        FOR EACH ROW WHEN (OLD.object_key IS DISTINCT FROM NEW.object_key OR
          (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL))
        EXECUTE FUNCTION {S}.reader_voice_enqueue_delete()"""))
    op.execute(sa.text(f"""CREATE FUNCTION {S}.reader_voice_memory_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.saved_at IS NULL AND OLD.saved_at IS NOT NULL AND EXISTS
        (SELECT 1 FROM {S}.reader_voice_audio WHERE conversation_id=OLD.id AND saved_at IS NOT NULL AND deleted_at IS NULL) THEN
        RAISE EXCEPTION 'audio_removal_confirmation_required';
      END IF;
      RETURN NEW;
    END $$"""))
    op.execute(sa.text(f"""CREATE TRIGGER reader_voice_memory_guard BEFORE UPDATE ON {S}.news_chat_conversations
      FOR EACH ROW EXECUTE FUNCTION {S}.reader_voice_memory_guard()"""))
    tables=['reader_voice_policy','reader_voice_usage','reader_voice_sessions','reader_voice_audio',
            'reader_voice_segments','reader_voice_save_jobs','reader_voice_deletion_outbox']
    op.execute(sa.text("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bee_researcher_runtime') THEN GRANT SELECT,INSERT,UPDATE,DELETE ON " +
        ','.join(f'{S}.{t}' for t in tables)+" TO bee_researcher_runtime; END IF; END $$"))


def downgrade():raise RuntimeError('Retain audio, cleanup outbox and billing on application rollback')
