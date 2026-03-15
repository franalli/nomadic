"""add runtime_state table

Revision ID: c4b7e1a29d3f
Revises: 9f6a2e4b7c1d
Create Date: 2026-03-13 13:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "c4b7e1a29d3f"
down_revision: Union[str, Sequence[str], None] = "9f6a2e4b7c1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create shared runtime_state table for leases and spend counters."""
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "runtime_state" in tables:
        return

    op.create_table(
        "runtime_state",
        sa.Column("state_key", sa.String(length=255), nullable=False),
        sa.Column("state_type", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("day_key", sa.String(length=10), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value_micro_usd", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state_key"),
    )
    op.create_index(op.f("ix_runtime_state_state_type"), "runtime_state", ["state_type"])
    op.create_index(op.f("ix_runtime_state_scope"), "runtime_state", ["scope"])
    op.create_index(op.f("ix_runtime_state_session_id"), "runtime_state", ["session_id"])
    op.create_index(op.f("ix_runtime_state_provider"), "runtime_state", ["provider"])
    op.create_index(op.f("ix_runtime_state_day_key"), "runtime_state", ["day_key"])
    op.create_index(op.f("ix_runtime_state_expires_at"), "runtime_state", ["expires_at"])


def downgrade() -> None:
    """Drop runtime_state table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "runtime_state" not in tables:
        return

    op.drop_index(op.f("ix_runtime_state_expires_at"), table_name="runtime_state")
    op.drop_index(op.f("ix_runtime_state_day_key"), table_name="runtime_state")
    op.drop_index(op.f("ix_runtime_state_provider"), table_name="runtime_state")
    op.drop_index(op.f("ix_runtime_state_session_id"), table_name="runtime_state")
    op.drop_index(op.f("ix_runtime_state_scope"), table_name="runtime_state")
    op.drop_index(op.f("ix_runtime_state_state_type"), table_name="runtime_state")
    op.drop_table("runtime_state")
