"""nested notes

Revision ID: 0014_nested_notes
Revises: 0010_prefix_grammar
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0014_nested_notes'
down_revision: str | None = '0010_prefix_grammar'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('entries', sa.Column('parent_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'entries_parent_id_fkey', 'entries', 'entries', ['parent_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('entries_parent_id_fkey', 'entries', type_='foreignkey')
    op.drop_column('entries', 'parent_id')
