"""Operations config, read from environment variables."""

import os
import secrets
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str
    # Signs session cookies. Without SESSION_SECRET each process makes its own,
    # so a restart logs everyone out: set it wherever the app is deployed.
    session_secret: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    # Feature flags: off unless set, and changed without a code deploy.
    monthly_review: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        session_secret = os.environ.get("SESSION_SECRET")
        return cls(
            database_url=os.environ["DATABASE_URL"],
            monthly_review=_flag("FLAG_MONTHLY_REVIEW"),
            **({"session_secret": session_secret} if session_secret else {}),
        )


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
