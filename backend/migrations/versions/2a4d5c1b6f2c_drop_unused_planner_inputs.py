"""Drop unused planner input columns and session preferences."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2a4d5c1b6f2c"
down_revision: Union[str, Sequence[str], None] = "8ef3b6a8e5c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    planner_columns = [
        "origin",
        "destination_hint",
        "start_date",
        "end_date",
        "budget_bucket",
        "group_size",
        "vibes",
    ]

    with op.batch_alter_table("trip_contexts") as batch_op:
        for col in planner_columns:
            batch_op.drop_column(col)

    op.drop_index(op.f("ix_session_preferences_id"), table_name="session_preferences")
    op.drop_table("session_preferences")


def downgrade() -> None:
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

    with op.batch_alter_table("trip_contexts") as batch_op:
        batch_op.add_column(sa.Column("origin", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("destination_hint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("end_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("budget_bucket", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("group_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("vibes", sa.JSON(), nullable=True))
