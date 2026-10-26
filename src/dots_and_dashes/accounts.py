"""Users and their passwords. Users are created from the command line (cli.py), never by sign-up."""

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

# Checked against when no User has the email given, so a wrong email takes as
# long to refuse as a wrong password.
_NO_USER_HASH = _hasher.hash("no such user")


@dataclass(frozen=True)
class User:
    id: int
    email: str
    # "Today" runs midnight to midnight here.
    timezone: ZoneInfo
    canary: bool


def normalise_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("a password can't be empty")
    return _hasher.hash(password)


def password_matches(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _NO_USER_HASH, password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False
