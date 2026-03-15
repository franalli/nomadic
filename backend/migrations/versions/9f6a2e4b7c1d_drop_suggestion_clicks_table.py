"""drop suggestion_clicks table

Revision ID: 9f6a2e4b7c1d
Revises: 7a1b2c3d4e5f
Create Date: 2026-03-13 12:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "9f6a2e4b7c1d"
down_revision: Union[str, Sequence[str], None] = "7a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unused suggestion_clicks table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "suggestion_clicks" not in tables:
        return

    indexes = {index["name"] for index in inspector.get_indexes("suggestion_clicks")}
    if "ix_suggestion_clicks_id" in indexes:
        op.drop_index("ix_suggestion_clicks_id", table_name="suggestion_clicks")
    op.drop_table("suggestion_clicks")


def downgrade() -> None:
    """Recreate suggestion_clicks for historical downgrade support."""
    op.create_table(
        "suggestion_clicks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suggestion_text", sa.String(length=128), nullable=False),
        sa.Column("suggestion_index", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suggestion_clicks_id", "suggestion_clicks", ["id"], unique=False)
