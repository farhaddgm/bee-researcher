"""Private reader chat and independent consumption ledger, opt-in only."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0045_news_chat"
down_revision = "0044_security_events"
branch_labels = depends_on = None
S = "market_intelligence"


def upgrade():
    # Frozen migration: independent of future ORM changes. This schema only.
    op.create_table('news_chat_policy', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('config', pg.JSONB(), nullable=False), sa.CheckConstraint('id = 1', name='news_chat_policy_singleton'), schema=S)
    op.create_table('news_chat_conversations',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assistant_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.assistant_workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('publication_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.publications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('context', pg.JSONB(), nullable=False), sa.Column('provider', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column('deleted_at', sa.DateTime(timezone=True)), schema=S)
    op.create_index('ix_mi_news_chat_conversations_user_id', 'news_chat_conversations', ['user_id'], schema=S)
    op.create_index('ix_news_chat_thread_page', 'news_chat_conversations', ['user_id', 'publication_id', 'created_at', 'id'], schema=S)
    op.create_table('news_chat_generations',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.news_chat_conversations.id', ondelete='SET NULL')),
        sa.Column('user_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='SET NULL')),
        sa.Column('assistant_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.assistant_workspaces.id', ondelete='SET NULL')),
        sa.Column('idempotency_key', sa.String(64), nullable=False), sa.Column('session_hash', sa.String(128), nullable=False),
        sa.Column('question', sa.Text(), nullable=False), sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('language', sa.String(8), nullable=False), sa.Column('model', pg.JSONB(), nullable=False), sa.Column('citations', pg.JSONB(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('error_code', sa.String(64)), sa.Column('cancel_requested', sa.Boolean(), nullable=False), sa.Column('feedback', sa.Integer()),
        sa.Column('reserved_usd', sa.Numeric(18,8), nullable=False), sa.Column('actual_usd', sa.Numeric(18,8)), sa.Column('usage', pg.JSONB(), nullable=False),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('queued','running','completed','stopped','failed','unknown')", name='news_chat_status'),
        sa.CheckConstraint('reserved_usd >= 0 AND (actual_usd IS NULL OR actual_usd >= 0)', name='news_chat_cost'), schema=S)
    op.create_index('ix_mi_news_chat_generations_conversation_id', 'news_chat_generations', ['conversation_id'], schema=S)
    op.create_index('ix_news_chat_created', 'news_chat_generations', ['created_at'], schema=S)
    op.create_index('ix_news_chat_history_page', 'news_chat_generations', ['conversation_id', 'created_at', 'id'], schema=S)
    op.create_index('uq_news_chat_idempotency', 'news_chat_generations', ['user_id', 'idempotency_key'], unique=True, schema=S)
    op.create_index('uq_news_chat_active_user', 'news_chat_generations', ['user_id'], unique=True, schema=S, postgresql_where=sa.text("status IN ('queued','running')"))
    # Cascading account/project/article deletion must not orphan private text
    # in the retained, financial generation ledger.
    op.execute(sa.text(f"""CREATE FUNCTION {S}.clear_deleted_news_chat() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          UPDATE {S}.news_chat_generations SET question='', answer='', citations='[]'::jsonb,
            cancel_requested=true, session_hash=''
          WHERE conversation_id=OLD.id;
          RETURN OLD;
        END $$"""))
    op.execute(sa.text(f"CREATE TRIGGER clear_deleted_news_chat BEFORE DELETE ON {S}.news_chat_conversations FOR EACH ROW EXECUTE FUNCTION {S}.clear_deleted_news_chat()"))
    op.execute(sa.text(f"INSERT INTO {S}.news_chat_policy(id,config) VALUES (1,'{{}}'::jsonb)"))


def downgrade():
    raise RuntimeError("Disable news_chat_enabled; preserve private history and usage on rollback")
