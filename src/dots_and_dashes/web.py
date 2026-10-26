"""The Web module: thin FastAPI routes that parse, call the domain, persist and render."""

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from dots_and_dashes import journal, persistence
from dots_and_dashes.settings import Settings

Clock = Callable[[], datetime]

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
templates.env.filters["as_typed"] = journal.as_typed
templates.env.tests["draggable"] = journal.is_draggable


def _system_clock() -> datetime:
    return datetime.now(UTC)


class NewEntryIn(BaseModel):
    text: str
    day: date | None = None  # the Daily Log to log it on; today when omitted


class MoveIn(BaseModel):
    to: int


class TimeIn(BaseModel):
    time: time


class EditedEntryIn(BaseModel):
    text: str


class EntryOut(BaseModel):
    id: int
    type: journal.EntryType
    state: journal.TaskState | None
    priority: bool
    inspiration: bool
    time: time | None
    text: str
    day: date | None
    location: journal.Location
    month: date | None
    parent_id: int | None
    migrated_from_id: int | None
    migration_count: int


# The User's choice of day to plan, overriding the server's: from 18:00 the
# night before, planning tomorrow, and otherwise today.
Plan = Literal["today", "tomorrow"]


def _night_before(plan: Plan | None) -> bool | None:
    return None if plan is None else plan == "tomorrow"


class MigrationIn(BaseModel):
    """Where to migrate or schedule a Task.

    to is a Daily Log ("day", with date, or else the day being planned), a
    month's task list ("month", with month, or else the day being planned's),
    the Future Log ("future", with month and an optional date), or a date
    ("date"), which lands on its Daily Log this month or in the Future Log.
    The server decides the day being planned; plan overrides it.
    """

    to: Literal["day", "month", "future", "date"]
    on: date | None = Field(None, alias="date")
    month: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")
    plan: Plan | None = None


class MigrationOut(BaseModel):
    original: EntryOut
    copy_: EntryOut = Field(serialization_alias="copy")


class MovedEventIn(BaseModel):
    """An Event's new date: Events move only by changing it."""

    on: date = Field(alias="date")


class DailyLogOut(BaseModel):
    date: date
    entries: list[EntryOut]


class MonthEntryIn(BaseModel):
    text: str


class FutureEntryIn(BaseModel):
    text: str
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    on: date | None = Field(None, alias="date")


class CalendarDayOut(BaseModel):
    date: date
    events: list[EntryOut]


class MonthlyLogOut(BaseModel):
    month: str
    calendar: list[CalendarDayOut]
    tasks: list[EntryOut]


class FutureMonthOut(BaseModel):
    month: str
    entries: list[EntryOut]


class FutureLogOut(BaseModel):
    months: list[FutureMonthOut]


class AnchorGroupOut(BaseModel):
    anchor: EntryOut | None
    tasks: list[EntryOut]


class MigrationDayOut(BaseModel):
    date: date
    groups: list[AnchorGroupOut]


class DailyMigrationOut(BaseModel):
    planning: date
    night_before: bool
    days: list[MigrationDayOut]


class LeftoverDayOut(BaseModel):
    date: date
    tasks: list[EntryOut]


class MonthlyReviewOut(BaseModel):
    month: str
    task_list: list[EntryOut]
    days: list[LeftoverDayOut]
    to_pull: list[EntryOut]
    needs_a_date: list[EntryOut]


def _parse_month(value: str) -> date:
    """Read a month written YYYY-MM as the date of its first day."""
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        raise HTTPException(422, f"{value!r} is not a month") from None


def _month_param(month: Annotated[str, PathParam(pattern=r"^\d{4}-\d{2}$")]) -> date:
    return _parse_month(month)


def _out(entry: journal.Entry) -> EntryOut:
    return EntryOut.model_validate(entry, from_attributes=True)


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker.begin() as session:
        yield session


def _today(request: Request) -> date:
    state = request.app.state
    return journal.today(state.clock(), state.settings.timezone)


# Scoped to the function so its writes commit before the response is sent;
# the default scope would commit after, racing the browser's next request.
SessionDep = Annotated[Session, Depends(_session, scope="function")]
TodayDep = Annotated[date, Depends(_today)]
MonthDep = Annotated[date, Depends(_month_param)]

