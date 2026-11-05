"""Topic map for precise searches.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pillar", sa.String(20), nullable=False),
        sa.Column("name_en", sa.String(300), nullable=False),
        sa.Column("name_ar", sa.String(300), nullable=False),
        sa.Column("phrases_en", sa.JSON(), nullable=False),
        sa.Column("phrases_ar", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("origin", sa.String(20), nullable=False, server_default="seed"),
        sa.Column("last_swept_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_search_topics_pillar", "search_topics", ["pillar"])
    with op.batch_alter_table("search_log") as b:
        b.add_column(sa.Column("topic_id", sa.Integer(), nullable=True))
        b.create_index("ix_search_log_topic_id", ["topic_id"])


def downgrade() -> None:
    with op.batch_alter_table("search_log") as b:
        b.drop_index("ix_search_log_topic_id")
        b.drop_column("topic_id")
    op.drop_index("ix_search_topics_pillar", "search_topics")
    op.drop_table("search_topics")
