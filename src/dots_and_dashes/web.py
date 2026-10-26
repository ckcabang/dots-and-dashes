"""The Web module: thin FastAPI routes that parse, call the domain, persist and render."""

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
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


class EntryOut(BaseModel):
    id: int
    type: journal.EntryType
    state: journal.TaskState | None
    priority: bool
    inspiration: bool
    time: time | None
    text: str
    day: date
    parent_id: int | None


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


def _nest(session: Session, entry_id: int) -> journal.Entry:
    entry = _existing_entry(session, entry_id)
    daily_log = persistence.entries_on(session, entry.day)
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

    @app.exception_handler(journal.NestingError)
    def refuse_nesting(request: Request, exc: journal.NestingError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/", response_class=HTMLResponse)
    def todays_daily_log_page(
        request: Request, session: SessionDep, today: TodayDep
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "daily_log.html",
            {"day": today, "entries": persistence.entries_on(session, today)},
        )

    @app.post("/entries")
    def quick_entry(
        request: Request,
        text: Annotated[str, Form()],
        session: SessionDep,
        today: TodayDep,
    ) -> Response:
        entry = persistence.add_entry(session, journal.log_entry(text, on=today))
        if "HX-Request" in request.headers:
            return templates.TemplateResponse(
                request, "_entry.html", {"entry": entry}, status_code=201
            )
        return RedirectResponse("/", status_code=303)

    @app.post("/entries/{entry_id}/nest", response_class=HTMLResponse)
    def nest_from_page(request: Request, entry_id: int, session: SessionDep) -> Response:
        entry = _nest(session, entry_id)
        return _entries_fragment(request, session, entry.day)

    @app.post("/entries/{entry_id}/un-nest", response_class=HTMLResponse)
    def un_nest_from_page(request: Request, entry_id: int, session: SessionDep) -> Response:
        entry = _un_nest(session, entry_id)
        return _entries_fragment(request, session, entry.day)

    def _entries_fragment(request: Request, session: Session, day: date) -> Response:
        return templates.TemplateResponse(
            request, "_entries.html", {"entries": persistence.entries_on(session, day)}
        )

    @app.post("/api/entries", status_code=201)
    def create_entry(body: NewEntryIn, session: SessionDep, today: TodayDep) -> EntryOut:
        entry = persistence.add_entry(session, journal.log_entry(body.text, on=today))
        return EntryOut.model_validate(entry, from_attributes=True)

    @app.post("/api/entries/{entry_id}/nest")
    def nest_entry(entry_id: int, session: SessionDep) -> EntryOut:
        return EntryOut.model_validate(_nest(session, entry_id), from_attributes=True)

    @app.post("/api/entries/{entry_id}/un-nest")
    def un_nest_entry(entry_id: int, session: SessionDep) -> EntryOut:
        return EntryOut.model_validate(_un_nest(session, entry_id), from_attributes=True)

    @app.get("/api/daily-logs/today")
    def todays_daily_log(session: SessionDep, today: TodayDep) -> DailyLogOut:
        return DailyLogOut(
            date=today,
            entries=[
                EntryOut.model_validate(entry, from_attributes=True)
                for entry in persistence.entries_on(session, today)
            ],
        )

    return app
