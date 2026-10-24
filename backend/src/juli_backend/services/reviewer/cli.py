"""Provision partner reviewer accounts (fast track P32-A, D42.5).

    python -m juli_backend.services.reviewer.cli create --email shopee-review@app-juli.com \\
        --platform shopee --by you@app-juli.com [--days 30]
    python -m juli_backend.services.reviewer.cli renew  --email … --by … [--days 30] \\
        [--rotate-password]
    python -m juli_backend.services.reviewer.cli revoke --email … --by …
    python -m juli_backend.services.reviewer.cli reset  --email … --platform shopee --by … \
        [--days 30]
    python -m juli_backend.services.reviewer.cli show   --email …

``reset`` (P67, D75 Q4) gives the address a brand-new account with a clean history: the
old Supabase user is banned and renamed to ``local+retired-<stamp>@domain`` (its ops row
too, revoked), then a NEW Supabase user and a NEW ops row are created -- new user id,
new ``created_at`` -- so the sandbox reviewer sees none of the old account's runs.
(``create`` on an existing address keeps the same user id and row, and so the history.)

Env: ``DATABASE_URL``, ``SUPABASE_URL``, ``SUPABASE_SERVICE_ROLE_KEY`` (not for
``show``). A generated password is printed ONCE to stdout (create, and renew
with ``--rotate-password``) and is never stored, logged or committed. Every
command writes an ops audit row. Operator-only: not reachable over HTTP.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.async_db import async_database_url
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.reviewer import accounts
from juli_backend.services.reviewer.gotrue import BAN_FOREVER, UNBAN, GoTrueAdmin

PASSWORD_BYTES = 18  # ~24 URL-safe characters


def generate_password() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewer-accounts", description="Partner reviewer trial accounts (D42)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Create (or take over) a reviewer account")
    create.add_argument("--email", required=True)
    create.add_argument("--platform", required=True, help="e.g. shopee")
    create.add_argument("--days", type=int, default=accounts.DEFAULT_LIFETIME_DAYS)
    create.add_argument("--by", required=True, help="Your staff e-mail (audited)")
    renew = sub.add_parser("renew", help="Extend expiry (and un-revoke)")
    renew.add_argument("--email", required=True)
    renew.add_argument("--days", type=int, default=accounts.DEFAULT_LIFETIME_DAYS)
    renew.add_argument("--rotate-password", action="store_true")
    renew.add_argument("--by", required=True)
    revoke = sub.add_parser("revoke", help="Revoke now (row kept, Supabase user banned)")
    revoke.add_argument("--email", required=True)
    revoke.add_argument("--by", required=True)
    reset = sub.add_parser(
        "reset", help="Retire the account and create a fresh one (new user id, clean history)"
    )
    reset.add_argument("--email", required=True)
    reset.add_argument("--platform", required=True, help="e.g. shopee")
    reset.add_argument("--days", type=int, default=accounts.DEFAULT_LIFETIME_DAYS)
    reset.add_argument("--by", required=True, help="Your staff e-mail (audited)")
    show = sub.add_parser("show", help="Print the account row")
    show.add_argument("--email", required=True)
    return parser


def _staff_email(value: str) -> str:
    email = value.strip().lower()
    if not email.endswith("@app-juli.com"):
        raise SystemExit("--by must be a staff e-mail (@app-juli.com)")
    return email


def _describe(account: accounts.ReviewerAccount) -> str:
    state = account.status()
    return (
        f"email={account.email} platform={account.platform} user_id={account.user_id} "
        f"expires_at={account.expires_at.isoformat()}Z status={state}"
    )


async def run(
    args: argparse.Namespace,
    session: AsyncSession,
    gotrue_factory: Callable[[], GoTrueAdmin],
    out: Callable[[str], None] = print,
) -> int:
    if args.command == "show":
        found = await accounts.find_by_email(session, args.email)
        out(_describe(found) if found else "not found")
        return 0 if found else 1
    by = _staff_email(args.by)
    if args.command == "create":
        platform = accounts.normalise_platform(args.platform)
        password = generate_password()
        user = gotrue_factory().create_or_update(args.email.strip().lower(), password, platform)
        account = await accounts.upsert_account(
            session, user_id=user.id, email=args.email, platform=platform, days=args.days, by=by
        )
        await session.commit()
        out(_describe(account))
        out(f"password (shown once, hand it to the reviewer; not stored): {password}")
        return 0
    if args.command == "renew":
        renewed = await accounts.renew_account(session, args.email, days=args.days, by=by)
        if renewed is None:
            out("not found")
            return 1
        new_password = generate_password() if args.rotate_password else None
        gotrue_factory().update(renewed.user_id, password=new_password, ban=UNBAN)
        await session.commit()
        out(_describe(renewed))
        if new_password:
            out(f"new password (shown once; not stored): {new_password}")
        return 0
    if args.command == "reset":
        return await _reset(args, session, gotrue_factory(), by=by, out=out)
    if args.command == "revoke":
        revoked = await accounts.revoke_account(session, args.email, by=by)
        if revoked is None:
            out("not found")
            return 1
        gotrue_factory().update(revoked.user_id, ban=BAN_FOREVER)
        await session.commit()
        out(_describe(revoked))
        return 0
    raise SystemExit(f"unknown command {args.command}")


async def _reset(
    args: argparse.Namespace,
    session: AsyncSession,
    gotrue: GoTrueAdmin,
    *,
    by: str,
    out: Callable[[str], None],
) -> int:
    """Retire the old account (Supabase user + ops row), then create a fresh one."""
    email = args.email.strip().lower()
    platform = accounts.normalise_platform(args.platform)
    if not 1 <= args.days <= accounts.MAX_LIFETIME_DAYS:
        raise SystemExit(f"--days must be between 1 and {accounts.MAX_LIFETIME_DAYS}")
    moment = utc_now_naive()
    old = gotrue.find_by_email(email)
    if old is not None:
        gotrue.update(old.id, email=accounts.retired_email(email, moment), ban=BAN_FOREVER)
    retired = await accounts.retire_account(session, email, by=by, now=moment)
    password = generate_password()
    user = gotrue.create(email, password, platform)
    if retired is not None and user.id == retired.user_id:
        raise SystemExit("reset: Supabase returned the old user id; nothing was committed")
    account = await accounts.upsert_account(
        session, user_id=user.id, email=email, platform=platform, days=args.days, by=by
    )
    await session.commit()
    if retired is not None:
        out(f"retired: user_id={retired.user_id} email={retired.email}")
    out(_describe(account))
    out(f"password (shown once, hand it to the reviewer; not stored): {password}")
    return 0


def _gotrue() -> GoTrueAdmin:
    return GoTrueAdmin(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))


async def _main(argv: Sequence[str] | None) -> int:
    args = build_parser().parse_args(argv)
    raw = os.getenv("DATABASE_URL", "")
    if not raw:
        raise SystemExit("DATABASE_URL is required")
    engine = create_async_engine(async_database_url(raw))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await run(args, session, _gotrue)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    sys.exit(main())
