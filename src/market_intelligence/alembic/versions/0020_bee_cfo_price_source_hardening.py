"""Add a direct, structured TGJU quote source for the approved 18K gold index."""

from alembic import op
import sqlalchemy as sa


revision = "0020_bee_cfo_price_hardening"
down_revision = "0019_bee_cfo_factor_forecast"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    # The HTML profile remains a useful fallback, but the structured endpoint
    # is preferred so navigation/schema numbers can never become a quote.
    op.execute(sa.text(f"""
        INSERT INTO {SCHEMA}.bee_cfo_indicator_sources
            (id, indicator_id, source_key, name, homepage_url, fetch_url,
             adapter, parser_json, priority, status)
        VALUES
            ('00000000-0000-0000-0000-000000001825'::uuid,
             '00000000-0000-0000-0000-000000001811'::uuid,
             'SRC-TGJU-API',
             'TGJU API · طلای ۱۸ عیار',
             'https://www.tgju.org/',
             'https://api.tgju.org/v1/market/indicator/today-table-data/geram18?lang=fa',
             'json',
             '{{"path":["data",0,0]}}'::jsonb,
             5,
             'active')
        ON CONFLICT (indicator_id, source_key) DO NOTHING
    """))


def downgrade() -> None:
    op.execute(sa.text(f"""
        DELETE FROM {SCHEMA}.bee_cfo_indicator_sources
        WHERE indicator_id = '00000000-0000-0000-0000-000000001811'::uuid
          AND source_key = 'SRC-TGJU-API'
    """))
