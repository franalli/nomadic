"""add variant column to unsplash_image_cache

Revision ID: a1b2c3d4e5f6
Revises: 817b72698e5b
Create Date: 2026-01-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "817b72698e5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add variant column and update primary key to composite (destination, variant)."""
    # Clean up any leftover tables from failed migrations
    from sqlalchemy import inspect

    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if "unsplash_image_cache_old" in existing_tables:
        op.drop_table("unsplash_image_cache_old")
    if "unsplash_image_cache" in existing_tables:
        op.drop_table("unsplash_image_cache")

    # Create new table with composite primary key including variant
    op.create_table(
        "unsplash_image_cache",
        sa.Column("destination", sa.String(length=256), nullable=False),
        sa.Column("variant", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_id", sa.String(length=128), nullable=False),
        sa.Column("photographer", sa.String(length=256), nullable=True),
        sa.Column("photographer_url", sa.String(length=512), nullable=True),
        sa.Column("unsplash_url", sa.String(length=512), nullable=True),
        sa.Column("download_location", sa.String(length=512), nullable=True),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("destination", "variant"),
    )


def downgrade() -> None:
    """Remove variant column and revert to single-column primary key."""
    # Drop and recreate - this is a cache table, data loss is acceptable
    op.drop_table("unsplash_image_cache")

    # Create old table structure without variant
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
