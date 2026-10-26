"""The Persistence module: maps Journal domain values to Postgres tables."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime
from datetime import time as TimeOfDay
from zoneinfo import ZoneInfo

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
    event,
    false,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    ORMExecuteState,
    Session,
    mapped_column,
    with_loader_criteria,
)

from dots_and_dashes import accounts, journal

# The session.info key naming the User a session reads and writes the journal of.
USER_ID = "user_id"


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    # An IANA name, such as America/Los_Angeles.
    timezone: Mapped[str] = mapped_column(String(64))
    canary: Mapped[bool] = mapped_column(Boolean, server_default=false())

    def to_user(self) -> accounts.User:
        return accounts.User(
            id=self.id, email=self.email, timezone=ZoneInfo(self.timezone), canary=self.canary
        )


class EntryRow(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    # Entries logged before Users existed have none until the first User claims them.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
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
    # Manual position within its Daily Log, as the Journal module ordered it.
    # Monthly Log and Future Log Entries have one too, but nothing orders by it.
    position: Mapped[int] = mapped_column(Integer)
    # A Nested Note's parent Task or Event. The Journal un-nests a deleted
    # parent's Notes; SET NULL is only a safety net.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL")
    )
    # The copy this one was migrated or scheduled from, in its Migration Chain.
    migrated_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), index=True
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
            location=journal.Location(self.location),
            month=self.month,
            parent_id=self.parent_id,
            migrated_from_id=self.migrated_from_id,
        )


class CaptureRow(Base):
    __tablename__ = "captures"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Raw, exactly as captured: Triage reads it with the Prefix rules.
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_capture(self) -> journal.Capture:
        return journal.Capture(id=self.id, text=self.text)


@event.listens_for(Session, "do_orm_execute")
def _only_the_users_entries(state: ORMExecuteState) -> None:
    """Every Entry and Capture a session reads is its User's. A session with no
    User reads none."""
    if not state.is_select:
        return
    user_id = state.session.info.get(USER_ID)
    owned = (lambda cls: cls.user_id == user_id) if user_id is not None else (lambda cls: false())
    state.statement = state.statement.options(
        with_loader_criteria(EntryRow, owned, include_aliases=True),
        with_loader_criteria(CaptureRow, owned, include_aliases=True),
    )


def _user_id(session: Session) -> int:
    try:
        return session.info[USER_ID]
    except KeyError:
        raise RuntimeError("this session has no User to log Entries for") from None


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
        "location": entry.location,
        "month": entry.month,
        "migrated_from_id": entry.migrated_from_id,
    }
    if isinstance(entry, journal.Entry):
        # Only a stored Entry can be a Nested Note; saving keeps it nested.
        columns["parent_id"] = entry.parent_id
    return columns


def _chain_links(session: Session, ids: set[int]) -> dict[int, int | None]:
    """The Migration Chain links of the chains these Entries are in: id to migrated-from id."""
    links: dict[int, int | None] = {}
    seen: set[int] = set()
    frontier = ids
    while frontier:
        seen |= frontier
        rows = session.execute(
            select(EntryRow.id, EntryRow.migrated_from_id).where(
                or_(EntryRow.id.in_(frontier), EntryRow.migrated_from_id.in_(frontier))
            )
        ).all()
        links.update({id: earlier for id, earlier in rows})
        reached = {id for id, _ in rows} | {earlier for _, earlier in rows if earlier}
        frontier = reached - seen
    return links


def _loaded(session: Session, rows: Iterable[EntryRow]) -> list[journal.Entry]:
    """Entries from their rows, each with its Migration Count."""
    entries = [row.to_entry() for row in rows]
    linked = {e.id for e in entries if e.type == journal.EntryType.TASK}
    links = _chain_links(session, linked) if linked else {}
    return [
        replace(entry, migration_count=journal.migration_count(entry.id, links))
        if entry.id in linked
        else entry
        for entry in entries
    ]


def add_entry(session: Session, new_entry: journal.NewEntry) -> journal.Entry:
    """Store a new Entry. Its place in a Daily Log's order is stored with save_daily_log."""
    row = EntryRow(**_columns(new_entry), user_id=_user_id(session), position=0)
    session.add(row)
    session.flush()
    [entry] = _loaded(session, [row])
    return entry


def entries_on(session: Session, day: date) -> list[journal.Entry]:
    rows = session.scalars(
        select(EntryRow)
        .where(EntryRow.location == journal.Location.DAY, EntryRow.day == day)
        .order_by(EntryRow.position, EntryRow.id)
    )
    return journal.arrange_daily_log(_loaded(session, rows))


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
    return calendar, journal.arrange_task_list(_loaded(session, tasks))


def future_log(session: Session, today: date) -> list[journal.FutureMonth]:
    rows = session.scalars(
        select(EntryRow)
        .where(
            EntryRow.location == journal.Location.FUTURE,
            EntryRow.month > journal.month_of(today),
        )
        .order_by(EntryRow.id)
    )
    return journal.future_log(_loaded(session, rows), today=today)


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
    [entry] = _loaded(session, [_row(session, entry_id)])
    return entry


def nested_notes(session: Session, parent_id: int) -> list[journal.Entry]:
    """The Nested Notes under a Task or Event, in the order they were logged."""
    rows = session.scalars(
        select(EntryRow).where(EntryRow.parent_id == parent_id).order_by(EntryRow.id)
    )
    return [row.to_entry() for row in rows]


