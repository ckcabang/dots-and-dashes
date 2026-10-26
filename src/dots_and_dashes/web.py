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


class MoveIn(BaseModel):
    to: int


class TimeIn(BaseModel):
    time: time


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


def _rearrange(
    session: Session,
    entry_id: int,
    change: Callable[[list[journal.Entry]], list[journal.Entry]],
) -> DailyLogOut:
    """Apply an ordering change to the Daily Log holding an Entry, and store it."""
    day = persistence.find_day(session, entry_id)
    if day is None:
        raise HTTPException(404, "no such Entry")
    entries = change(persistence.entries_on(session, day))
    persistence.save_daily_log(session, entries)
    return DailyLogOut(
        date=day,
        entries=[EntryOut.model_validate(entry, from_attributes=True) for entry in entries],
    )


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

    @app.exception_handler(journal.TimedEntryMoveError)
    @app.exception_handler(journal.UntimedEntryError)
    def refuse_reordering(request: Request, exc: ValueError) -> Response:
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
        persistence.add_entry(session, journal.log_entry(text, on=today))
        if "HX-Request" in request.headers:
            # The whole Daily Log, since a Timed Entry may land anywhere in it.
            entries = persistence.entries_on(session, today)
            return templates.TemplateResponse(
                request, "_entries.html", {"entries": entries}, status_code=201
            )
        return RedirectResponse("/", status_code=303)

    @app.post("/entries/{entry_id}/move")
    def move_entry_on_page(
        request: Request,
        entry_id: int,
        to: Annotated[int, Form()],
        session: SessionDep,
    ) -> Response:
        daily_log = _rearrange(
            session, entry_id, lambda entries: journal.move_entry(entries, entry_id, to=to)
        )
        if "HX-Request" in request.headers:
            return templates.TemplateResponse(
                request, "_entries.html", {"entries": daily_log.entries}
            )
        return RedirectResponse("/", status_code=303)

    @app.post("/api/entries", status_code=201)
    def create_entry(body: NewEntryIn, session: SessionDep, today: TodayDep) -> EntryOut:
        entry = persistence.add_entry(session, journal.log_entry(body.text, on=today))
        return EntryOut.model_validate(entry, from_attributes=True)

    @app.post("/api/entries/{entry_id}/move")
    def move_entry(entry_id: int, body: MoveIn, session: SessionDep) -> DailyLogOut:
        return _rearrange(
            session,
            entry_id,
            lambda entries: journal.move_entry(entries, entry_id, to=body.to),
        )

    @app.post("/api/entries/{entry_id}/time")
    def change_time(entry_id: int, body: TimeIn, session: SessionDep) -> DailyLogOut:
        return _rearrange(
            session,
            entry_id,
            lambda entries: journal.change_time(entries, entry_id, to=body.time),
        )

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
