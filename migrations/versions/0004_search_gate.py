"""Search log: how many results passed the precision gate, and why the others did not.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("search_log") as b:
        b.add_column(sa.Column("kept", sa.Integer(), nullable=True))
        b.add_column(sa.Column("gate", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("search_log") as b:
        b.drop_column("gate")
        b.drop_column("kept")
