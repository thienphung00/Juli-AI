"""CLI for production write authorization operator actions (issue #1335).

Operator entry point for issuing and revoking production write authorizations.
Not exposed via HTTP (/v1); operator-only access via CLI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.services.operations.production_write_authorizations_service import (
    ProductionWriteAuthorizationService,
)
from juli_backend.services.tiktok.credential_binding import (
    CredentialBindingError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="production-write-authorizations",
        description="Operator CLI for production write authorizations (issue #1335).",
    )

    subparsers = parser.add_subparsers(dest="command", help="Operation to perform")

    # Issue subcommand
    issue_parser = subparsers.add_parser("issue", help="Issue an authorization")
    issue_parser.add_argument("shop_id", help="Shop UUID")
    issue_parser.add_argument("product_id", help="TikTok product ID")
    issue_parser.add_argument(
        "mutation_kind", help="Mutation kind (e.g., listing.optimize_product)"
    )
    issue_parser.add_argument(
        "--capability",
        default="sandbox_write",
        help="TikTok capability (default: sandbox_write)",
    )
    issue_parser.add_argument(
        "--shop-cipher",
        required=True,
        help="Shop cipher from TikTok authorization response",
    )
    issue_parser.add_argument(
        "--authorized-by",
        required=True,
        help="Operator email or identifier",
    )
    issue_parser.add_argument(
        "--reason",
        help="Reason for authorization (optional)",
    )
    issue_parser.add_argument(
        "--ttl-hours",
        type=int,
        default=24,
        help="Time-to-live in hours (default: 24)",
    )
    issue_parser.add_argument(
        "--db-url",
        required=True,
        help="Database URL (e.g., postgresql://user@localhost/juli)",
    )

    # Revoke subcommand
    revoke_parser = subparsers.add_parser("revoke", help="Revoke an authorization")
    revoke_parser.add_argument("authorization_id", help="Authorization UUID to revoke")
    revoke_parser.add_argument(
        "--reason",
        help="Reason for revocation",
    )
    revoke_parser.add_argument(
        "--db-url",
        required=True,
        help="Database URL (e.g., postgresql://user@localhost/juli)",
    )

    return parser


async def issue_authorization(args) -> int:
    """Issue a production write authorization via the service."""
    try:
        shop_id = uuid.UUID(args.shop_id)
        product_id = args.product_id
        mutation_kind = args.mutation_kind
        capability = args.capability
        shop_cipher = args.shop_cipher
        authorized_by = args.authorized_by
        reason = args.reason
        ttl_hours = args.ttl_hours
        db_url = args.db_url

        # Create async engine and session
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            service = ProductionWriteAuthorizationService(session)

            try:
                auth = await service.issue(
                    shop_id=shop_id,
                    tiktok_product_id=product_id,
                    mutation_kind=mutation_kind,
                    capability=capability,
                    shop_cipher=shop_cipher,
                    authorized_by=authorized_by,
                    reason=reason,
                    ttl_hours=ttl_hours,
                )
                await session.commit()

                print("✓ Authorization issued")
                print(f"  ID: {auth.id}")
                print(f"  Shop: {auth.shop_id}")
                print(f"  Product: {auth.tiktok_product_id}")
                print(f"  Mutation: {auth.mutation_kind}")
                print(f"  Expires: {auth.expires_at}")
                return 0

            except CredentialBindingError as e:
                print(f"✗ Authorization refused: {e}", file=sys.stderr)
                return 1
            except ValueError as e:
                print(f"✗ Validation error: {e}", file=sys.stderr)
                return 1

        await engine.dispose()

    except ValueError as e:
        print(f"✗ Invalid input: {e}", file=sys.stderr)
        return 1


async def revoke_authorization(args) -> int:
    """Revoke a production write authorization via the service."""
    try:
        auth_id = uuid.UUID(args.authorization_id)
        reason = args.reason
        db_url = args.db_url

        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            service = ProductionWriteAuthorizationService(session)

            try:
                auth = await service.revoke(auth_id, reason=reason)
                await session.commit()

                print("✓ Authorization revoked")
                print(f"  ID: {auth.id}")
                print(f"  Revoked at: {auth.revoked_at}")
                if auth.revoke_reason:
                    print(f"  Reason: {auth.revoke_reason}")
                return 0

            except Exception as e:
                print(f"✗ Revocation failed: {e}", file=sys.stderr)
                return 1

        await engine.dispose()

    except ValueError as e:
        print(f"✗ Invalid input: {e}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.command:
        print("error: command required", file=sys.stderr)
        return 1

    if args.command == "issue":
        return asyncio.run(issue_authorization(args))
    elif args.command == "revoke":
        return asyncio.run(revoke_authorization(args))
    else:
        print(f"error: unknown command {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
