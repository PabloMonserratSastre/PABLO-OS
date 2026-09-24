"""Execution leases and persistent scheduling; keeps existing user data."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("lease_token", sa.String(36), nullable=True))
    op.add_column("agent_runs", sa.Column("lease_until", sa.Float(), nullable=True))
    op.create_table(
        "runtime_status",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("project_id", sa.String(36)),
        sa.Column("next_run", sa.String(40), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_id", sa.String(36)),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_schedules_next_run", "schedules", ["next_run"])


def downgrade():
    op.drop_table("schedules")
    op.drop_table("runtime_status")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("lease_token")
        batch.drop_column("lease_until")
