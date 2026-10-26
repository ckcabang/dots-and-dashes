"""entry locations: Daily Log, Monthly Log task list or Future Log

Revision ID: 0015_monthly_future_log
Revises: 0014_nested_notes
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0015_monthly_future_log'
down_revision: str | None = '0014_nested_notes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('entries', sa.Column('location', sa.String(length=16), server_default='day', nullable=False))
    op.add_column('entries', sa.Column('month', sa.Date(), nullable=True))
    op.create_index(op.f('ix_entries_month'), 'entries', ['month'], unique=False)
    op.alter_column('entries', 'day', existing_type=sa.Date(), nullable=True)
    # A Daily Log Entry has a day; Monthly Log and Future Log Entries a month.
    op.create_check_constraint(
        'ck_entries_located',
        'entries',
        "(location = 'day' AND day IS NOT NULL)"
        " OR (location IN ('month', 'future') AND month IS NOT NULL)",
    )
    # Events outside the Future Log always have a date.
    op.create_check_constraint(
        'ck_entries_event_has_date',
        'entries',
        "type <> 'event' OR location = 'future' OR day IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint('ck_entries_event_has_date', 'entries', type_='check')
    op.drop_constraint('ck_entries_located', 'entries', type_='check')
    op.execute("DELETE FROM entries WHERE day IS NULL")
    op.alter_column('entries', 'day', existing_type=sa.Date(), nullable=False)
    op.drop_index(op.f('ix_entries_month'), table_name='entries')
    op.drop_column('entries', 'month')
    op.drop_column('entries', 'location')
