"""Reader research; frozen additive schema, no grants or business consent changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0048_reader_research'
down_revision = '0047_project_chat_memory'
branch_labels = depends_on = None
S = 'market_intelligence'


def uid(name, target=None, primary=False, nullable=False, ondelete='CASCADE'):
    args = [name, pg.UUID(as_uuid=True)]
    if target:
        args.append(sa.ForeignKey(f'{S}.{target}.id', ondelete=ondelete))
    return sa.Column(*args, primary_key=primary, nullable=nullable)


def upgrade():
    op.create_table('reader_research_profiles', uid('user_id', 'admin_users', primary=True),
        uid('assistant_id', 'assistant_workspaces', primary=True),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('settings', pg.JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), schema=S)
    op.create_table('reader_research_records', uid('id', primary=True), uid('user_id', 'admin_users'),
        uid('assistant_id', 'assistant_workspaces'), sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('title', sa.String(180), nullable=False), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('attributes', pg.JSONB(), nullable=False), sa.Column('publication_ids', pg.JSONB(), nullable=False),
        uid('conversation_id', 'news_chat_conversations', nullable=True, ondelete='SET NULL'),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('topic','watch','action','decision','shared')", name='reader_research_kind'),
        sa.CheckConstraint('version > 0', name='reader_research_version'), schema=S)
    op.create_index('ix_reader_research_page', 'reader_research_records', ['assistant_id','kind','created_at','id'], schema=S)
    op.create_index('ix_reader_research_owner', 'reader_research_records', ['user_id','assistant_id'], schema=S)
    op.execute(sa.text(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bee_researcher_runtime') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON {S}.reader_research_profiles,{S}.reader_research_records TO bee_researcher_runtime;
      END IF;
    END $$"""))


def downgrade():
    raise RuntimeError('Preserve reader decisions, actions and tracking; application rollback must retain schema')
