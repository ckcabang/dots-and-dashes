"""entry signifiers and time

Revision ID: 0010_prefix_grammar
Revises: 0001
Create Date: 2026-10-26 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0010_prefix_grammar'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('entries', sa.Column('priority', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('entries', sa.Column('inspiration', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('entries', sa.Column('time', sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column('entries', 'time')
    op.drop_column('entries', 'inspiration')
    op.drop_column('entries', 'priority')
