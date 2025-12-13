"""add_suggestion_clicks_table

Revision ID: 0cc367f7e2df
Revises: 46379117fccb
Create Date: 2025-12-13 14:15:07.233363

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0cc367f7e2df"
down_revision: Union[str, Sequence[str], None] = "46379117fccb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
    op.create_index(op.f("ix_suggestion_clicks_id"), "suggestion_clicks", ["id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_suggestion_clicks_id"), table_name="suggestion_clicks")
    op.drop_table("suggestion_clicks")
