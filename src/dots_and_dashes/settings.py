"""Operations config, read from environment variables."""

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    database_url: str
    # Until Users exist (#6), the journal has one timezone for "today".
    timezone: ZoneInfo
    # Feature flags: off unless set, and changed without a code deploy.
    monthly_review: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            timezone=ZoneInfo(os.environ.get("JOURNAL_TIMEZONE", "UTC")),
            monthly_review=_flag("FLAG_MONTHLY_REVIEW"),
        )


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
