"""The Web module: thin FastAPI routes that parse, call the domain, persist and render."""

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
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
    day: date


class DailyLogOut(BaseModel):
    date: date
    entries: list[EntryOut]


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker.begin() as session:
        yield session


def _today(request: Request) -> date:
    state = request.app.state
    return journal.today(state.clock(), state.settings.timezone)


SessionDep = Annotated[Session, Depends(_session)]
TodayDep = Annotated[date, Depends(_today)]


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

    @app.post("/api/entries", status_code=201)
    def create_entry(body: NewEntryIn, session: SessionDep, today: TodayDep) -> EntryOut:
        entry = persistence.add_entry(
            session, journal.log_entry(body.text, on=body.day or today)
        )
        return EntryOut.model_validate(entry, from_attributes=True)

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

    return app
