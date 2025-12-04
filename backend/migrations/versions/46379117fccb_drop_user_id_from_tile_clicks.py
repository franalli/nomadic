"""drop_user_id_from_tile_clicks

Revision ID: 46379117fccb
Revises: 2e2c7a728ad8
Create Date: 2025-12-04 01:40:11.476041

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "46379117fccb"
down_revision: Union[str, Sequence[str], None] = "2e2c7a728ad8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop user_id column from tile_clicks (field is never used)."""
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("tile_clicks")]
    if "user_id" in columns:
        op.drop_column("tile_clicks", "user_id")


def downgrade() -> None:
    """Re-add user_id column to tile_clicks."""
    op.add_column("tile_clicks", sa.Column("user_id", sa.String(64), nullable=True))
