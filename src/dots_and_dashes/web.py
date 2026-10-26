"""The Web module: thin FastAPI routes that parse, call the domain, persist and render."""

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
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
templates.env.filters["as_typed"] = journal.as_typed


def _system_clock() -> datetime:
    return datetime.now(UTC)


class NewEntryIn(BaseModel):
    text: str


class EditedEntryIn(BaseModel):
    text: str


class EntryOut(BaseModel):
    id: int
    type: journal.EntryType
    state: journal.TaskState | None
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

# The Task State changes the keyboard and the API can ask for, by URL name.
TASK_STATE_CHANGES: dict[str, Callable[[journal.Entry], journal.Entry]] = {
    "complete": journal.complete,
    "cancel": journal.cancel,
    "reopen": journal.reopen,
}


def _change_task_state(session: Session, entry_id: int, change: str) -> journal.Entry:
    act = TASK_STATE_CHANGES.get(change)
    if act is None:
        raise persistence.EntryNotFoundError(f"no Task State change {change!r}")
    return persistence.save_entry(session, act(persistence.get_entry(session, entry_id)))


def _edit(session: Session, entry_id: int, text: str) -> journal.Entry:
    entry = persistence.get_entry(session, entry_id)
    return persistence.save_entry(session, journal.edit_entry(entry, text))


def _entry_fragment(request: Request, entry: journal.Entry) -> Response:
    return templates.TemplateResponse(request, "_entry.html", {"entry": entry})


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

    @app.exception_handler(journal.TaskStateError)
    def refuse_task_state_change(request: Request, exc: journal.TaskStateError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(persistence.EntryNotFoundError)
    def entry_not_found(request: Request, exc: persistence.EntryNotFoundError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=404)

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

    @app.post("/entries/{entry_id}/{change}")
    def change_task_state_on_page(
        request: Request, entry_id: int, change: str, session: SessionDep
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
        persistence.delete_entry(session, entry_id)
        # HTMX swaps the Entry's line for this empty body.
        return Response(status_code=200)

    @app.post("/api/entries", status_code=201)
    def create_entry(body: NewEntryIn, session: SessionDep, today: TodayDep) -> EntryOut:
        entry = persistence.add_entry(session, journal.log_entry(body.text, on=today))
        return EntryOut.model_validate(entry, from_attributes=True)

    @app.post("/api/entries/{entry_id}/{change}")
    def change_task_state(entry_id: int, change: str, session: SessionDep) -> EntryOut:
        entry = _change_task_state(session, entry_id, change)
        return EntryOut.model_validate(entry, from_attributes=True)

    @app.patch("/api/entries/{entry_id}")
    def edit_entry(entry_id: int, body: EditedEntryIn, session: SessionDep) -> EntryOut:
        entry = _edit(session, entry_id, body.text)
        return EntryOut.model_validate(entry, from_attributes=True)

    @app.delete("/api/entries/{entry_id}", status_code=204)
    def delete_entry(entry_id: int, session: SessionDep) -> Response:
        persistence.delete_entry(session, entry_id)
        return Response(status_code=204)

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
