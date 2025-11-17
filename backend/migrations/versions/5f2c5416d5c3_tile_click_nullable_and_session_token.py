"""Allow nullable tile FK, store raw tile id, and accept string session ids.

Revision ID: 5f2c5416d5c3
Revises: 4a6c1f40c1d2
Create Date: 2025-11-17 00:56:13.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f2c5416d5c3"
down_revision: Union[str, Sequence[str], None] = "4a6c1f40c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow storing click events without a tile FK and with raw session IDs."""
    op.alter_column(
        "tile_clicks",
        "tile_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.drop_constraint(
        "tile_clicks_session_id_fkey",
        "tile_clicks",
        type_="foreignkey",
    )
    op.alter_column(
        "tile_clicks",
        "session_id",
        existing_type=sa.Integer(),
        type_=sa.String(length=64),
        existing_nullable=True,
        postgresql_using="session_id::text",
    )

    op.add_column(
        "tile_clicks",
        sa.Column("tile_identifier", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    """Revert session_id/tile_id changes."""
    op.drop_column("tile_clicks", "tile_identifier")

    op.alter_column(
        "tile_clicks",
        "session_id",
        existing_type=sa.String(length=64),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="NULLIF(session_id, '')::integer",
    )
    op.create_foreign_key(
        "tile_clicks_session_id_fkey",
        "tile_clicks",
        "sessions",
        ["session_id"],
        ["id"],
    )

    op.alter_column(
        "tile_clicks",
        "tile_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
