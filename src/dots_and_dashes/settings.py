"""Operations config, read from environment variables."""

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    database_url: str
    # Until Users exist (#6), the journal has one timezone for "today".
    timezone: ZoneInfo

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            timezone=ZoneInfo(os.environ.get("JOURNAL_TIMEZONE", "UTC")),
        )
