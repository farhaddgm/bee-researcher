"""Owner token limits and a durable token ledger; retain on rollback."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0051_token_quotas'
down_revision = '0050_reader_tools'
branch_labels = depends_on = None
S = 'market_intelligence'


def upgrade():
    op.create_table('reader_token_limits', sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('assistant_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.assistant_workspaces.id', ondelete='CASCADE')),
        sa.Column('user_id', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='CASCADE')),
        sa.Column('limits', pg.JSONB(), nullable=False), sa.Column('inherit', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_by', pg.UUID(as_uuid=True), sa.ForeignKey(f'{S}.admin_users.id', ondelete='SET NULL')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("(id = 'default' AND assistant_id IS NULL AND user_id IS NULL AND NOT inherit) OR "
                           "(assistant_id IS NOT NULL AND user_id IS NULL AND id = 'project:' || assistant_id::text) OR "
                           "(assistant_id IS NOT NULL AND user_id IS NOT NULL AND id = 'user:' || assistant_id::text || ':' || user_id::text)", name='reader_token_limit_scope'),
        sa.CheckConstraint('version > 0', name='reader_token_limit_version'), schema=S)
    op.add_column('news_chat_generations', sa.Column('reserved_tokens', sa.BigInteger(), server_default='0', nullable=False), schema=S)
    op.add_column('news_chat_generations', sa.Column('input_tokens', sa.BigInteger()), schema=S)
    op.add_column('news_chat_generations', sa.Column('output_tokens', sa.BigInteger()), schema=S)
    op.create_check_constraint('reader_token_counts', 'news_chat_generations',
        'reserved_tokens >= 0 AND (input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0)', schema=S)
    op.create_index('ix_reader_token_usage', 'news_chat_generations', ['user_id', 'assistant_id', 'created_at', 'id'], schema=S)
    # Supports the old app during a forward-schema rollback and between DDL
    # and replacement. Only valid integers become measured usage. Historical
    # Anthropic price-weighted inputs remain explicitly estimated.
    op.execute(sa.text(f"""CREATE FUNCTION {S}.reader_token_ledger_fill() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE inp bigint; outp bigint; bound bigint; cap bigint;
    BEGIN
      IF NEW.input_tokens IS NULL OR NEW.output_tokens IS NULL THEN
        IF jsonb_typeof(NEW.usage->'output_tokens') = 'number' AND NEW.usage->>'output_tokens' ~ '^[0-9]{{1,13}}$' THEN
          outp := LEAST((NEW.usage->>'output_tokens')::bigint,1000000000000);
        END IF;
        IF jsonb_typeof(COALESCE(NEW.usage->'quota_input_tokens',NEW.usage->'input_tokens')) = 'number'
          AND COALESCE(NEW.usage->>'quota_input_tokens',NEW.usage->>'input_tokens') ~ '^[0-9]{{1,13}}$' THEN
          inp := LEAST(COALESCE(NEW.usage->>'quota_input_tokens',NEW.usage->>'input_tokens')::bigint,1000000000000);
        END IF;
        IF inp IS NOT NULL AND outp IS NOT NULL AND
          (NEW.model->>'provider' <> 'anthropic' OR NEW.usage ? 'quota_input_tokens') THEN
          NEW.input_tokens := inp; NEW.output_tokens := outp;
        ELSIF NEW.status = 'stopped' AND NEW.actual_usd = 0 AND inp IS NULL AND outp IS NULL THEN
          NEW.input_tokens := 0; NEW.output_tokens := 0;
        END IF;
        IF NEW.reserved_tokens = 0 AND NEW.input_tokens IS NULL THEN
          IF NEW.usage->>'input_bound' ~ '^[0-9]{{1,13}}$' THEN
            bound := LEAST((NEW.usage->>'input_bound')::bigint,1000000000000);
          ELSE
            bound := octet_length(NEW.question) + octet_length(NEW.answer) + 600;
          END IF;
          IF NEW.model->>'max_output_tokens' ~ '^[0-9]{{1,5}}$' THEN
            cap := LEAST((NEW.model->>'max_output_tokens')::bigint,4000);
          ELSE cap := 4000; END IF;
          NEW.reserved_tokens := GREATEST(bound + cap, COALESCE(inp,0) + COALESCE(outp,0));
        END IF;
      END IF;
      RETURN NEW;
    END $$;"""))
    op.execute(sa.text(f"""CREATE TRIGGER reader_token_ledger_fill BEFORE INSERT OR UPDATE ON {S}.news_chat_generations
      FOR EACH ROW EXECUTE FUNCTION {S}.reader_token_ledger_fill();"""))
    op.execute(sa.text(f"""UPDATE {S}.news_chat_generations SET reserved_tokens = reserved_tokens;"""))
    op.execute(sa.text(f"""REVOKE ALL ON FUNCTION {S}.reader_token_ledger_fill() FROM PUBLIC;"""))
    op.execute(sa.text(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bee_researcher_runtime') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON {S}.reader_token_limits TO bee_researcher_runtime;
      END IF;
    END $$;"""))


def downgrade():
    raise RuntimeError('Retain token consumption and configured limits during application rollback')
