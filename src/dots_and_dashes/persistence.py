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


def add_entry(session: Session, new: journal.NewEntry) -> journal.Entry:
    row = EntryRow(type=new.type, state=new.state, text=new.text, day=new.day)
    session.add(row)
    session.flush()
    return row.to_entry()


def entries_on(session: Session, day: date) -> list[journal.Entry]:
    rows = session.scalars(
        select(EntryRow).where(EntryRow.day == day).order_by(EntryRow.id)
    )
    return [row.to_entry() for row in rows]
