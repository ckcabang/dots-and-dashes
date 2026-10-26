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
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from dots_and_dashes import accounts, journal, persistence
from dots_and_dashes.chaos import SaveChaos
from dots_and_dashes.settings import Settings
from dots_and_dashes.telemetry import RequestTelemetry, Telemetry

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

    to: journal.DestinationChoice
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


class FutureEntryForm(BaseModel):
    """FutureEntryIn as the Future Log page sends it: the month and date as
    typed, read once the form is in, so an impossible one is refused on the page."""

    text: str
    month: str
    on: str | None = Field(None, alias="date")


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


class WaitingEventOut(BaseModel):
    event: EntryOut
    notes: list[EntryOut]


class MonthlyReviewOut(BaseModel):
    month: str
    task_list: list[EntryOut]
    days: list[LeftoverDayOut]
    to_pull: list[EntryOut]
    needs_a_date: list[WaitingEventOut]


class NewCaptureIn(BaseModel):
    text: str


class SuggestionOut(BaseModel):
    """What Triage suggests a Capture becomes, and that written as typed, to adjust."""

    type: journal.EntryType
    priority: bool
    inspiration: bool
    time: time | None
    text: str
    typed: str


class CaptureOut(BaseModel):
    id: int
    text: str
    suggestion: SuggestionOut


class TriageIn(BaseModel):
    """Where to place a Capture, and its text as adjusted.

    to is a Daily Log ("day", with date, or else today's), the current
    month's task list ("month"), the Future Log ("future", with month and an
    optional date), or a date ("date"), which lands on its Daily Log this
    month or in the Future Log. Without text, the Capture's own text is read.
    """

    to: journal.DestinationChoice
    text: str | None = None
    on: date | None = Field(None, alias="date")
    month: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")


class TriageForm(BaseModel):
    """TriageIn as the Triage page sends it: the date and month as typed,
    read once the form is in, so an impossible one is refused on the page."""

    to: journal.DestinationChoice
    text: str | None = None
    on: str | None = Field(None, alias="date")
    month: str | None = None


class InboxOut(BaseModel):
    count: int
    captures: list[CaptureOut]


class UnreadableDateError(ValueError):
    """Raised for a date or month, as typed, that is no real day or month."""


def _parse_month(value: str) -> date:
    """Read a month written YYYY-MM as the date of its first day."""
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        raise UnreadableDateError(f"{value!r} is not a month") from None


def _optional_month(value: str | None) -> date | None:
    return _parse_month(value) if value else None


def _optional_date(value: str | None) -> date | None:
    """Read a date written YYYY-MM-DD, if one was."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UnreadableDateError(f"{value!r} is not a date") from None


def _month_param(month: Annotated[str, PathParam(pattern=r"^\d{4}-\d{2}$")]) -> date:
    return _parse_month(month)


def _out(entry: journal.Entry) -> EntryOut:
    return EntryOut.model_validate(entry, from_attributes=True)


def _capture_out(capture: journal.Capture) -> CaptureOut:
    suggestion = journal.triage_suggestion(capture)
    return CaptureOut(
        id=capture.id,
        text=capture.text,
        suggestion=SuggestionOut(
            type=suggestion.type,
            priority=suggestion.priority,
            inspiration=suggestion.inspiration,
            time=suggestion.time,
            text=suggestion.text,
            typed=journal.as_typed(suggestion),
        ),
    )


# A login lasts 30 days, on desktop and phone alike. The session lives only in
# its signed cookie, so logging out clears the cookie in that browser; a copy
# taken earlier stays valid until it expires.
SESSION_MAX_AGE = 30 * 24 * 60 * 60
# The session cookie's key for the logged-in User's id.
SESSION_USER = "user_id"


class LoginRequiredError(Exception):
    """Raised when a journal page or API route is asked for without a session."""


def _current_user(request: Request) -> accounts.User:
    """The logged-in User, from the signed session cookie."""
    user_id = request.session.get(SESSION_USER)
    if user_id is not None:
        with request.app.state.sessionmaker() as session:
            if user := persistence.get_user(session, user_id):
                return user
    raise LoginRequiredError


UserDep = Annotated[accounts.User, Depends(_current_user)]


def _session(request: Request, user: UserDep) -> Iterator[Session]:
    """A database session that reads and writes only the logged-in User's journal."""
    with request.app.state.sessionmaker(info={persistence.USER_ID: user.id}) as session:
        with session.begin():
            yield session


def _today(request: Request, user: UserDep) -> date:
    return journal.today(request.app.state.clock(), user.timezone)


# Scoped to the function so its writes commit before the response is sent;
# the default scope would commit after, racing the browser's next request.
SessionDep = Annotated[Session, Depends(_session, scope="function")]
TodayDep = Annotated[date, Depends(_today)]
MonthDep = Annotated[date, Depends(_month_param)]


