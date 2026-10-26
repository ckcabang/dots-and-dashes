"""users: the User and the Canary User, each owning their own Entries

Revision ID: 0006_users
Revises: 0016_migration_chain
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006_users'
down_revision: str | None = '0016_migration_chain'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False),
        sa.Column('canary', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    # Nullable so Entries logged before Users existed survive: the first real
    # User created claims them.
    op.add_column('entries', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'entries_user_id_fkey', 'entries', 'users', ['user_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index(op.f('ix_entries_user_id'), 'entries', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_entries_user_id'), table_name='entries')
    op.drop_constraint('entries_user_id_fkey', 'entries', type_='foreignkey')
    op.drop_column('entries', 'user_id')
    op.drop_table('users')
