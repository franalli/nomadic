"""add trip_events table

Revision ID: d5e8f3b14a7c
Revises: c4b7e1a29d3f
Create Date: 2026-03-21 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e8f3b14a7c"
down_revision: Union[str, None] = "c4b7e1a29d3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trip_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("event_type", sa.String(48), nullable=False, index=True),
        sa.Column("destination", sa.String(200), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_trip_events_session_type",
        "trip_events",
        ["session_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_trip_events_session_type", table_name="trip_events")
    op.drop_table("trip_events")
