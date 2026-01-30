"""initial

Revision ID: 001_initial
Revises:
Create Date: 2026-01-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.core.database import Base
    import app.models  # noqa: F401 - register all models with Base.metadata
    conn = op.get_bind()
    Base.metadata.create_all(bind=conn)


def downgrade() -> None:
    from app.core.database import Base
    import app.models  # noqa: F401
    conn = op.get_bind()
    Base.metadata.drop_all(bind=conn)
