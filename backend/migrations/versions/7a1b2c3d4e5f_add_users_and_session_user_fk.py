"""add_users_and_session_user_fk

Revision ID: 7a1b2c3d4e5f
Revises: 3c42a4c8a9f1
Create Date: 2026-03-04 12:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "3c42a4c8a9f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create users table and add nullable user links to existing entities."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("google_id", sa.String(length=64), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=True),
            sa.Column("avatar_url", sa.String(length=500), nullable=True),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
        op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=True)
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    else:
        user_columns = {c["name"] for c in inspector.get_columns("users")}
        if "google_id" not in user_columns:
            op.add_column("users", sa.Column("google_id", sa.String(length=64), nullable=True))
        if "email" not in user_columns:
            op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))
        if "name" not in user_columns:
            op.add_column("users", sa.Column("name", sa.String(length=200), nullable=True))
        if "avatar_url" not in user_columns:
            op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
        if "last_login_at" not in user_columns:
            op.add_column(
                "users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
            )

        user_indexes = {ix["name"] for ix in inspector.get_indexes("users")}
        if op.f("ix_users_google_id") not in user_indexes:
            op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=True)
        if op.f("ix_users_email") not in user_indexes:
            op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    session_columns = {c["name"] for c in inspector.get_columns("sessions")}
    if "user_id" not in session_columns:
        op.add_column("sessions", sa.Column("user_id", sa.Integer(), nullable=True))

    session_fks = inspector.get_foreign_keys("sessions")
    has_sessions_user_fk = any(
        fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["user_id"]
        for fk in session_fks
    )
    if not has_sessions_user_fk:
        op.create_foreign_key("fk_sessions_user_id_users", "sessions", "users", ["user_id"], ["id"])

    session_indexes = {ix["name"] for ix in inspector.get_indexes("sessions")}
    if op.f("ix_sessions_user_id") not in session_indexes:
        op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)

    if "shared_trips" in tables:
        shared_columns = {c["name"] for c in inspector.get_columns("shared_trips")}
        if "user_id" not in shared_columns:
            op.add_column("shared_trips", sa.Column("user_id", sa.Integer(), nullable=True))

        shared_fks = inspector.get_foreign_keys("shared_trips")
        has_shared_user_fk = any(
            fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["user_id"]
            for fk in shared_fks
        )
        if not has_shared_user_fk:
            op.create_foreign_key(
                "fk_shared_trips_user_id_users",
                "shared_trips",
                "users",
                ["user_id"],
                ["id"],
            )

        shared_indexes = {ix["name"] for ix in inspector.get_indexes("shared_trips")}
        if op.f("ix_shared_trips_user_id") not in shared_indexes:
            op.create_index(
                op.f("ix_shared_trips_user_id"), "shared_trips", ["user_id"], unique=False
            )


def downgrade() -> None:
    """Remove user links and users table."""
    op.drop_index(op.f("ix_shared_trips_user_id"), table_name="shared_trips")
    op.drop_constraint("fk_shared_trips_user_id_users", "shared_trips", type_="foreignkey")
    op.drop_column("shared_trips", "user_id")

    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_constraint("fk_sessions_user_id_users", "sessions", type_="foreignkey")
    op.drop_column("sessions", "user_id")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
