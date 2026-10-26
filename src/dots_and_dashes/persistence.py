"""The Persistence module: maps Journal domain values to Postgres tables."""

from datetime import date, datetime
from datetime import time as TimeOfDay

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    Time,
    false,
    func,
    select,
)
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
    priority: Mapped[bool] = mapped_column(Boolean, server_default=false())
    inspiration: Mapped[bool] = mapped_column(Boolean, server_default=false())
    time: Mapped[TimeOfDay | None] = mapped_column(Time)
    text: Mapped[str] = mapped_column(Text)
    day: Mapped[date] = mapped_column(Date, index=True)
    # Manual position within its Daily Log; the Journal module orders by it.
    position: Mapped[int] = mapped_column(Integer)
    # A Nested Note's parent Task or Event.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_entry(self) -> journal.Entry:
        return journal.Entry(
            id=self.id,
            type=journal.EntryType(self.type),
            state=journal.TaskState(self.state) if self.state else None,
            priority=self.priority,
            inspiration=self.inspiration,
            time=self.time,
            text=self.text,
            day=self.day,
            parent_id=self.parent_id,
        )


class EntryNotFoundError(LookupError):
    """Raised when no stored Entry has the id asked for."""


def _columns(entry: journal.NewEntry | journal.Entry) -> dict[str, object]:
    """The stored columns for an Entry; adding and saving both write these."""
    columns: dict[str, object] = {
        "type": entry.type,
        "state": entry.state,
        "priority": entry.priority,
        "inspiration": entry.inspiration,
        "time": entry.time,
        "text": entry.text,
        "day": entry.day,
    }
    if isinstance(entry, journal.Entry):
        # Only a stored Entry can be a Nested Note; saving keeps it nested.
        columns["parent_id"] = entry.parent_id
    return columns


def add_entry(session: Session, new_entry: journal.NewEntry) -> journal.Entry:
    row = EntryRow(
        **_columns(new_entry),
        # A new Entry goes to the bottom of its Daily Log.
        position=select(func.coalesce(func.max(EntryRow.position), 0) + 1)
        .where(EntryRow.day == new_entry.day)
        .scalar_subquery(),
    )
    session.add(row)
    session.flush()
    # A new Timed Entry slots in by its time, so store the Daily Log as it now
    # shows: the manual order is always the order on the page.
    save_daily_log(session, entries_on(session, new_entry.day))
    return row.to_entry()


def entries_on(session: Session, day: date) -> list[journal.Entry]:
    rows = session.scalars(
        select(EntryRow)
        .where(EntryRow.day == day)
        .order_by(EntryRow.position, EntryRow.id)
    )
    return journal.arrange_daily_log([row.to_entry() for row in rows])


def save_daily_log(session: Session, entries: list[journal.Entry]) -> None:
    """Store a Daily Log's Entries, in order, as its manual order, with their times."""
    for position, entry in enumerate(entries, start=1):
        row = session.get_one(EntryRow, entry.id)
        row.position = position
        row.time = entry.time
    session.flush()


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
