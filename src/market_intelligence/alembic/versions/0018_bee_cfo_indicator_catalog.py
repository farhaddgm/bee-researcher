"""Add the isolated Bee CFO market/index catalog and price delivery domain."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_bee_cfo_indicator_catalog"
down_revision = "0017_bee_cfo_telegram_delivery"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
NOW = sa.text("CURRENT_TIMESTAMP")
EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_ARRAY = sa.text("'[]'::jsonb")
ASSISTANT_FK = f"{SCHEMA}.assistant_workspaces.id"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )


def upgrade() -> None:
    op.create_table(
        "bee_cfo_markets",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("market_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("region", sa.String(32), nullable=False, server_default="global"),
        sa.Column("currency", sa.String(16)),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("display_order", sa.SmallInteger, nullable=False, server_default="100"),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        *_timestamps(),
        sa.UniqueConstraint("market_key", name="uq_mi_bee_cfo_markets_key"),
        sa.CheckConstraint("status IN ('draft', 'active', 'disabled')", name=op.f("ck_mi_bee_cfo_markets_status")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_markets_status_order", "bee_cfo_markets", ["status", "display_order"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_indicators",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("market_key", sa.String(64), nullable=False),
        sa.Column("indicator_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("quote_unit", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False, server_default="IRR"),
        sa.Column("parser_key", sa.String(48), nullable=False, server_default="generic"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("display_order", sa.SmallInteger, nullable=False, server_default="100"),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        *_timestamps(),
        sa.UniqueConstraint("indicator_key", name="uq_mi_bee_cfo_indicators_key"),
        sa.CheckConstraint("status IN ('draft', 'active', 'disabled')", name=op.f("ck_mi_bee_cfo_indicators_status")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_indicators_market_status", "bee_cfo_indicators", ["market_key", "status", "display_order"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_indicator_sources",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("indicator_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_indicators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("homepage_url", sa.String(2048), nullable=False),
        sa.Column("fetch_url", sa.String(2048), nullable=False),
        sa.Column("adapter", sa.String(16), nullable=False, server_default="html"),
        sa.Column("parser_json", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("priority", sa.SmallInteger, nullable=False, server_default="3"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        *_timestamps(),
        sa.UniqueConstraint("indicator_id", "source_key", name="uq_mi_bee_cfo_indicator_sources_key"),
        sa.CheckConstraint("adapter IN ('html', 'json')", name=op.f("ck_mi_bee_cfo_indicator_sources_adapter")),
        sa.CheckConstraint("status IN ('draft', 'active', 'disabled')", name=op.f("ck_mi_bee_cfo_indicator_sources_status")),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name=op.f("ck_mi_bee_cfo_indicator_sources_priority")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_indicator_sources_active", "bee_cfo_indicator_sources", ["indicator_id", "status", "priority"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_assistant_indicator_selections",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assistant_id", UUID, sa.ForeignKey(ASSISTANT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("market_key", sa.String(64), nullable=False),
        sa.Column("indicator_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("revision", sa.String(64), nullable=False, server_default="bee-cfo-indicator-1"),
        *_timestamps(),
        sa.UniqueConstraint("assistant_id", name="uq_mi_bee_cfo_indicator_selection_assistant"),
        sa.CheckConstraint("status IN ('draft', 'active', 'paused')", name=op.f("ck_mi_bee_cfo_indicator_selection_status")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_indicator_selection_status", "bee_cfo_assistant_indicator_selections", ["status"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_price_snapshots",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assistant_id", UUID, sa.ForeignKey(ASSISTANT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("indicator_key", sa.String(64), nullable=False),
        sa.Column("source_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_indicator_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("previous_value", sa.Numeric(24, 8)),
        sa.Column("change_value", sa.Numeric(24, 8)),
        sa.Column("change_percent", sa.Numeric(18, 8)),
        sa.Column("quote_unit", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("raw_quote", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("provenance", JSONB, nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("assistant_id", "indicator_key", "observed_at", name="uq_mi_bee_cfo_price_snapshot_observed"),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_price_snapshots_assistant_indicator_observed", "bee_cfo_price_snapshots", ["assistant_id", "indicator_key", "observed_at"], schema=SCHEMA)

    op.create_table(
        "bee_cfo_price_deliveries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assistant_id", UUID, sa.ForeignKey(ASSISTANT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", UUID, sa.ForeignKey(f"{SCHEMA}.bee_cfo_price_snapshots.id", ondelete="SET NULL")),
        sa.Column("destination_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("message_ids", JSONB, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("renderer_revision", sa.String(64), nullable=False, server_default="bee-cfo-price-1"),
        sa.Column("error_message", sa.Text),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("assistant_id", "report_id", "destination_id", name="uq_mi_bee_cfo_price_delivery_destination"),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed', 'skipped')", name=op.f("ck_mi_bee_cfo_price_deliveries_status")),
        schema=SCHEMA,
    )
    op.create_index("ix_mi_bee_cfo_price_deliveries_status_created", "bee_cfo_price_deliveries", ["assistant_id", "status", "created_at"], schema=SCHEMA)

    # Default options are catalog entries, not an automatic selection. Direct
    # price references are explicit and auditable; the Bitcoin JSON reference
    # remains draft until the product owner approves it.
    op.execute(sa.text(f"""
        INSERT INTO {SCHEMA}.bee_cfo_markets
            (id, market_key, name, display_name, region, currency, status, display_order)
        VALUES
            ('00000000-0000-0000-0000-000000001801'::uuid, 'IR_GOLD', 'Iran gold market', 'بازار طلای ایران', 'IR', 'IRR', 'active', 10),
            ('00000000-0000-0000-0000-000000001802'::uuid, 'IR_FX', 'Iran free FX market', 'بازار ارز آزاد ایران', 'IR', 'IRR', 'active', 20),
            ('00000000-0000-0000-0000-000000001803'::uuid, 'GLOBAL_CRYPTO', 'Global crypto market', 'بازار رمزارز جهانی', 'global', 'USD', 'active', 30)
        ON CONFLICT (market_key) DO NOTHING
    """))
    op.execute(sa.text(f"""
        INSERT INTO {SCHEMA}.bee_cfo_indicators
            (id, market_key, indicator_key, name, display_name, quote_unit, currency, parser_key, status, display_order)
        VALUES
            ('00000000-0000-0000-0000-000000001811'::uuid, 'IR_GOLD', 'GOLD_18K', '18K gold per gram', 'هر گرم طلای ۱۸ عیار', 'تومان', 'IRR', 'gold_18k', 'active', 10),
            ('00000000-0000-0000-0000-000000001812'::uuid, 'IR_FX', 'USD_FREE', 'USD free-market rate', 'دلار آمریکا در بازار آزاد', 'تومان', 'IRR', 'usd_free', 'active', 20),
            ('00000000-0000-0000-0000-000000001813'::uuid, 'GLOBAL_CRYPTO', 'BTC_USDT', 'Bitcoin spot price', 'قیمت بیت‌کوین', 'دلار', 'USD', 'btc_usdt', 'active', 30)
        ON CONFLICT (indicator_key) DO NOTHING
    """))
    op.execute(sa.text(f"""
        INSERT INTO {SCHEMA}.bee_cfo_indicator_sources
            (id, indicator_id, source_key, name, homepage_url, fetch_url, adapter, parser_json, priority, status)
        VALUES
            ('00000000-0000-0000-0000-000000001821'::uuid, '00000000-0000-0000-0000-000000001811'::uuid, 'SRC-TGJU-GOLD', 'TGJU · طلای ۱۸ عیار', 'https://www.tgju.org/', 'https://www.tgju.org/profile/geram18', 'html', '{{}}'::jsonb, 5, 'active'),
            ('00000000-0000-0000-0000-000000001822'::uuid, '00000000-0000-0000-0000-000000001812'::uuid, 'SRC-TGJU-USD', 'TGJU · دلار آزاد', 'https://www.tgju.org/', 'https://www.tgju.org/profile/price_dollar_rl', 'html', '{{}}'::jsonb, 5, 'active'),
            ('00000000-0000-0000-0000-000000001823'::uuid, '00000000-0000-0000-0000-000000001812'::uuid, 'SRC-NVSN-USD', 'نوسان · دلار', 'https://www.navasan.net/', 'https://www.navasan.net/dayRates.php?item=usd', 'html', '{{}}'::jsonb, 4, 'active'),
            ('00000000-0000-0000-0000-000000001824'::uuid, '00000000-0000-0000-0000-000000001813'::uuid, 'SRC-CG-BTC', 'CoinGecko · Bitcoin', 'https://www.coingecko.com/', 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd', 'json', '{{"path":["bitcoin","usd"]}}'::jsonb, 3, 'draft')
        ON CONFLICT (indicator_id, source_key) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_index("ix_mi_bee_cfo_price_deliveries_status_created", table_name="bee_cfo_price_deliveries", schema=SCHEMA)
    op.drop_table("bee_cfo_price_deliveries", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_price_snapshots_assistant_indicator_observed", table_name="bee_cfo_price_snapshots", schema=SCHEMA)
    op.drop_table("bee_cfo_price_snapshots", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_indicator_selection_status", table_name="bee_cfo_assistant_indicator_selections", schema=SCHEMA)
    op.drop_table("bee_cfo_assistant_indicator_selections", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_indicator_sources_active", table_name="bee_cfo_indicator_sources", schema=SCHEMA)
    op.drop_table("bee_cfo_indicator_sources", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_indicators_market_status", table_name="bee_cfo_indicators", schema=SCHEMA)
    op.drop_table("bee_cfo_indicators", schema=SCHEMA)
    op.drop_index("ix_mi_bee_cfo_markets_status_order", table_name="bee_cfo_markets", schema=SCHEMA)
    op.drop_table("bee_cfo_markets", schema=SCHEMA)
