"""Add bounded, versioned analysis lenses; additive forward-schema rollback."""
import json
import uuid
from pathlib import Path
import hashlib

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0052_analysis_lenses'
down_revision = '0051_token_quotas'
branch_labels = depends_on = None
S = 'market_intelligence'


def upgrade():
    op.create_table('analysis_lenses', sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('key', sa.String(60), nullable=False, unique=True), sa.Column('active_revision', sa.Integer()),
        sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), schema=S)
    op.create_table('analysis_lens_revisions', sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('lens_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.analysis_lenses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('definition', pg.JSONB(), nullable=False),
        sa.Column('definition_hash', sa.String(64), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('actor_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('lens_id', 'revision', name='uq_analysis_lens_revision'),
        sa.CheckConstraint("status IN ('draft','published','revoked')", name='analysis_lens_revision_status'), schema=S)
    op.create_foreign_key('analysis_lens_active_revision', 'analysis_lenses', 'analysis_lens_revisions',
        ['id', 'active_revision'], ['lens_id', 'revision'], source_schema=S, referent_schema=S)
    op.create_table('analysis_lens_policy', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('config', pg.JSONB(), nullable=False), sa.CheckConstraint('id = 1', name='analysis_lens_policy_singleton'), schema=S)
    op.create_table('analysis_discovery_snapshots', sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assistant_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.assistant_workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('publication_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.publications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('data', pg.JSONB(), nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False), schema=S)
    op.create_index('ix_analysis_discovery_expiry', 'analysis_discovery_snapshots', ['expires_at'], schema=S)
    op.create_table('analysis_lens_preview_runs', sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('actor_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='SET NULL')),
        sa.Column('lens_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.analysis_lenses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('definition_hash', sa.String(64), nullable=False),
        sa.Column('conversation_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.news_chat_conversations.id', ondelete='SET NULL')),
        sa.Column('generation_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.news_chat_generations.id', ondelete='SET NULL')),
        sa.Column('source_version', sa.String(64), nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False), schema=S)
    op.create_table('analysis_lens_audit', sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('actor_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='SET NULL')),
        sa.Column('lens_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.analysis_lenses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(30), nullable=False), sa.Column('definition_hash', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), schema=S)
    op.add_column('news_chat_generations', sa.Column('analysis_result', pg.JSONB()), schema=S)
    op.add_column('news_chat_generations', sa.Column('audience', sa.String(20), nullable=False, server_default='reader'), schema=S)
    op.create_check_constraint('news_chat_audience', 'news_chat_generations', "audience IN ('reader','owner_preview')", schema=S)
    # Version-one seed is immutable and deterministic; it never resets edits.
    seed = json.loads(Path(__file__).with_name('0052_analysis_lenses_seed.json').read_text(encoding='utf-8'))
    namespace = uuid.UUID(seed['namespace'])
    lenses = sa.table('analysis_lenses', sa.column('id', pg.UUID(as_uuid=True)), sa.column('key', sa.String(60)), sa.column('active_revision', sa.Integer()), schema=S)
    revisions = sa.table('analysis_lens_revisions', sa.column('id', pg.UUID(as_uuid=True)), sa.column('lens_id', pg.UUID(as_uuid=True)),
        sa.column('revision', sa.Integer()), sa.column('definition', pg.JSONB()), sa.column('definition_hash', sa.String(64)), sa.column('status', sa.String(16)), schema=S)
    for entry in seed['definitions']:
        key, definition = entry['key'], entry['definition']
        lid = uuid.uuid5(namespace, key)
        op.bulk_insert(lenses, [{'id': lid, 'key': key, 'active_revision': None}])
        definition_hash = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        op.bulk_insert(revisions, [{'id': uuid.uuid5(namespace, key + ':1'), 'lens_id': lid, 'revision': 1,
            'definition': op.inline_literal(json.dumps(definition, ensure_ascii=False)),
            'definition_hash': definition_hash, 'status': 'published'}], multiinsert=False)
        op.execute(lenses.update().where(lenses.c.id == lid).values(active_revision=1))
    policy = sa.table('analysis_lens_policy', sa.column('id', sa.Integer()), sa.column('config', pg.JSONB()), schema=S)
    op.bulk_insert(policy, [{'id': 1, 'config': op.inline_literal('{"enabled":false,"default_key":"general","version":1}')}], multiinsert=False)
    op.execute(sa.text(f"""CREATE FUNCTION {S}.analysis_generation_clear() RETURNS trigger
      LANGUAGE plpgsql SET search_path = pg_catalog AS $$
      BEGIN
        IF NEW.conversation_id IS NULL OR (NEW.answer = '' AND NEW.cancel_requested) THEN
          NEW.analysis_result := NULL;
        END IF;
        RETURN NEW;
      END $$"""))
    op.execute(sa.text(f"CREATE TRIGGER analysis_generation_clear BEFORE UPDATE ON {S}.news_chat_generations FOR EACH ROW EXECUTE FUNCTION {S}.analysis_generation_clear()"))
    op.execute(sa.text(f"""CREATE FUNCTION {S}.analysis_revision_immutable() RETURNS trigger
      LANGUAGE plpgsql SET search_path = pg_catalog AS $$
      BEGIN
        IF OLD.status IN ('published','revoked') AND
           (NEW.definition IS DISTINCT FROM OLD.definition OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash
            OR NEW.lens_id IS DISTINCT FROM OLD.lens_id OR NEW.revision IS DISTINCT FROM OLD.revision
            OR (OLD.status = 'revoked' AND NEW.status <> 'revoked')
            OR (OLD.status = 'published' AND NEW.status NOT IN ('published','revoked'))) THEN
          RAISE EXCEPTION 'published lens revision is immutable';
        END IF;
        RETURN NEW;
      END $$"""))
    op.execute(sa.text(f"CREATE TRIGGER analysis_revision_immutable BEFORE UPDATE ON {S}.analysis_lens_revisions FOR EACH ROW EXECUTE FUNCTION {S}.analysis_revision_immutable()"))
    op.execute(sa.text(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bee_researcher_runtime') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON {S}.analysis_lenses,{S}.analysis_lens_revisions,
          {S}.analysis_lens_policy,{S}.analysis_discovery_snapshots,{S}.analysis_lens_preview_runs TO bee_researcher_runtime;
        REVOKE ALL ON {S}.analysis_lens_audit FROM bee_researcher_runtime;
        GRANT SELECT,INSERT ON {S}.analysis_lens_audit TO bee_researcher_runtime;
      END IF;
    END $$"""))


def downgrade():
    raise RuntimeError('Keep additive analysis-lens data on application rollback; destructive downgrade is not automatic.')
