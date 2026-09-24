"""Durable workspace for hosts with ephemeral disks."""
from alembic import op
import sqlalchemy as sa
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("workspace_files", sa.Column("path", sa.String(500), primary_key=True),
                    sa.Column("content", sa.LargeBinary(), nullable=False),
                    sa.Column("checksum", sa.String(64), nullable=False))


def downgrade():
    op.drop_table("workspace_files")
