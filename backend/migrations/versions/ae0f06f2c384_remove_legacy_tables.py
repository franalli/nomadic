"""remove_legacy_tables

Revision ID: ae0f06f2c384
Revises: 297678ec8f79
Create Date: 2025-11-29 00:20:34.022170

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae0f06f2c384"
down_revision: Union[str, Sequence[str], None] = "297678ec8f79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Remove legacy tables (Branch, BranchTile, Tile) and update TileClick
    to use string identifiers instead of foreign keys.
    """
    # First: Drop foreign key constraints on tile_clicks before dropping referenced tables
    op.execute("ALTER TABLE tile_clicks DROP CONSTRAINT IF EXISTS tile_clicks_tile_id_fkey")
    op.execute("ALTER TABLE tile_clicks DROP CONSTRAINT IF EXISTS tile_clicks_branch_id_fkey")

    # Update tile_clicks: add string identifiers, remove FK columns
    op.add_column(
        "tile_clicks", sa.Column("branch_identifier", sa.String(length=128), nullable=True)
    )

    # Drop the FK columns
    op.execute("ALTER TABLE tile_clicks DROP COLUMN IF EXISTS branch_id")
    op.execute("ALTER TABLE tile_clicks DROP COLUMN IF EXISTS tile_id")

    # Now drop legacy tables (order matters due to foreign keys between them)
    op.drop_table("branch_tiles")
    op.drop_index(op.f("ix_tiles_id"), table_name="tiles")
    op.drop_table("tiles")
    op.drop_index(op.f("ix_branches_id"), table_name="branches")
    op.drop_table("branches")

    # Drop plan_states if it exists (legacy table)
    op.execute("DROP TABLE IF EXISTS plan_states CASCADE")


def downgrade() -> None:
    """
    Restore legacy tables. Note: data will be lost.
    """
    # Add back tile_clicks FK columns
    op.add_column("tile_clicks", sa.Column("tile_id", sa.INTEGER(), nullable=True))
    op.add_column("tile_clicks", sa.Column("branch_id", sa.INTEGER(), nullable=True))

    # Drop the string identifier column
    op.drop_column("tile_clicks", "branch_identifier")

    # Recreate legacy tables
    op.create_table(
        "branches",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("trip_context_id", sa.INTEGER(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("destination", sa.String(length=64), nullable=False),
        sa.Column("is_primary", sa.BOOLEAN(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_context_id"], ["trip_contexts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_branches_id"), "branches", ["id"], unique=False)

    op.create_table(
        "tiles",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("partner", sa.String(length=64), nullable=True),
        sa.Column("partner_product_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("subtitle", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("price_estimate", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("price_basis", sa.String(length=32), nullable=True),
        sa.Column("is_estimate_only", sa.BOOLEAN(), nullable=False, server_default="true"),
        sa.Column("deeplink_url", sa.String(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.INTEGER(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("location_label", sa.String(length=128), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tiles_id"), "tiles", ["id"], unique=False)

    op.create_table(
        "branch_tiles",
        sa.Column("branch_id", sa.INTEGER(), nullable=False),
        sa.Column("tile_id", sa.INTEGER(), nullable=False),
        sa.Column("position", sa.INTEGER(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["tile_id"], ["tiles.id"]),
        sa.PrimaryKeyConstraint("branch_id", "tile_id"),
    )

    # Add back FK constraints on tile_clicks
    op.create_foreign_key(
        "tile_clicks_branch_id_fkey", "tile_clicks", "branches", ["branch_id"], ["id"]
    )
    op.create_foreign_key("tile_clicks_tile_id_fkey", "tile_clicks", "tiles", ["tile_id"], ["id"])
