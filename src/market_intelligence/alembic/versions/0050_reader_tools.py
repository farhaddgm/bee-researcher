"""Add correction evidence and explicit expert threads; preserve all accounts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision = '0050_reader_tools'
down_revision = '0049_reader_voice'
branch_labels = depends_on = None
S = 'market_intelligence'


def uid(name, target=None, primary=False, nullable=False):
    args = [name, pg.UUID(as_uuid=True)]
    if target:
        args.append(sa.ForeignKey(f'{S}.{target}.id', ondelete='CASCADE'))
    return sa.Column(*args, primary_key=primary, nullable=nullable)


def stamp(name, nullable=False, default=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def upgrade():
    op.drop_constraint('reader_research_kind', 'reader_research_records', schema=S, type_='check')
    op.create_check_constraint('reader_research_kind', 'reader_research_records',
        "kind IN ('topic','watch','action','decision','shared','meeting')", schema=S)
    op.add_column('reader_research_records', sa.Column('source_versions', pg.JSONB(), nullable=False,
        server_default=sa.text("'{}'::jsonb")), schema=S)
    op.add_column('reader_research_records', sa.Column('source_generation_id', pg.UUID(as_uuid=True), nullable=True), schema=S)
    op.create_foreign_key('fk_reader_record_generation', 'reader_research_records', 'news_chat_generations', ['source_generation_id'], ['id'], source_schema=S, referent_schema=S, ondelete='SET NULL')
    op.create_table('reader_news_monitors', uid('publication_id', 'publications', primary=True),
        uid('assistant_id', 'assistant_workspaces'), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('report_hash', sa.String(64), nullable=False), sa.Column('report_text', sa.Text(), nullable=False),
        sa.Column('source_hash', sa.String(64)), sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('source_title', sa.Text(), nullable=False),
        sa.Column('report_complete', sa.Boolean(), nullable=False), sa.Column('source_complete', sa.Boolean(), nullable=False),
        stamp('created_at', default=True), stamp('checked_at', nullable=True), stamp('next_check_at'),
        uid('lease_token', nullable=True), stamp('lease_until', nullable=True),
        sa.Column('check_status', sa.String(32), nullable=False), schema=S)
    op.create_index('ix_reader_news_due', 'reader_news_monitors', ['next_check_at','publication_id'], schema=S)
    op.create_table('reader_news_revisions', uid('id', primary=True), uid('publication_id','publications'),
        uid('assistant_id','assistant_workspaces'), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(16), nullable=False), sa.Column('before_hash', sa.String(64), nullable=False),
        sa.Column('after_hash', sa.String(64), nullable=False), sa.Column('before_text', sa.Text(), nullable=False),
        sa.Column('after_text', sa.Text(), nullable=False), sa.Column('title', sa.Text(), nullable=False),
        sa.Column('notice', sa.String(24), nullable=False), sa.Column('complete', sa.Boolean(), nullable=False),
        stamp('created_at', default=True), sa.CheckConstraint("channel IN ('report','source')", name='reader_revision_channel'),
        sa.UniqueConstraint('publication_id','version',name='uq_reader_revision_version'), schema=S)
    op.create_index('ix_reader_revision_page','reader_news_revisions',['publication_id','version'],schema=S)
    op.create_table('reader_news_watches', uid('user_id','admin_users',primary=True),
        uid('publication_id','publications',primary=True), uid('assistant_id','assistant_workspaces'),
        sa.Column('enabled',sa.Boolean(),nullable=False), sa.Column('seen_version',sa.Integer(),nullable=False),
        stamp('created_at',default=True),schema=S)
    op.create_index('ix_reader_watch_owner','reader_news_watches',['user_id','assistant_id'],schema=S)
    op.create_table('reader_expert_requests', uid('id',primary=True),uid('assistant_id','assistant_workspaces'),
        uid('requester_id','admin_users'),uid('assignee_id','admin_users'),
        sa.Column('title',sa.String(180),nullable=False),sa.Column('question',sa.Text(),nullable=False),
        sa.Column('excerpt',sa.Text(),nullable=False),sa.Column('publication_ids',pg.JSONB(),nullable=False),
        sa.Column('source_versions',pg.JSONB(),nullable=False),sa.Column('status',sa.String(16),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('requester_seen',sa.Integer(),nullable=False),
        sa.Column('assignee_seen',sa.Integer(),nullable=False),stamp('created_at',default=True),stamp('updated_at',default=True),
        sa.CheckConstraint("status IN ('open','answered','closed','cancelled')",name='reader_expert_status'),
        sa.CheckConstraint('requester_id <> assignee_id',name='reader_expert_colleague'),schema=S)
    op.create_index('ix_reader_expert_inbox','reader_expert_requests',['assistant_id','created_at','id'],schema=S)
    op.create_table('reader_expert_replies',uid('id',primary=True),uid('request_id','reader_expert_requests'),
        uid('author_id','admin_users'),sa.Column('body',sa.Text(),nullable=False),stamp('created_at',default=True),schema=S)
    op.create_index('ix_reader_expert_thread','reader_expert_replies',['request_id','created_at','id'],schema=S)
    op.execute(sa.text(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bee_researcher_runtime') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON {S}.reader_news_monitors,{S}.reader_news_watches,{S}.reader_expert_requests TO bee_researcher_runtime;
        GRANT SELECT,INSERT ON {S}.reader_news_revisions,{S}.reader_expert_replies TO bee_researcher_runtime;
        REVOKE UPDATE,DELETE,TRUNCATE ON {S}.reader_news_revisions,{S}.reader_expert_replies FROM bee_researcher_runtime;
      END IF;
    END $$"""))


def downgrade():
    raise RuntimeError('Retain source revision evidence and expert replies during application rollback')