def _save_chaos(request: Request, session: SessionDep) -> None:
    """With the chaos switch on, fail or slow this Entry save. It holds its
    database connection meanwhile, the way a struggling database would."""
    chaos: SaveChaos = request.app.state.save_chaos
    if chaos.on:
        session.connection()
        chaos.save()


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


def _planning(request: Request, user: accounts.User, plan: Plan | None) -> journal.Planning:
    return journal.daily_migration_planning(
        request.app.state.clock(), user.timezone, night_before=_night_before(plan)
    )


def _store_migration(session: Session, migration: journal.Migration) -> journal.Entry:
    """Store a migrated Task and its new copy, moving its Nested Notes; the copy."""
    task = persistence.save_entry(session, migration.original)
    copy = _add(session, migration.copy)
    for note in journal.move_nested_notes(persistence.nested_notes(session, task.id), to=copy):
        _place(session, persistence.save_entry(session, note))
    return copy


def _migrate(
    request: Request, user: accounts.User, session: Session, entry_id: int, body: MigrationIn
) -> tuple[journal.Entry, journal.Entry]:
    """Migrate or Schedule a Task, moving its Nested Notes; the original and its copy."""
    planning = _planning(request, user, body.plan).day
    task = persistence.get_entry(session, entry_id)
    to = journal.destination(
        body.to, on=body.on, month=_optional_month(body.month), planning=planning
    )
    migration = journal.migrate(task, to=to, planning=planning)
    copy = _store_migration(session, migration)
    return persistence.get_entry(session, task.id), copy


def _daily_migration(
    request: Request, user: accounts.User, session: Session, plan: Plan | None
) -> tuple[journal.Planning, list[journal.MigrationDay]]:
    """The day a Daily Migration run now plans and the Open Tasks it reviews.
    Opening it writes nothing, so it can be skipped."""
    planning = _planning(request, user, plan)
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
        needs_a_date=[
            WaitingEventOut(event=_out(w.event), notes=[_out(note) for note in w.notes])
            for w in review.needs_a_date
        ],
    )


def _move_event(session: Session, entry_id: int, on: date) -> journal.Entry:
    event = persistence.get_entry(session, entry_id)
    moved, notes = journal.move_event(event, persistence.nested_notes(session, entry_id), on=on)
    return _store_moved_event(session, moved, notes)


def _date_waiting_event(session: Session, entry_id: int, on: date, today: date) -> None:
    event = persistence.get_entry(session, entry_id)
    nested_notes = persistence.nested_notes(session, entry_id)
    moved, notes = journal.date_waiting_event(event, nested_notes, on=on, today=today)
    _store_moved_event(session, moved, notes)


def _store_moved_event(
    session: Session, moved: journal.Entry, notes: list[journal.Entry]
) -> journal.Entry:
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


def _triage(
    session: Session,
    capture_id: int,
    *,
    to: journal.DestinationChoice,
    on: date | None,
    month: date | None,
    text: str | None,
    today: date,
) -> journal.Entry:
    """Turn a Capture into an Entry where it was placed, taking it out of the Inbox."""
    capture = persistence.get_capture(session, capture_id)
    destination = journal.destination(to, on=on, month=month, planning=today)
    entry = _add(session, journal.triage(capture, text=text, to=destination, today=today))
    persistence.delete_capture(session, capture_id)
    return entry


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


# Journal rules that refuse a request, and dates that are no real day or
# month, answered 422 with the reason.
REFUSED_AS_INVALID: tuple[type[ValueError], ...] = (
    UnreadableDateError,
    journal.BlankEntryError,
    journal.BlankCaptureError,
    journal.PlacementError,
    journal.MigrationError,
    journal.TimedEntryMoveError,
    journal.NestedNoteMoveError,
    journal.UntimedEntryError,
    journal.NestingError,
)


# The key journey, logging an Entry on a Daily Log from the page or the API:
# the requests the save metrics count and time.
ENTRY_SAVES = {("POST", "/entries"), ("POST", "/api/entries")}


def _pool_size(settings: Settings) -> dict[str, int]:
    """With DB_POOL_SIZE set, the app holds at most that many connections;
    unset, SQLAlchemy's own pool of 5 plus 10 overflow."""
    if settings.db_pool_size is None:
        return {}
    return {"pool_size": settings.db_pool_size, "max_overflow": 0}


