"""The Persistence module: maps Journal domain values to Postgres tables."""

from datetime import date, datetime
from datetime import time as TimeOfDay

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
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
    # A day for Daily Log Entries, and optionally for Future Log ones.
    day: Mapped[date | None] = mapped_column(Date, index=True)
    location: Mapped[str] = mapped_column(String(16), server_default="day")
    # The month, as its first day, for the Monthly Log and Future Log.
    month: Mapped[date | None] = mapped_column(Date, index=True)
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
            location=journal.Location(self.location),
            month=self.month,
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
        location=new_entry.location,
        month=new_entry.month,
    )
    session.add(row)
    session.flush()
    return row.to_entry()


def entries_on(session: Session, day: date) -> list[journal.Entry]:
    rows = session.scalars(
        select(EntryRow)
        .where(EntryRow.location == journal.Location.DAY, EntryRow.day == day)
        .order_by(EntryRow.id)
    )
    return journal.daily_log_order([row.to_entry() for row in rows])


def monthly_log(
    session: Session, month: date
) -> tuple[list[journal.CalendarDay], list[journal.Entry]]:
    """A Monthly Log's calendar and its task list."""
    month = journal.month_of(month)
    days = session.scalars(
        select(EntryRow)
        .where(
            EntryRow.location == journal.Location.DAY,
            EntryRow.type == journal.EntryType.EVENT,
            EntryRow.day >= month,
            EntryRow.day < journal.next_month(month),
        )
        .order_by(EntryRow.id)
    )
    tasks = session.scalars(
        select(EntryRow)
        .where(EntryRow.location == journal.Location.MONTH, EntryRow.month == month)
        .order_by(EntryRow.id)
    )
    calendar = journal.monthly_calendar(month, [row.to_entry() for row in days])
    return calendar, [row.to_entry() for row in tasks]


def future_log(session: Session, today: date) -> list[journal.FutureMonth]:
    rows = session.scalars(
        select(EntryRow)
        .where(
            EntryRow.location == journal.Location.FUTURE,
            EntryRow.month > journal.month_of(today),
        )
        .order_by(EntryRow.id)
    )
    return journal.future_log([row.to_entry() for row in rows], today=today)