def successor(session: Session, entry_id: int) -> journal.Entry | None:
    """The copy migrated or scheduled from an Entry, if any."""
    row = session.scalars(select(EntryRow).where(EntryRow.migrated_from_id == entry_id)).first()
    return row.to_entry() if row else None


def save_entry(session: Session, entry: journal.Entry) -> journal.Entry:
    """Store the changes to an existing Entry. Its place in a Daily Log's order
    is stored with save_daily_log."""
    row = _row(session, entry.id)
    for column, value in _columns(entry).items():
        setattr(row, column, value)
    session.flush()
    [saved] = _loaded(session, [row])
    return saved


def delete_entry(session: Session, entry_id: int) -> None:
    """Delete an Entry permanently."""
    session.delete(_row(session, entry_id))
    session.flush()


def daily_migration(session: Session, planning: date) -> list[journal.MigrationDay]:
    """The Daily Migration for a day being planned. It only reads."""
    days = (
        select(EntryRow.day)
        .where(
            EntryRow.location == journal.Location.DAY,
            EntryRow.type == journal.EntryType.TASK,
            EntryRow.state == journal.TaskState.OPEN,
            EntryRow.day < planning,
        )
        .distinct()
    )
    # Whole Daily Logs, in manual order, so each Open Task's Anchor is found.
    rows = session.scalars(
        select(EntryRow)
        .where(EntryRow.location == journal.Location.DAY, EntryRow.day.in_(days))
        .order_by(EntryRow.day, EntryRow.position, EntryRow.id)
    )
    return journal.daily_migration(_loaded(session, rows), planning=planning)


def monthly_review(session: Session, today: date) -> journal.MonthlyReview:
    """The Monthly Review of the User's current month. It only reads."""
    month = journal.month_of(today)
    last_month = journal.previous_month(month)
    # Last month's Daily Logs in manual order, so each keeps its Daily Log order.
    days = session.scalars(
        select(EntryRow)
        .where(
            EntryRow.location == journal.Location.DAY,
            EntryRow.day >= last_month,
            EntryRow.day < month,
        )
        .order_by(EntryRow.day, EntryRow.position, EntryRow.id)
    )
    task_list = session.scalars(
        select(EntryRow)
        .where(EntryRow.location == journal.Location.MONTH, EntryRow.month == last_month)
        .order_by(EntryRow.id)
    )
    entries = [
        *_loaded(session, days),
        *_loaded(session, task_list),
        *future_log_month(session, month),
    ]
    return journal.monthly_review(entries, today=today)


def future_log_month(session: Session, month: date) -> list[journal.Entry]:
    """A month's Future Log Entries, in the order they were logged."""
    rows = session.scalars(
        select(EntryRow)
        .where(EntryRow.location == journal.Location.FUTURE, EntryRow.month == month)
        .order_by(EntryRow.id)
    )
    return _loaded(session, rows)


class CaptureNotFoundError(LookupError):
    """Raised when no stored Capture in the Inbox has the id asked for."""


def add_capture(session: Session, new_capture: journal.NewCapture) -> journal.Capture:
    """Store a Capture in the User's Inbox."""
    row = CaptureRow(text=new_capture.text, user_id=_user_id(session))
    session.add(row)
    session.flush()
    return row.to_capture()


def inbox(session: Session) -> list[journal.Capture]:
    """The Captures in the Inbox, in the order they were captured."""
    rows = session.scalars(select(CaptureRow).order_by(CaptureRow.id))
    return [row.to_capture() for row in rows]


def inbox_count(session: Session) -> int:
    """How many Captures are waiting in the Inbox."""
    return session.scalar(select(func.count(CaptureRow.id))) or 0


def _capture_row(session: Session, capture_id: int) -> CaptureRow:
    row = session.get(CaptureRow, capture_id)
    if row is None:
        raise CaptureNotFoundError(f"no Capture {capture_id} in the Inbox")
    return row


def get_capture(session: Session, capture_id: int) -> journal.Capture:
    return _capture_row(session, capture_id).to_capture()


def delete_capture(session: Session, capture_id: int) -> None:
    """Take a Capture out of the Inbox for good: Deleted, or Triaged into an Entry."""
    session.delete(_capture_row(session, capture_id))
    session.flush()


class DuplicateUserError(ValueError):
    """Raised when a User with that email already exists."""


def create_user(
    session: Session, email: str, password_hash: str, timezone: ZoneInfo, *, canary: bool
) -> accounts.User:
    """Store a new User. The first real User claims the Entries logged before Users existed."""
    email = accounts.normalise_email(email)
    if session.scalars(select(UserRow).where(UserRow.email == email)).first():
        raise DuplicateUserError(f"a User with email {email!r} already exists")
    row = UserRow(email=email, password_hash=password_hash, timezone=timezone.key, canary=canary)
    session.add(row)
    session.flush()
    if not canary:
        session.execute(
            update(EntryRow).where(EntryRow.user_id.is_(None)).values(user_id=row.id)
        )
    return row.to_user()


def user_by_email(session: Session, email: str) -> tuple[accounts.User, str] | None:
    """The User with an email, and their password hash."""
    row = session.scalars(
        select(UserRow).where(UserRow.email == accounts.normalise_email(email))
    ).first()
    return (row.to_user(), row.password_hash) if row else None


def get_user(session: Session, user_id: int) -> accounts.User | None:
    row = session.get(UserRow, user_id)
    return row.to_user() if row else None
