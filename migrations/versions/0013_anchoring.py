"""entry manual position within its Daily Log

Revision ID: 0013_anchoring
Revises: 0014_nested_notes
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0013_anchoring'
down_revision: str | None = '0014_nested_notes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('entries', sa.Column('position', sa.Integer(), nullable=True))
    # Logged order was the manual order until now, and the Daily Log's
    # ordering rule turns it into the same Daily Log.
    op.execute('UPDATE entries SET position = id')
    op.alter_column('entries', 'position', nullable=False)


def downgrade() -> None:
    op.drop_column('entries', 'position')