# The Task State changes the keyboard and the API can ask for, by URL name;
# any other name is refused as invalid.
TaskStateChange = Literal["complete", "cancel", "reopen"]
TASK_STATE_CHANGES: dict[TaskStateChange, Callable[[journal.Entry], journal.Entry]] = {
    "complete": journal.complete,
    "cancel": journal.cancel,
    "reopen": journal.reopen,
}


def _place(session: Session, entry: journal.Entry) -> None:
    """Store an Entry's place on the Daily Log it was logged or moved onto, if any."""
    if entry.location is journal.Location.DAY and entry.day is not None:
        others = [e for e in persistence.entries_on(session, entry.day) if e.id != entry.id]
        persistence.save_daily_log(session, journal.place_on_daily_log(entry, others))


def _add(session: Session, new_entry: journal.NewEntry) -> journal.Entry:
    entry = persistence.add_entry(session, new_entry)
    _place(session, entry)
    return entry


def _change_task_state(
    session: Session, entry_id: int, change: TaskStateChange
) -> journal.Entry:
    act = TASK_STATE_CHANGES[change]
    return persistence.save_entry(session, act(persistence.get_entry(session, entry_id)))


def _edit(session: Session, entry_id: int, text: str) -> journal.Entry:
    edited = journal.edit_entry(persistence.get_entry(session, entry_id), text)
    nested_notes = persistence.nested_notes(session, entry_id)
    for note in journal.notes_released_by_edit(edited, nested_notes):
        persistence.save_entry(session, note)
    return persistence.save_entry(session, edited)


def _destination(body: MigrationIn, planning: date) -> journal.Destination:
    month = _parse_month(body.month) if body.month else None
    match body.to:
        case "day":
            return journal.Destination.daily_log(body.on or planning)
        case "month":
            return journal.Destination.monthly_log(month or planning)
        case "future" if month:
            return journal.Destination.future_log(month, on=body.on)
        case "date" if body.on:
            return journal.schedule_destination(body.on, planning=planning)
    raise HTTPException(422, f"migrating to {body.to!r} needs a date or month")


def _planning(request: Request, plan: Plan | None) -> journal.Planning:
    state = request.app.state
    return journal.daily_migration_planning(
        state.clock(), state.settings.timezone, night_before=_night_before(plan)
    )


def _store_migration(session: Session, migration: journal.Migration) -> journal.Entry:
    """Store a migrated Task and its new copy, moving its Nested Notes; the copy."""
    task = persistence.save_entry(session, migration.original)
    copy = _add(session, migration.copy)
    for note in journal.move_nested_notes(persistence.nested_notes(session, task.id), to=copy):
        _place(session, persistence.save_entry(session, note))
    return copy


def _migrate(
    request: Request, session: Session, entry_id: int, body: MigrationIn
) -> tuple[journal.Entry, journal.Entry]:
    """Migrate or Schedule a Task, moving its Nested Notes; the original and its copy."""
    planning = _planning(request, body.plan).day
    task = persistence.get_entry(session, entry_id)
    migration = journal.migrate(task, to=_destination(body, planning), planning=planning)
    copy = _store_migration(session, migration)
    return persistence.get_entry(session, task.id), copy


def _daily_migration(
    request: Request, session: Session, plan: Plan | None
) -> tuple[journal.Planning, list[journal.MigrationDay]]:
    """The day a Daily Migration run now plans and the Open Tasks it reviews.
    Opening it writes nothing, so it can be skipped."""
    planning = _planning(request, plan)
    return planning, persistence.daily_migration(session, planning.day)


def _pull_from_future_log(session: Session, today: date) -> None:
    """Pull this month's Future Log into its Monthly Log."""
    future = persistence.future_log_month(session, journal.month_of(today))
    pull = journal.pull_from_future_log(future, today=today)
    for migration in pull.migrations:
        _store_migration(session, migration)
    for moved in pull.moved:
        _place(session, persistence.save_entry(session, moved))


