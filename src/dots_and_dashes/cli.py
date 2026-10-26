"""The command line: `dots-and-dashes create-user` is the only way a User is made."""

import argparse
import getpass
import os
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dots_and_dashes import accounts, persistence
from dots_and_dashes.settings import Settings


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise argparse.ArgumentTypeError(f"{name!r} is not an IANA timezone") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dots-and-dashes")
    commands = parser.add_subparsers(dest="command", required=True)
    create_user = commands.add_parser(
        "create-user", help="create the User, or with --canary the Canary User"
    )
    create_user.add_argument("--email", required=True)
    create_user.add_argument(
        "--timezone", required=True, type=_timezone, help="an IANA name, e.g. Europe/London"
    )
    create_user.add_argument(
        "--canary", action="store_true", help="a synthetic User for monitoring only"
    )
    create_user.add_argument(
        "--password-env",
        default="USER_PASSWORD",
        metavar="VAR",
        help="the environment variable holding the password, such as a secret "
        "(default USER_PASSWORD); prompted for when unset",
    )
    return parser


def _password(variable: str) -> str:
    if password := os.environ.get(variable):
        return password
    password = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != password:
        sys.exit("The passwords don't match.")
    return password


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        password_hash = accounts.hash_password(_password(args.password_env))
    except ValueError as exc:
        sys.exit(str(exc))
    engine = create_engine(Settings.from_env().database_url)
    try:
        with Session(engine) as session, session.begin():
            user = persistence.create_user(
                session, args.email, password_hash, args.timezone, canary=args.canary
            )
    except persistence.DuplicateUserError as exc:
        sys.exit(str(exc))
    finally:
        engine.dispose()
    kind = "Canary User" if user.canary else "User"
    print(f"Created {kind} {user.email} ({user.timezone.key}).")


if __name__ == "__main__":
    main()
