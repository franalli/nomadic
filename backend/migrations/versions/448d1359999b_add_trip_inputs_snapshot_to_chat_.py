"""add trip_inputs_snapshot to chat_messages

Revision ID: 448d1359999b
Revises: 0cc367f7e2df
Create Date: 2026-01-11 22:14:16.134243

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "448d1359999b"
down_revision: Union[str, Sequence[str], None] = "0cc367f7e2df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add trip_inputs_snapshot column to chat_messages for undo functionality."""
    op.add_column("chat_messages", sa.Column("trip_inputs_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove trip_inputs_snapshot column from chat_messages."""
    op.drop_column("chat_messages", "trip_inputs_snapshot")
