"""add_shared_trips

Revision ID: 3c42a4c8a9f1
Revises: b5c6d7e8f9a0
Create Date: 2026-03-04 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c42a4c8a9f1"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create shared_trips table for frozen public trip snapshots."""
    op.create_table(
        "shared_trips",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=12), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("destination", sa.String(length=200), nullable=True),
        sa.Column("hero_image_url", sa.String(length=500), nullable=True),
        sa.Column("day_count", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_shared_trips_id"), "shared_trips", ["id"], unique=False)
    op.create_index(op.f("ix_shared_trips_slug"), "shared_trips", ["slug"], unique=True)


def downgrade() -> None:
    """Drop shared_trips table."""
    op.drop_index(op.f("ix_shared_trips_slug"), table_name="shared_trips")
    op.drop_index(op.f("ix_shared_trips_id"), table_name="shared_trips")
    op.drop_table("shared_trips")
