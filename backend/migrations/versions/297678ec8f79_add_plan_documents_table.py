"""add_plan_documents_table

Revision ID: 297678ec8f79
Revises: 5d9c7b4d3a10
Create Date: 2025-11-28 23:53:01.537211

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "297678ec8f79"
down_revision: Union[str, Sequence[str], None] = "5d9c7b4d3a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "plan_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=16), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_documents_id"), "plan_documents", ["id"], unique=False)
    op.create_index(
        op.f("ix_plan_documents_session_id"), "plan_documents", ["session_id"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_plan_documents_session_id"), table_name="plan_documents")
    op.drop_index(op.f("ix_plan_documents_id"), table_name="plan_documents")
    op.drop_table("plan_documents")
