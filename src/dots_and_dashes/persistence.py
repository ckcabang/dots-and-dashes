"""The Persistence module: maps Journal domain values to Postgres tables."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Identity, String, Text, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from dots_and_dashes import journal


class Base(DeclarativeBase):
    pass


class EntryRow(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    type: Mapped[str] = mapped_column(String(16))
    # Only Tasks have a Task State.
    state: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    day: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_entry(self) -> journal.Entry:
        return journal.Entry(
            id=self.id,
            type=journal.EntryType(self.type),
            state=journal.TaskState(self.state) if self.state else None,
            text=self.text,
            day=self.day,
        )


class EntryNotFoundError(LookupError):
    """Raised when no stored Entry has the id asked for."""


def _columns(entry: journal.NewEntry | journal.Entry) -> dict[str, object]:
    """The stored columns for an Entry; adding and saving both write these."""
    return {
        "type": entry.type,
        "state": entry.state,
        "text": entry.text,
        "day": entry.day,
    }


def add_entry(session: Session, new_entry: journal.NewEntry) -> journal.Entry:
    row = EntryRow(**_columns(new_entry))
    session.add(row)
    session.flush()
    return row.to_entry()


def entries_on(session: Session, day: date) -> list[journal.Entry]:
    rows = session.scalars(
        select(EntryRow).where(EntryRow.day == day).order_by(EntryRow.id)
    )
    return [row.to_entry() for row in rows]


def _row(session: Session, entry_id: int) -> EntryRow:
    row = session.get(EntryRow, entry_id)
    if row is None:
        raise EntryNotFoundError(f"no Entry {entry_id}")
    return row


def get_entry(session: Session, entry_id: int) -> journal.Entry:
    return _row(session, entry_id).to_entry()


def save_entry(session: Session, entry: journal.Entry) -> journal.Entry:
    """Store the changes to an existing Entry."""
    row = _row(session, entry.id)
    for column, value in _columns(entry).items():
        setattr(row, column, value)
    session.flush()
    return row.to_entry()


def delete_entry(session: Session, entry_id: int) -> None:
    """Delete an Entry permanently."""
    session.delete(_row(session, entry_id))
    session.flush()
