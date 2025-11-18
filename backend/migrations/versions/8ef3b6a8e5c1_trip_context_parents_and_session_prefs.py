"""Add trip context parent link and session preferences table.

Revision ID: 8ef3b6a8e5c1
Revises: 5f2c5416d5c3
Create Date: 2025-11-18 10:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8ef3b6a8e5c1"
down_revision: Union[str, Sequence[str], None] = "5f2c5416d5c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trip_contexts",
        sa.Column("parent_trip_context_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "trip_contexts_parent_trip_context_id_fkey",
        "trip_contexts",
        "trip_contexts",
        ["parent_trip_context_id"],
        ["id"],
    )

    op.create_table(
        "session_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("budget_bucket", sa.String(length=32), nullable=True),
        sa.Column("group_size", sa.Integer(), nullable=True),
        sa.Column("vibes", sa.JSON(), nullable=True),
        sa.Column("trip_style", sa.String(length=64), nullable=True),
        sa.Column("blocked_destinations", sa.JSON(), nullable=True),
        sa.Column("preferred_climate", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index(
        op.f("ix_session_preferences_id"),
        "session_preferences",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_session_preferences_id"), table_name="session_preferences")
    op.drop_table("session_preferences")

    op.drop_constraint(
        "trip_contexts_parent_trip_context_id_fkey",
        "trip_contexts",
        type_="foreignkey",
    )
    op.drop_column("trip_contexts", "parent_trip_context_id")
