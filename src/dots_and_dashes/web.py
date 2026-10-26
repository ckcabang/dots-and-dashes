"""The Web module: thin FastAPI routes that parse, call the domain, persist and render."""

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Path as PathParam, Request
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


def _system_clock() -> datetime:
    return datetime.now(UTC)


class NewEntryIn(BaseModel):
    text: str
    day: date | None = None  # the Daily Log to log it on; today when omitted


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


SessionDep = Annotated[Session, Depends(_session)]
TodayDep = Annotated[date, Depends(_today)]
MonthDep = Annotated[date, Depends(_month_param)]


def _nest(session: Session, entry_id: int) -> journal.Entry:
    entry = _existing_entry(session, entry_id)
    daily_log = persistence.entries_on(session, journal.daily_log_day(entry))
    return persistence.set_parent(session, journal.nest_note(entry, daily_log))


def _un_nest(session: Session, entry_id: int) -> journal.Entry:
    entry = _existing_entry(session, entry_id)
    return persistence.set_parent(session, journal.un_nest_note(entry))


def _existing_entry(session: Session, entry_id: int) -> journal.Entry:
    entry = persistence.get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="no such Entry")
    return entry


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

    @app.exception_handler(journal.BlankEntryError)
    def refuse_blank_entry(request: Request, exc: journal.BlankEntryError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(journal.PlacementError)
    def refuse_misplaced_entry(request: Request, exc: journal.PlacementError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def require_monthly_log(month: date, today: date) -> None:
        if not journal.has_monthly_log(month, today=today):
            raise HTTPException(404, "months after the current one have no Monthly Log")

    @app.exception_handler(journal.NestingError)
    def refuse_nesting(request: Request, exc: journal.NestingError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def render_daily_log(request: Request, session: Session, day: date) -> Response:
        return templates.TemplateResponse(
            request,
            "daily_log.html",
            {
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
    def go_to_date(date: date) -> Response:
        return RedirectResponse(f"/days/{date.isoformat()}", status_code=303)

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
        entry = persistence.add_entry(session, journal.log_entry(text, on=on))
        if "HX-Request" in request.headers:
            return templates.TemplateResponse(
                request, "_entry.html", {"entry": entry}, status_code=201
            )
        return RedirectResponse(f"/days/{on.isoformat()}", status_code=303)

    @app.post("/entries/{entry_id}/nest", response_class=HTMLResponse)
    def nest_from_page(request: Request, entry_id: int, session: SessionDep) -> Response:
        entry = _nest(session, entry_id)
        return _entries_fragment(request, session, journal.daily_log_day(entry))

    @app.post("/entries/{entry_id}/un-nest", response_class=HTMLResponse)
    def un_nest_from_page(request: Request, entry_id: int, session: SessionDep) -> Response:
        entry = _un_nest(session, entry_id)
        return _entries_fragment(request, session, journal.daily_log_day(entry))

    def _entries_fragment(request: Request, session: Session, day: date) -> Response:
        return templates.TemplateResponse(
            request, "_entries.html", {"entries": persistence.entries_on(session, day)}
        )

    @app.post("/api/entries", status_code=201)
    def create_entry(body: NewEntryIn, session: SessionDep, today: TodayDep) -> EntryOut:
        entry = persistence.add_entry(
            session, journal.log_entry(body.text, on=body.day or today)
        )
        return EntryOut.model_validate(entry, from_attributes=True)

    @app.post("/api/entries/{entry_id}/nest")
    def nest_entry(entry_id: int, session: SessionDep) -> EntryOut:
        return EntryOut.model_validate(_nest(session, entry_id), from_attributes=True)

    @app.post("/api/entries/{entry_id}/un-nest")
    def un_nest_entry(entry_id: int, session: SessionDep) -> EntryOut:
        return EntryOut.model_validate(_un_nest(session, entry_id), from_attributes=True)

    def daily_log_out(session: Session, day: date) -> DailyLogOut:
        return DailyLogOut(
            date=day,
            entries=[
                EntryOut.model_validate(entry, from_attributes=True)
                for entry in persistence.entries_on(session, day)
            ],
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
                "month": month,
                "previous_month": (month - timedelta(days=1)).replace(day=1),
                "next_month": next_month
                if journal.has_monthly_log(next_month, today=today)
                else None,
                "calendar": calendar,
                "tasks": tasks,
            },
        )

    @app.post("/months/{month}/entries")
    def add_to_monthly_log(
        month: MonthDep,
        text: Annotated[str, Form()],
        session: SessionDep,
        today: TodayDep,
    ) -> Response:
        persistence.add_entry(
            session, journal.log_month_entry(text, month=month, today=today)
        )
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
            persistence.add_entry(
                session, journal.log_month_entry(body.text, month=month, today=today)
            )
        )

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
        persistence.add_entry(
            session,
            journal.log_future_entry(
                text,
                month=_parse_month(month),
                on=on,
                today=today,
            ),
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
            persistence.add_entry(
                session,
                journal.log_future_entry(
                    body.text, month=_parse_month(body.month), on=body.on, today=today
                ),
            )
        )

    return app