def create_app(
    settings: Settings | None = None,
    clock: Clock = _system_clock,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    telemetry = telemetry or Telemetry.from_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = telemetry.create_engine(
            settings.database_url, pool_pre_ping=True, **_pool_size(settings)
        )
        app.state.sessionmaker = sessionmaker(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Dots & Dashes", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock
    app.state.save_chaos = SaveChaos.from_settings(settings)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=settings.secure_cookies,
    )
    # Outermost, so its span covers every other middleware and the route.
    app.add_middleware(RequestTelemetry, telemetry=telemetry, entry_saves=ENTRY_SAVES)
    app.state.telemetry = telemetry
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.exception_handler(LoginRequiredError)
    def login_required(request: Request, exc: LoginRequiredError) -> Response:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "log in first"}, status_code=401)
        if "HX-Request" in request.headers:
            # HTMX would swap a followed redirect's login page into the journal.
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse("/login", status_code=303)

    # There is no sign-up route: Users are created with `dots-and-dashes create-user`.
    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        return templates.TemplateResponse(request, "login.html", {})

    @app.post("/login")
    def log_in(
        request: Request,
        email: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> Response:
        with app.state.sessionmaker() as session:
            found = persistence.user_by_email(session, email)
        user, password_hash = found if found else (None, None)
        # Checked even with no such User, so a wrong email is as slow to refuse.
        matched = accounts.password_matches(password_hash, password)
        if user is None or not matched:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"email": email, "refused": True},
                status_code=401,
            )
        request.session.clear()
        request.session[SESSION_USER] = user.id
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def log_out(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

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
    @app.exception_handler(persistence.CaptureNotFoundError)
    def not_found(request: Request, exc: LookupError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    def render_daily_log(request: Request, session: Session, day: date, today: date) -> Response:
        return templates.TemplateResponse(
            request,
            "daily_log.html",
            {
                "today": today,
                "day": day,
                "previous_day": day - timedelta(days=1),
                "next_day": day + timedelta(days=1),
                "entries": persistence.entries_on(session, day),
                "inbox_count": persistence.inbox_count(session),
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def todays_daily_log_page(
        request: Request, session: SessionDep, today: TodayDep
    ) -> Response:
        return render_daily_log(request, session, today, today)

    @app.get("/days", dependencies=[Depends(_current_user)])
    def go_to_date(on: Annotated[date, Query(alias="date")]) -> Response:
        return RedirectResponse(f"/days/{on.isoformat()}", status_code=303)

    @app.get("/days/{day}", response_class=HTMLResponse)
    def daily_log_page(
        request: Request, day: date, session: SessionDep, today: TodayDep
    ) -> Response:
        return render_daily_log(request, session, day, today)

    @app.post("/entries", dependencies=[Depends(_save_chaos)])
    def quick_entry(
        request: Request,
        text: Annotated[str, Form()],
        session: SessionDep,
        today: TodayDep,
        day: Annotated[date | None, Form()] = None,
    ) -> Response:
        on = day or today
        request.app.state.telemetry.entry_saved(_add(session, journal.log_entry(text, on=on)))
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
        user: UserDep,
        session: SessionDep,
    ) -> Response:
        original, _ = _migrate(request, user, session, entry_id, body)
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

    @app.post("/api/entries", status_code=201, dependencies=[Depends(_save_chaos)])
    def create_entry(
        request: Request, body: NewEntryIn, session: SessionDep, today: TodayDep
    ) -> EntryOut:
        entry = _add(session, journal.log_entry(body.text, on=body.day or today))
        request.app.state.telemetry.entry_saved(entry)
        return _out(entry)

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
        request: Request, entry_id: int, body: MigrationIn, user: UserDep, session: SessionDep
    ) -> MigrationOut:
        original, copy = _migrate(request, user, session, entry_id, body)
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
        request: Request,
        user: UserDep,
        session: SessionDep,
        today: TodayDep,
        plan: Plan | None = None,
    ) -> Response:
        planning, review = _daily_migration(request, user, session, plan)
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
        request: Request, user: UserDep, session: SessionDep, plan: Plan | None = None
    ) -> DailyMigrationOut:
        planning, review = _daily_migration(request, user, session, plan)
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
            today: TodayDep,
        ) -> Response:
            _date_waiting_event(session, entry_id, on, today)
            return RedirectResponse("/monthly-review", status_code=303)

        @app.get("/api/monthly-review")
        def monthly_review(session: SessionDep, today: TodayDep) -> MonthlyReviewOut:
            return _monthly_review_out(persistence.monthly_review(session, today))

        @app.post("/api/monthly-review/pull")
        def pull(session: SessionDep, today: TodayDep) -> MonthlyReviewOut:
            _pull_from_future_log(session, today)
            return _monthly_review_out(persistence.monthly_review(session, today))

    def render_future_log(
        request: Request,
        session: Session,
        today: date,
        *,
        typed: FutureEntryForm | None = None,
        refused: str | None = None,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "future_log.html",
            {
                "today": today,
                "first_month": journal.next_month(journal.month_of(today)),
                "future_log": persistence.future_log(session, today),
                "typed": typed,
                "refused": refused,
            },
            status_code=422 if refused else 200,
        )

    @app.get("/future", response_class=HTMLResponse)
    def future_log_page(request: Request, session: SessionDep, today: TodayDep) -> Response:
        return render_future_log(request, session, today)

    @app.post("/future/entries")
    def add_to_future_log(
        request: Request,
        form: Annotated[FutureEntryForm, Form()],
        session: SessionDep,
        today: TodayDep,
    ) -> Response:
        try:
            # An empty date field reads as no date.
            new_entry = journal.log_future_entry(
                form.text,
                month=_parse_month(form.month),
                on=_optional_date(form.on),
                today=today,
            )
        except REFUSED_AS_INVALID as refused:
            # Refused before anything is written.
            return render_future_log(request, session, today, typed=form, refused=str(refused))
        _add(session, new_entry)
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

    # Capture on the go: a minimal page for the phone that saves raw text to
    # the Inbox, unclassified.
    @app.get("/capture", response_class=HTMLResponse)
    def capture_page(
        request: Request, today: TodayDep, captured: bool = False
    ) -> Response:
        return templates.TemplateResponse(
            request, "capture.html", {"today": today, "captured": captured}
        )

    @app.post("/capture")
    def capture_from_page(text: Annotated[str, Form()], session: SessionDep) -> Response:
        persistence.add_capture(session, journal.capture(text))
        return RedirectResponse("/capture?captured=1", status_code=303)

    def render_inbox(
        request: Request,
        session: Session,
        today: date,
        capture_id: int | None = None,
        *,
        adjusted: TriageForm | None = None,
        refused: str | None = None,
    ) -> Response:
        """The Inbox, Triaging one Capture: the one asked for, or else the
        first captured."""
        captures = persistence.inbox(session)
        if capture_id is not None:
            triaging: journal.Capture | None = persistence.get_capture(session, capture_id)
        else:
            triaging = captures[0] if captures else None
        suggestion = journal.triage_suggestion(triaging) if triaging else None
        return templates.TemplateResponse(
            request,
            "inbox.html",
            {
                "today": today,
                "captures": captures,
                "triaging": triaging,
                "suggestion": suggestion,
                "typed": adjusted.text if adjusted else suggestion and journal.as_typed(suggestion),
                "adjusted": adjusted,
                "refused": refused,
                "this_month": journal.month_of(today),
                "first_future_month": journal.next_month(journal.month_of(today)),
            },
            status_code=422 if refused else 200,
        )

    @app.get("/inbox", response_class=HTMLResponse)
    def inbox_page(request: Request, session: SessionDep, today: TodayDep) -> Response:
        return render_inbox(request, session, today)

    @app.get("/inbox/{capture_id}", response_class=HTMLResponse)
    def triage_page(
        request: Request, capture_id: int, session: SessionDep, today: TodayDep
    ) -> Response:
        return render_inbox(request, session, today, capture_id)

    @app.post("/inbox/{capture_id}/triage")
    def triage_from_page(
        request: Request,
        capture_id: int,
        form: Annotated[TriageForm, Form()],
        session: SessionDep,
        today: TodayDep,
    ) -> Response:
        try:
            _triage(
                session,
                capture_id,
                to=form.to,
                on=_optional_date(form.on),
                month=_optional_month(form.month),
                text=form.text,
                today=today,
            )
        except REFUSED_AS_INVALID as refused:
            # Refused before anything is written, so the Capture stays put.
            return render_inbox(
                request, session, today, capture_id, adjusted=form, refused=str(refused)
            )
        return RedirectResponse("/inbox", status_code=303)

    @app.post("/inbox/{capture_id}/delete")
    def delete_capture_from_page(capture_id: int, session: SessionDep) -> Response:
        persistence.delete_capture(session, capture_id)
        return RedirectResponse("/inbox", status_code=303)

    @app.post("/api/captures", status_code=201)
    def create_capture(body: NewCaptureIn, session: SessionDep) -> CaptureOut:
        return _capture_out(persistence.add_capture(session, journal.capture(body.text)))

    @app.post("/api/captures/{capture_id}/triage", status_code=201)
    def triage_capture(
        capture_id: int, body: TriageIn, session: SessionDep, today: TodayDep
    ) -> EntryOut:
        return _out(
            _triage(
                session,
                capture_id,
                to=body.to,
                on=body.on,
                month=_optional_month(body.month),
                text=body.text,
                today=today,
            )
        )

    @app.delete("/api/captures/{capture_id}", status_code=204)
    def delete_capture(capture_id: int, session: SessionDep) -> Response:
        persistence.delete_capture(session, capture_id)
        return Response(status_code=204)

    @app.get("/api/inbox")
    def inbox(session: SessionDep) -> InboxOut:
        captures = persistence.inbox(session)
        return InboxOut(count=len(captures), captures=[_capture_out(c) for c in captures])

    return app
