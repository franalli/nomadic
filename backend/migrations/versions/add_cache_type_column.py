"""add cache_type column to response_cache

Revision ID: b5c6d7e8f9a0
Revises: 0347ceb87559
Create Date: 2026-02-02

Adds cache_type column to response_cache table to support multiple cache types:
- 'specialist': Vertical specialist LLM outputs (7 day TTL)
- 'tiles': Tile data from Amadeus/curated providers (24h TTL)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "0347ceb87559"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cache_type column with default 'specialist' for existing rows."""
    op.add_column(
        "response_cache",
        sa.Column(
            "cache_type",
            sa.String(50),
            nullable=False,
            server_default="specialist",
        ),
    )
    op.create_index(
        "idx_response_cache_type",
        "response_cache",
        ["cache_type"],
        unique=False,
    )


def downgrade() -> None:
    """Remove cache_type column."""
    op.drop_index("idx_response_cache_type", table_name="response_cache")
    op.drop_column("response_cache", "cache_type")
