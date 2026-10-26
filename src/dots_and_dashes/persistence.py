"""The Persistence module: maps Journal domain values to Postgres tables."""

from datetime import date, datetime
from datetime import time as TimeOfDay

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
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


def add_entry(session: Session, new_entry: journal.NewEntry) -> journal.Entry:
    row = EntryRow(
        type=new_entry.type,
        state=new_entry.state,
        priority=new_entry.priority,
        inspiration=new_entry.inspiration,
        time=new_entry.time,
        text=new_entry.text,
        day=new_entry.day,
    )
    session.add(row)
    session.flush()
    return row.to_entry()


def entries_on(session: Session, day: date) -> list[journal.Entry]:
    rows = session.scalars(
        select(EntryRow).where(EntryRow.day == day).order_by(EntryRow.id)
    )
    return journal.arrange_daily_log([row.to_entry() for row in rows])


def get_entry(session: Session, entry_id: int) -> journal.Entry | None:
    row = session.get(EntryRow, entry_id)
    return row.to_entry() if row else None


def set_parent(session: Session, entry: journal.Entry) -> journal.Entry:
    """Store whether an Entry is a Nested Note, and under which parent."""
    row = session.get_one(EntryRow, entry.id)
    row.parent_id = entry.parent_id
    session.flush()
    return row.to_entry()
