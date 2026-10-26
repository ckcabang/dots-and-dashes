"""migration chain: each copy links to the one it was migrated or scheduled from

Revision ID: 0016_migration_chain
Revises: 0013_anchoring
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0016_migration_chain'
down_revision: str | None = '0013_anchoring'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('entries', sa.Column('migrated_from_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'entries_migrated_from_id_fkey',
        'entries',
        'entries',
        ['migrated_from_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_entries_migrated_from_id'), 'entries', ['migrated_from_id'], unique=False
    )


def downgrade() -> None:
    # The app before this revision has no Migrated or Scheduled Task States.
    op.execute("UPDATE entries SET state = 'completed' WHERE state IN ('migrated', 'scheduled')")
    op.drop_index(op.f('ix_entries_migrated_from_id'), table_name='entries')
    op.drop_constraint('entries_migrated_from_id_fkey', 'entries', type_='foreignkey')
    op.drop_column('entries', 'migrated_from_id')
