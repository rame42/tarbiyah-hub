"""Resource labels and user deletion (tombstones).

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("resources") as b:
        b.add_column(sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"))
        b.add_column(sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.create_index("ix_resources_deleted", ["deleted"])


def downgrade() -> None:
    with op.batch_alter_table("resources") as b:
        b.drop_index("ix_resources_deleted")
        b.drop_column("deleted")
        b.drop_column("labels")
