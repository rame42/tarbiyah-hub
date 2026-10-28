"""Relevance score and archive.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("resources") as b:
        b.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("relevance", sa.Integer(), nullable=True))
        b.create_index("ix_resources_archived", ["archived"])
        b.create_index("ix_resources_relevance", ["relevance"])


def downgrade() -> None:
    with op.batch_alter_table("resources") as b:
        b.drop_index("ix_resources_relevance")
        b.drop_index("ix_resources_archived")
        b.drop_column("relevance")
        b.drop_column("archived")
