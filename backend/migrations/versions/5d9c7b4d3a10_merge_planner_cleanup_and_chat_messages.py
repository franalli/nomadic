"""Merge chat messages and planner cleanup branches."""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "5d9c7b4d3a10"
down_revision: Union[str, Sequence[str], None] = ("2a4d5c1b6f2c", "c1f8e8bf9d21")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This merge revision links the two heads into a single linear history.
    pass


def downgrade() -> None:
    # Splitting merged heads is not supported automatically.
    pass
