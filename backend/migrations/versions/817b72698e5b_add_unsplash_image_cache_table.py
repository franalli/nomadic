"""add unsplash_image_cache table

Revision ID: 817b72698e5b
Revises: 448d1359999b
Create Date: 2026-01-13 23:15:56.922344

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "817b72698e5b"
down_revision: Union[str, Sequence[str], None] = "448d1359999b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "unsplash_image_cache",
        sa.Column("destination", sa.String(length=256), nullable=False),
        sa.Column("image_id", sa.String(length=128), nullable=False),
        sa.Column("photographer", sa.String(length=256), nullable=True),
        sa.Column("photographer_url", sa.String(length=512), nullable=True),
        sa.Column("unsplash_url", sa.String(length=512), nullable=True),
        sa.Column("download_location", sa.String(length=512), nullable=True),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("destination"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("unsplash_image_cache")
