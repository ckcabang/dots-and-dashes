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
    # Send the session cookie over HTTPS only: on wherever TLS serves the app.
    secure_cookies: bool = False
    # Feature flags: off unless set, and changed without a code deploy.
    monthly_review: bool = False
    # Telemetry: exported over OTLP (to Grafana Cloud) only when an endpoint
    # is set, so the app runs the same without it. The headers carry the
    # credentials, as `Authorization=Basic <base64 of instance-id:token>`.
    otlp_endpoint: str = ""
    otlp_headers: str = ""
    service_name: str = "dots-and-dashes"
    environment: str = "local"  # dev or prod, to tell their telemetry apart
    release: str = "local"  # the deployed image, to tie errors to a release
    # The chaos switch, for staging an incident on dev (docs/runbooks):
    # the share of Entry saves to fail, 0 to 1, and how long to slow each one.
    chaos_save_error_rate: float = 0.0
    chaos_save_latency_ms: int = 0
    # The most database connections the app holds; unset, SQLAlchemy's default.
    db_pool_size: int | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        session_secret = os.environ.get("SESSION_SECRET")
        return cls(
            database_url=os.environ["DATABASE_URL"],
            secure_cookies=_flag("SECURE_COOKIES"),
            monthly_review=_flag("FLAG_MONTHLY_REVIEW"),
            otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            otlp_headers=os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", ""),
            service_name=os.environ.get("OTEL_SERVICE_NAME", "dots-and-dashes"),
            environment=os.environ.get("DEPLOYMENT_ENVIRONMENT", "local"),
            # Fly sets FLY_IMAGE_REF on every Machine to the image it runs.
            release=os.environ.get("FLY_IMAGE_REF", "local"),
            chaos_save_error_rate=_rate("CHAOS_SAVE_ERROR_RATE"),
            chaos_save_latency_ms=_milliseconds("CHAOS_SAVE_LATENCY_MS"),
            db_pool_size=_pool_size("DB_POOL_SIZE"),
            **({"session_secret": session_secret} if session_secret else {}),
        )


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _rate(name: str) -> float:
    rate = float(os.environ.get(name) or 0)
    if not 0 <= rate <= 1:
        raise ValueError(f"{name} must be between 0 and 1, not {rate}")
    return rate


def _milliseconds(name: str) -> int:
    milliseconds = int(os.environ.get(name) or 0)
    if milliseconds < 0:
        raise ValueError(f"{name} must not be negative, not {milliseconds}")
    return milliseconds


def _pool_size(name: str) -> int | None:
    if not (value := os.environ.get(name)):
        return None
    if (size := int(value)) < 1:
        raise ValueError(f"{name} must be at least 1, not {size}")
    return size
