"""Private connectors, provider configuration and request budget ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("integrations", sa.Column("id", sa.String(30), primary_key=True),
                    sa.Column("config", sa.JSON(), nullable=False), sa.Column("encrypted", sa.Text(), nullable=False),
                    sa.Column("updated_at", sa.String(40), nullable=False))
    op.create_table("oauth_states", sa.Column("id", sa.String(64), primary_key=True),
                    sa.Column("encrypted", sa.Text(), nullable=False), sa.Column("expires", sa.Integer(), nullable=False),
                    sa.Column("session_id", sa.String(64), nullable=False))
    op.create_table("service_config", sa.Column("id", sa.String(40), primary_key=True),
                    sa.Column("value", sa.JSON(), nullable=False), sa.Column("encrypted", sa.Text(), nullable=False))
    op.create_table("budget_periods", sa.Column("id", sa.String(7), primary_key=True),
                    sa.Column("committed_micro", sa.Integer(), nullable=False), sa.Column("actual_micro", sa.Integer(), nullable=False))


def downgrade():
    for name in ["budget_periods", "service_config", "oauth_states", "integrations"]:
        op.drop_table(name)