def _monthly_review_out(review: journal.MonthlyReview) -> MonthlyReviewOut:
    return MonthlyReviewOut(
        month=f"{review.month:%Y-%m}",
        task_list=[_out(task) for task in review.task_list],
        days=[
            LeftoverDayOut(date=day.day, tasks=[_out(task) for task in day.tasks])
            for day in review.days
        ],
        to_pull=[_out(entry) for entry in review.to_pull],
        needs_a_date=[_out(entry) for entry in review.needs_a_date],
    )


def _move_event(session: Session, entry_id: int, on: date) -> journal.Entry:
    event = persistence.get_entry(session, entry_id)
    moved, notes = journal.move_event(event, persistence.nested_notes(session, entry_id), on=on)
    saved = persistence.save_entry(session, moved)
    _place(session, saved)
    for note in notes:
        _place(session, persistence.save_entry(session, note))
    return saved


def _delete(session: Session, entry_id: int) -> None:
    """Delete an Entry, storing first what the Journal changes to stop pointing at it."""
    for changed in journal.delete_entry(
        persistence.get_entry(session, entry_id),
        successor=persistence.successor(session, entry_id),
        nested_notes=persistence.nested_notes(session, entry_id),
    ):
        persistence.save_entry(session, changed)
    persistence.delete_entry(session, entry_id)


def _entry_fragment(request: Request, entry: journal.Entry) -> Response:
    return templates.TemplateResponse(request, "_entry.html", {"entry": entry})


def _nest(session: Session, entry_id: int) -> journal.Entry:
    entry = persistence.get_entry(session, entry_id)
    daily_log = persistence.entries_on(session, journal.daily_log_day(entry))
    return persistence.save_entry(session, journal.nest_note(entry, daily_log))


def _un_nest(session: Session, entry_id: int) -> journal.Entry:
    entry = persistence.get_entry(session, entry_id)
    return persistence.save_entry(session, journal.un_nest_note(entry))


def _rearrange(
    session: Session,
    entry_id: int,
    change: Callable[[list[journal.Entry]], list[journal.Entry]],
) -> date:
    """Apply an ordering change to the Daily Log holding an Entry, store it,
    and return that Daily Log's day."""
    day = journal.daily_log_day(persistence.get_entry(session, entry_id))
    persistence.save_daily_log(session, change(persistence.entries_on(session, day)))
    return day


# Journal rules that refuse a request, answered 422 with the reason.
REFUSED_AS_INVALID: tuple[type[ValueError], ...] = (
    journal.BlankEntryError,
    journal.PlacementError,
    journal.MigrationError,
    journal.TimedEntryMoveError,
    journal.NestedNoteMoveError,
    journal.UntimedEntryError,
    journal.NestingError,
)


