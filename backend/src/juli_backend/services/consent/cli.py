"""Operator commands for per-shop data-use consent (ADR-116 §2, owner decision D10).

    python -m juli_backend.services.consent.cli backfill-terms [--apply]
    python -m juli_backend.services.consent.cli grant --shop-id <uuid> --scope service \\
        [--scope llm_processing ...] --method contract_paper --terms-version <v> \\
        --evidence-ref <where> [--evidence-sha256 <hex>] --granted-by <who> \\
        [--granted-at <iso>] [--apply]
    python -m juli_backend.services.consent.cli revoke --shop-id <uuid> --scope <s> \\
        [--revoked-at <iso>] [--apply]

Operator-run only: never scheduled, not reachable over HTTP. Without ``--apply`` every
command is a dry run that writes nothing and prints what it would do.

``backfill-terms`` grants the Terms scopes (``service``, ``llm_processing``,
``llm_images``, ``llm_media``; never ``pooled_training``) to every shop whose owner has
accepted the Terms, through the same ``grant_terms_consents`` the acceptance route
uses. Shops are enumerated with the existing ``ops_list_shops()`` (SECURITY DEFINER,
EXECUTE to ``juli_ops`` only, ADR-089 decision 3) under ``ops_role``; each owner's
acceptance is read under that owner's user scope and each shop is written under its
own shop scope. One transaction per owner. Idempotent: a re-run grants nothing new.
Prints counts only -- no user id, e-mail or shop name.

``grant`` / ``revoke`` act on one shop (a contract client such as Fujiwa); ``--scope``
may be repeated. A scope already open is skipped by ``grant``; a scope with no open
grant is skipped by ``revoke``. A malformed request (blank field, bad hash) writes
nothing for any scope.

Env: ``DATABASE_URL`` (a role that is a member of ``juli_ops``, as the app runtime is).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.consent import METHODS, SCOPES
from juli_backend.repositories.consent import DataUseConsentsRepo
from juli_backend.repositories.identity import UsersRepo
from juli_backend.services.consent.grants import InvalidConsent, grant_consent, revoke_consent
from juli_backend.services.consent.terms import (
    TermsGrantResult,
    grant_terms_consents,
    terms_version_of,
)

logger = logging.getLogger(__name__)

#: ``() -> AsyncSession`` used as ``async with factory() as session``.
SessionFactory = Callable[[], Any]


# -- backfill-terms -----------------------------------------------------------------------


@dataclass(frozen=True)
class BackfillResult:
    owners: int
    owners_accepted: int
    shops: int
    grants: TermsGrantResult
    failed_owners: int = 0


async def _owned_shops(factory: SessionFactory) -> dict[uuid.UUID, list[uuid.UUID]]:
    from juli_backend.services.ops.overview import list_shops

    async with factory() as session:
        listings = await list_shops(session)
        await session.commit()
    owned: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for listing in listings:
        owned[listing.owner_user_id].append(listing.shop_id)
    return owned


async def run_backfill(factory: SessionFactory, *, apply: bool) -> BackfillResult:
    owned = await _owned_shops(factory)
    accepted = failed_owners = shops = 0
    grants = TermsGrantResult()
    for user_id, shop_ids in owned.items():
        async with factory() as session:
            try:
                user = await UsersRepo(session).get_own(user_id)
            except Exception as exc:
                await session.rollback()
                failed_owners += 1
                logger.warning(
                    "consent_backfill_owner_failed", extra={"error_type": type(exc).__name__}
                )
                continue
            if user.terms_accepted_at is None or user.terms_date_accepted is None:
                await session.rollback()
                continue
            accepted += 1
            shops += len(shop_ids)
            grants += await grant_terms_consents(
                session,
                user_id,
                shop_ids,
                accepted_at=user.terms_accepted_at,
                terms_version=terms_version_of(user.terms_date_accepted),
                write=apply,
            )
            if apply:
                await session.commit()
            else:
                await session.rollback()
    return BackfillResult(len(owned), accepted, shops, grants, failed_owners)


def format_backfill(result: BackfillResult, *, apply: bool) -> str:
    mode = "APPLY" if apply else "DRY RUN (add --apply to write)"
    verb = "granted" if apply else "to_grant"
    return (
        f"consent backfill-terms {mode}: owners={result.owners} "
        f"owners_accepted={result.owners_accepted} shops={result.shops} "
        f"{verb}={result.grants.granted} already_open={result.grants.already_open} "
        f"failed_shops={result.grants.failed_shops} failed_owners={result.failed_owners}"
    )


# -- grant / revoke -----------------------------------------------------------------------


@dataclass(frozen=True)
class GrantRequest:
    method: str
    terms_version: str
    evidence_ref: str
    granted_by: str
    evidence_sha256: str | None = None
    granted_at: datetime | None = None


async def run_grant(
    factory: SessionFactory,
    shop_id: uuid.UUID,
    scopes: Sequence[str],
    request: GrantRequest,
    *,
    apply: bool,
) -> dict[str, str]:
    """``scope -> outcome`` (``granted`` / ``would_grant`` / ``already_open``).

    Raises :class:`InvalidConsent` (nothing written) on a malformed request.
    """
    outcomes: dict[str, str] = {}
    async with factory() as session:
        try:
            async with with_shop_scope(session, shop_id):
                repo = DataUseConsentsRepo(session)
                for scope in dict.fromkeys(scopes):
                    if await repo.find_open(shop_id, scope) is not None:
                        outcomes[scope] = "already_open"
                        continue
                    # Validates on a dry run too; the rollback below discards the row.
                    await grant_consent(
                        session,
                        shop_id,
                        scope=scope,
                        method=request.method,
                        terms_version=request.terms_version,
                        evidence_ref=request.evidence_ref,
                        granted_by=request.granted_by,
                        evidence_sha256=request.evidence_sha256,
                        granted_at=request.granted_at,
                    )
                    outcomes[scope] = "granted" if apply else "would_grant"
        except BaseException:
            await session.rollback()
            raise
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return outcomes


async def run_revoke(
    factory: SessionFactory,
    shop_id: uuid.UUID,
    scopes: Sequence[str],
    *,
    revoked_at: datetime | None,
    apply: bool,
) -> dict[str, str]:
    """``scope -> outcome`` (``revoked`` / ``would_revoke`` / ``no_open_grant``)."""
    outcomes: dict[str, str] = {}
    async with factory() as session:
        try:
            async with with_shop_scope(session, shop_id):
                repo = DataUseConsentsRepo(session)
                for scope in dict.fromkeys(scopes):
                    if await repo.find_open(shop_id, scope) is None:
                        outcomes[scope] = "no_open_grant"
                        continue
                    if apply:
                        await revoke_consent(session, shop_id, scope, revoked_at=revoked_at)
                    outcomes[scope] = "revoked" if apply else "would_revoke"
        except BaseException:
            await session.rollback()
            raise
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return outcomes


def format_outcomes(
    command: str, shop_id: uuid.UUID, outcomes: dict[str, str], *, apply: bool
) -> str:
    mode = "APPLY" if apply else "DRY RUN (add --apply to write)"
    lines = [f"consent {command} {mode}: shop={shop_id}"]
    lines += [f"  {scope}: {outcome}" for scope, outcome in outcomes.items()]
    return "\n".join(lines)


# -- entry point --------------------------------------------------------------------------


def _iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO date-time: {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="consent", description="Per-shop data-use consent (ADR-116 §2, D10)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser(
        "backfill-terms", help="Grant the Terms scopes to shops of sellers who accepted"
    )
    backfill.add_argument("--apply", action="store_true", help="Write (default: dry run)")

    grant = sub.add_parser("grant", help="Record a grant for one shop")
    grant.add_argument("--shop-id", required=True, type=uuid.UUID)
    grant.add_argument("--scope", required=True, action="append", choices=SCOPES)
    grant.add_argument("--method", required=True, choices=METHODS)
    grant.add_argument("--terms-version", required=True)
    grant.add_argument("--evidence-ref", required=True)
    grant.add_argument("--evidence-sha256")
    grant.add_argument("--granted-by", required=True)
    grant.add_argument("--granted-at", type=_iso, help="ISO date-time (UTC if naive)")
    grant.add_argument("--apply", action="store_true", help="Write (default: dry run)")

    revoke = sub.add_parser("revoke", help="Close the open grant for one shop")
    revoke.add_argument("--shop-id", required=True, type=uuid.UUID)
    revoke.add_argument("--scope", required=True, action="append", choices=SCOPES)
    revoke.add_argument("--revoked-at", type=_iso, help="ISO date-time (UTC if naive)")
    revoke.add_argument("--apply", action="store_true", help="Write (default: dry run)")
    return parser


async def run_command(args: argparse.Namespace, factory: SessionFactory) -> tuple[int, str]:
    """Run one parsed command; ``(exit code, output)``."""
    if args.command == "backfill-terms":
        result = await run_backfill(factory, apply=args.apply)
        failed = result.grants.failed_shops or result.failed_owners
        return (1 if failed else 0), format_backfill(result, apply=args.apply)
    try:
        if args.command == "grant":
            request = GrantRequest(
                method=args.method,
                terms_version=args.terms_version,
                evidence_ref=args.evidence_ref,
                granted_by=args.granted_by,
                evidence_sha256=args.evidence_sha256,
                granted_at=args.granted_at,
            )
            outcomes = await run_grant(factory, args.shop_id, args.scope, request, apply=args.apply)
        else:
            outcomes = await run_revoke(
                factory, args.shop_id, args.scope, revoked_at=args.revoked_at, apply=args.apply
            )
    except InvalidConsent as exc:
        return 2, f"consent {args.command} refused, nothing written: {exc}"
    return 0, format_outcomes(args.command, args.shop_id, outcomes, apply=args.apply)


async def _main(argv: Sequence[str] | None) -> int:
    import os

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.async_db import async_database_url

    args = build_parser().parse_args(argv)
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    engine = create_async_engine(async_database_url(database_url))
    try:
        factory: Callable[[], AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
        code, output = await run_command(args, factory)
    finally:
        await engine.dispose()
    print(output)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    sys.exit(main())
