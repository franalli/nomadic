"""add_session_expiration_columns

Revision ID: 2e2c7a728ad8
Revises: ae0f06f2c384
Create Date: 2025-11-30 15:30:58.545175

"""

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2e2c7a728ad8"
down_revision: Union[str, Sequence[str], None] = "ae0f06f2c384"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add session expiration columns."""
    # Add last_activity_at column with default of now for existing rows
    op.add_column(
        "sessions",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,  # Temporarily nullable
        ),
    )

    # Add expires_at column with default of 90 days from now for existing rows
    op.add_column(
        "sessions",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,  # Temporarily nullable
        ),
    )

    # Set default values for existing rows
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=90)

    op.execute(
        sa.text(
            f"UPDATE sessions SET last_activity_at = '{now.isoformat()}', "
            f"expires_at = '{expires_at.isoformat()}' WHERE last_activity_at IS NULL"
        )
    )

    # Make columns non-nullable now that data is populated
    op.alter_column("sessions", "last_activity_at", nullable=False)
    op.alter_column("sessions", "expires_at", nullable=False)


def downgrade() -> None:
    """Remove session expiration columns."""
    op.drop_column("sessions", "expires_at")
    op.drop_column("sessions", "last_activity_at")
