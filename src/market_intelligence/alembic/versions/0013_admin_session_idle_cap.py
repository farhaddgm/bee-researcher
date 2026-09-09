"""Cap existing administrator sessions at the six-hour idle boundary."""

from alembic import op
import sqlalchemy as sa


SCHEMA = "market_intelligence"
revision = "0013_admin_session_idle_cap"
down_revision = "0012_pipeline_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older deployments used an absolute 12-hour (or longer) expiry. We do
    # not know their last request time, so safely cap each existing session
    # from the migration moment; subsequent requests renew it as a sliding
    # idle timeout through current_admin().
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.admin_sessions
            SET expires_at = LEAST(expires_at, CURRENT_TIMESTAMP + INTERVAL '6 hours')
            WHERE expires_at > CURRENT_TIMESTAMP + INTERVAL '6 hours'
            """
        )
    )


def downgrade() -> None:
    # The previous absolute expiry cannot be reconstructed safely.
    pass