def create_app(settings: Settings | None = None, clock: Clock = _system_clock) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        app.state.sessionmaker = sessionmaker(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Dots & Dashes", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    def refuse(request: Request, exc: Exception) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    for refused in REFUSED_AS_INVALID:
        app.add_exception_handler(refused, refuse)

    def require_monthly_log(month: date, today: date) -> None:
        if not journal.has_monthly_log(month, today=today):
            raise HTTPException(404, "months after the current one have no Monthly Log")

    @app.exception_handler(journal.TaskStateError)
    def refuse_task_state_change(request: Request, exc: journal.TaskStateError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(persistence.EntryNotFoundError)
    def entry_not_found(request: Request, exc: persistence.EntryNotFoundError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    def render_daily_log(request: Request, session: Session, day: date) -> Response:
        return templates.TemplateResponse(
            request,
            "daily_log.html",
            {
                "today": _today(request),
                "day": day,
                "previous_day": day - timedelta(days=1),
                "next_day": day + timedelta(days=1),
                "entries": persistence.entries_on(session, day),
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def todays_daily_log_page(
        request: Request, session: SessionDep, today: TodayDep
    ) -> Response:
        return render_daily_log(request, session, today)

    @app.get("/days")
    def go_to_date(on: Annotated[date, Query(alias="date")]) -> Response:
        return RedirectResponse(f"/days/{on.isoformat()}", status_code=303)

    @app.get("/days/{day}", response_class=HTMLResponse)
    def daily_log_page(request: Request, day: date, session: SessionDep) -> Response:
        return render_daily_log(request, session, day)

    @app.post("/entries")
    def quick_entry(
        request: Request,
        text: Annotated[str, Form()],
        session: SessionDep,
        today: TodayDep,
        day: Annotated[date | None, Form()] = None,
    ) -> Response:
        on = day or today
        _add(session, journal.log_entry(text, on=on))
        if "HX-Request" in request.headers:
            # The whole Daily Log, since a Timed Entry may land anywhere in it.
            return _entries_fragment(request, session, on, status_code=201)
        return RedirectResponse(f"/days/{on.isoformat()}", status_code=303)

    @app.post("/entries/{entry_id}/move")
    def move_entry_on_page(
        request: Request,
        entry_id: int,
        to: Annotated[int, Form()],
        session: SessionDep,
    ) -> Response:
        day = _rearrange(
            session, entry_id, lambda entries: journal.move_entry(entries, entry_id, to=to)
        )
        if "HX-Request" in request.headers:
            return _entries_fragment(request, session, day)
        return RedirectResponse(f"/days/{day.isoformat()}", status_code=303)

    # The nesting, migration and moving routes come before the Task State
    # ones, whose {change} would otherwise also match their names.
    @app.post("/entries/{entry_id}/migrate", response_class=HTMLResponse)
    def migrate_from_page(
        request: Request,
        entry_id: int,
        body: Annotated[MigrationIn, Form()],
        session: SessionDep,
    ) -> Response:
        original, _ = _migrate(request, session, entry_id, body)
        return _entry_fragment(request, original)

    @app.post("/entries/{entry_id}/nest", response_class=HTMLResponse)
    def nest_from_page(request: Request, entry_id: int, session: SessionDep) -> Response:
        entry = _nest(session, entry_id)
        return _entries_fragment(request, session, journal.daily_log_day(entry))

    @app.post("/entries/{entry_id}/un-nest", response_class=HTMLResponse)
    def un_nest_from_page(request: Request, entry_id: int, session: SessionDep) -> Response:
        entry = _un_nest(session, entry_id)
        return _entries_fragment(request, session, journal.daily_log_day(entry))

    def _entries_fragment(
        request: Request, session: Session, day: date, status_code: int = 200
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "_entries.html",
            {"entries": persistence.entries_on(session, day)},
            status_code=status_code,
        )

    @app.post("/entries/{entry_id}/{change}")
    def change_task_state_on_page(
        request: Request, entry_id: int, change: TaskStateChange, session: SessionDep
    ) -> Response:
        return _entry_fragment(request, _change_task_state(session, entry_id, change))

    @app.post("/entries/{entry_id}")
    def edit_entry_on_page(
        request: Request,
        entry_id: int,
        text: Annotated[str, Form()],
        session: SessionDep,
    ) -> Response:
        return _entry_fragment(request, _edit(session, entry_id, text))

    @app.delete("/entries/{entry_id}")
    def delete_entry_on_page(entry_id: int, session: SessionDep) -> Response:
        _delete(session, entry_id)
        # HTMX swaps the Entry's line for this empty body.
        return Response(status_code=200)

    @app.post("/api/entries", status_code=201)
    def create_entry(body: NewEntryIn, session: SessionDep, today: TodayDep) -> EntryOut:
        return _out(_add(session, journal.log_entry(body.text, on=body.day or today)))

    @app.post("/api/entries/{entry_id}/move")
    def move_entry(entry_id: int, body: MoveIn, session: SessionDep) -> DailyLogOut:
        day = _rearrange(
            session,
            entry_id,
            lambda entries: journal.move_entry(entries, entry_id, to=body.to),
        )
        return daily_log_out(session, day)

    @app.post("/api/entries/{entry_id}/time")
    def change_time(entry_id: int, body: TimeIn, session: SessionDep) -> DailyLogOut:
        day = _rearrange(
            session,
            entry_id,
            lambda entries: journal.change_time(entries, entry_id, to=body.time),
        )
        return daily_log_out(session, day)

    @app.post("/api/entries/{entry_id}/nest")
    def nest_entry(entry_id: int, session: SessionDep) -> EntryOut:
        return _out(_nest(session, entry_id))

    @app.post("/api/entries/{entry_id}/un-nest")
    def un_nest_entry(entry_id: int, session: SessionDep) -> EntryOut:
        return _out(_un_nest(session, entry_id))

    @app.post("/api/entries/{entry_id}/migrate")
    def migrate_entry(
        request: Request, entry_id: int, body: MigrationIn, session: SessionDep
    ) -> MigrationOut:
        original, copy = _migrate(request, session, entry_id, body)
        return MigrationOut(original=_out(original), copy_=_out(copy))

    @app.post("/api/entries/{entry_id}/date")
    def move_event(entry_id: int, body: MovedEventIn, session: SessionDep) -> EntryOut:
        return _out(_move_event(session, entry_id, body.on))

    @app.post("/api/entries/{entry_id}/{change}")
    def change_task_state(
        entry_id: int, change: TaskStateChange, session: SessionDep
    ) -> EntryOut:
        return _out(_change_task_state(session, entry_id, change))

    @app.patch("/api/entries/{entry_id}")
    def edit_entry(entry_id: int, body: EditedEntryIn, session: SessionDep) -> EntryOut:
        return _out(_edit(session, entry_id, body.text))

    @app.delete("/api/entries/{entry_id}", status_code=204)
    def delete_entry(entry_id: int, session: SessionDep) -> Response:
        _delete(session, entry_id)
        return Response(status_code=204)

    def daily_log_out(session: Session, day: date) -> DailyLogOut:
        return DailyLogOut(
            date=day,
            entries=[_out(entry) for entry in persistence.entries_on(session, day)],
        )

    @app.get("/api/daily-logs/today")
    def todays_daily_log(session: SessionDep, today: TodayDep) -> DailyLogOut:
        return daily_log_out(session, today)

    # Declared after /today, so "today" is never read as a date.
    @app.get("/api/daily-logs/{day}")
    def daily_log(day: date, session: SessionDep) -> DailyLogOut:
        return daily_log_out(session, day)

    @app.get("/months")
    def current_monthly_log_page(today: TodayDep) -> Response:
        return RedirectResponse(f"/months/{today:%Y-%m}", status_code=303)

    @app.get("/months/{month}", response_class=HTMLResponse)
    def monthly_log_page(
        request: Request, month: MonthDep, session: SessionDep, today: TodayDep
    ) -> Response:
        require_monthly_log(month, today)
        calendar, tasks = persistence.monthly_log(session, month)
        next_month = journal.next_month(month)
        return templates.TemplateResponse(
            request,
            "monthly_log.html",
            {
                "today": today,
                "month": month,
                "previous_month": journal.previous_month(month),
                "next_month": next_month
                if journal.has_monthly_log(next_month, today=today)
                else None,
                "calendar": calendar,
                "tasks": tasks,
                "monthly_review": settings.monthly_review,
            },
        )

    @app.post("/months/{month}/entries")
    def add_to_monthly_log(
        month: MonthDep,
        text: Annotated[str, Form()],
        session: SessionDep,
        today: TodayDep,
    ) -> Response:
        _add(session, journal.log_month_entry(text, month=month, today=today))
        return RedirectResponse(f"/months/{month:%Y-%m}", status_code=303)

    @app.get("/api/monthly-logs/{month}")
    def monthly_log(month: MonthDep, session: SessionDep, today: TodayDep) -> MonthlyLogOut:
        require_monthly_log(month, today)
        calendar, tasks = persistence.monthly_log(session, month)
        return MonthlyLogOut(
            month=f"{month:%Y-%m}",
            calendar=[
                CalendarDayOut(date=day.day, events=[_out(e) for e in day.events])
                for day in calendar
            ],
            tasks=[_out(entry) for entry in tasks],
        )

    @app.post("/api/monthly-logs/{month}/entries", status_code=201)
    def create_monthly_log_entry(
        month: MonthDep, body: MonthEntryIn, session: SessionDep, today: TodayDep
    ) -> EntryOut:
        return _out(
            _add(session, journal.log_month_entry(body.text, month=month, today=today))
        )

    @app.get("/migration", response_class=HTMLResponse)
    def daily_migration_page(
        request: Request, session: SessionDep, today: TodayDep, plan: Plan | None = None
    ) -> Response:
        planning, review = _daily_migration(request, session, plan)
        return templates.TemplateResponse(
            request,
            "daily_migration.html",
            {
                "today": today,
                "planning": planning.day,
                "night_before": planning.night_before,
                "review": review,
            },
        )

    @app.get("/api/daily-migration")
    def daily_migration(
        request: Request, session: SessionDep, plan: Plan | None = None
    ) -> DailyMigrationOut:
        planning, review = _daily_migration(request, session, plan)
        return DailyMigrationOut(
            planning=planning.day,
            night_before=planning.night_before,
            days=[
                MigrationDayOut(
                    date=day.day,
                    groups=[
                        AnchorGroupOut(
                            anchor=_out(group.anchor) if group.anchor else None,
                            tasks=[_out(task) for task in group.tasks],
                        )
                        for group in day.groups
                    ],
                )
                for day in review
            ],
        )

    # Behind the FLAG_MONTHLY_REVIEW feature flag: with it off these routes
    # don't exist, so they answer 404, and the Monthly Log doesn't link here.
    if settings.monthly_review:

        @app.get("/monthly-review", response_class=HTMLResponse)
        def monthly_review_page(
            request: Request, session: SessionDep, today: TodayDep
        ) -> Response:
            review = persistence.monthly_review(session, today)
            return templates.TemplateResponse(
                request,
                "monthly_review.html",
                {
                    "today": today,
                    "review": review,
                    "last_month": journal.previous_month(review.month),
                    "last_day": journal.next_month(review.month) - timedelta(days=1),
                },
            )

        @app.post("/monthly-review/pull")
        def pull_from_page(session: SessionDep, today: TodayDep) -> Response:
            _pull_from_future_log(session, today)
            return RedirectResponse("/monthly-review", status_code=303)

        @app.post("/monthly-review/entries/{entry_id}/date")
        def date_event_from_page(
            entry_id: int,
            on: Annotated[date, Form(alias="date")],
            session: SessionDep,
        ) -> Response:
            _move_event(session, entry_id, on)
            return RedirectResponse("/monthly-review", status_code=303)

        @app.get("/api/monthly-review")
        def monthly_review(session: SessionDep, today: TodayDep) -> MonthlyReviewOut:
            return _monthly_review_out(persistence.monthly_review(session, today))

        @app.post("/api/monthly-review/pull")
        def pull(session: SessionDep, today: TodayDep) -> MonthlyReviewOut:
            _pull_from_future_log(session, today)
            return _monthly_review_out(persistence.monthly_review(session, today))

    @app.get("/future", response_class=HTMLResponse)
    def future_log_page(request: Request, session: SessionDep, today: TodayDep) -> Response:
        return templates.TemplateResponse(
            request,
            "future_log.html",
            {
                "today": today,
                "first_month": journal.next_month(journal.month_of(today)),
                "future_log": persistence.future_log(session, today),
            },
        )

    @app.post("/future/entries")
    def add_to_future_log(
        text: Annotated[str, Form()],
        month: Annotated[str, Form(pattern=r"^\d{4}-\d{2}$")],
        session: SessionDep,
        today: TodayDep,
        # An empty date field reads as no date.
        on: Annotated[date | None, Form(alias="date")] = None,
    ) -> Response:
        _add(
            session,
            journal.log_future_entry(text, month=_parse_month(month), on=on, today=today),
        )
        return RedirectResponse("/future", status_code=303)

    @app.get("/api/future-log")
    def future_log(session: SessionDep, today: TodayDep) -> FutureLogOut:
        return FutureLogOut(
            months=[
                FutureMonthOut(
                    month=f"{bucket.month:%Y-%m}",
                    entries=[_out(entry) for entry in bucket.entries],
                )
                for bucket in persistence.future_log(session, today)
            ]
        )

    @app.post("/api/future-log/entries", status_code=201)
    def create_future_log_entry(
        body: FutureEntryIn, session: SessionDep, today: TodayDep
    ) -> EntryOut:
        return _out(
            _add(
                session,
                journal.log_future_entry(
                    body.text, month=_parse_month(body.month), on=body.on, today=today
                ),
            )
        )

    return app
