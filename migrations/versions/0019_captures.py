"""captures: raw text waiting in the Inbox for Triage, each owned by a User

Revision ID: 0019_captures
Revises: 0006_users
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0019_captures'
down_revision: str | None = '0006_users'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'captures',
        sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_captures_user_id'), 'captures', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_captures_user_id'), table_name='captures')
    op.drop_table('captures')
