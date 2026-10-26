"""`dots-and-dashes migrate`, the release command: it brings the schema up to
this release's head, and lets an older release (a rollback) start against a
database a later release already migrated."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from dots_and_dashes import cli

ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"
# A revision this release has never heard of, as a later release leaves it.
LATER_RELEASE = "0099_from_a_later_release"


def _head() -> str:
    head = ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_current_head()
    assert head is not None
    return head


def _revision(database_url: str) -> str:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
    engine.dispose()
    return revision


def _stamp(database_url: str, revision: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = :r"), {"r": revision})
    engine.dispose()


@pytest.fixture
def migrate(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.chdir(ALEMBIC_INI.parent)
    yield lambda: cli.main(["migrate"])
    # Leave the shared test database at head for the other tests.
    config = Config(ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", database_url)
    if _revision(database_url) == LATER_RELEASE:
        _stamp(database_url, _head())
    command.upgrade(config, "head")


def test_migrate_upgrades_the_database_to_this_releases_head(database_url, migrate):
    config = Config(ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "-1")

    migrate()

    assert _revision(database_url) == _head()


def test_a_rollback_starts_against_a_database_a_later_release_migrated(
    database_url, migrate, capsys
):
    _stamp(database_url, LATER_RELEASE)

    migrate()

    assert _revision(database_url) == LATER_RELEASE
    assert LATER_RELEASE in capsys.readouterr().out
