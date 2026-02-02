"""add response_cache table

Revision ID: 0347ceb87559
Revises: a1b2c3d4e5f6
Create Date: 2026-02-02 13:01:33.894445

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0347ceb87559"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create response_cache table for specialist LLM output caching."""
    op.create_table(
        "response_cache",
        sa.Column("cache_key", sa.String(256), primary_key=True),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_response_cache_expires_at",
        "response_cache",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop response_cache table."""
    op.drop_index("idx_response_cache_expires_at", table_name="response_cache")
    op.drop_table("response_cache")
