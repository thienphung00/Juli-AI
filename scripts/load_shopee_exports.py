"""Load a folder of Shopee Seller Centre exports through the ingest gateway (ADR-117 step 2).

    # Parse and validate against the gateway's own models; nothing is sent.
    python scripts/load_shopee_exports.py FOLDER --dry-run

    # A running backend: POST /v1/ingest/shopee/{dataset} with an ingest token.
    JULI_INGEST_TOKEN=jci_... python scripts/load_shopee_exports.py FOLDER --api-url URL

    # A LOCAL Postgres (Docker): the same gateway code in-process, as the shop.
    python scripts/load_shopee_exports.py FOLDER --database-url postgresql://...@127.0.0.1/... \\
        --shop-id UUID

``--database-url`` refuses any host but localhost / 127.0.0.1 / ::1 unless
``--allow-remote-database`` is given: until a client approves the sub-processor list, its
non-public rows exist only in a local database (ADR-117 §6, C13 / D8). The same rule
applies to ``--bootstrap-local-shop``, which creates a local shop + ``service`` consent row
for development only.

The summary prints counts per dataset, never values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from scripts.shopee_exports.parse import Parsed, Post, parse_folder

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate(parsed: Parsed, now: datetime) -> list[str]:
    """Each post checked by the gateway's own validator (no database)."""
    from juli_backend.services.ingest.gateway import IngestRejected, validate_rows
    from juli_backend.services.ingest.mapping import dataset_spec
    from juli_backend.services.ingest.schemas import IngestBody

    problems: list[str] = []
    for post in parsed.posts:
        spec = dataset_spec("shopee", post.dataset)
        if spec is None:
            problems.append(f"{post.file}: unknown dataset {post.dataset}")
            continue
        try:
            validate_rows(spec, IngestBody.model_validate(post.body), now)
        except ValidationError as exc:
            problems.append(f"{post.file} {post.dataset}: {exc.errors()[:3]}")
        except IngestRejected as exc:
            problems.append(f"{post.file} {post.dataset}: {exc.code} {exc.errors[:3]}")
    return problems


def summary(parsed: Parsed) -> str:
    posts = Counter(post.dataset for post in parsed.posts)
    rows: Counter[str] = Counter()
    for post in parsed.posts:
        rows[post.dataset] += len(post.body["rows"])
    lines = [f"{'dataset':<26}{'posts':>7}{'rows':>9}"]
    lines += [f"{name:<26}{posts[name]:>7}{rows[name]:>9}" for name in sorted(posts)]
    if parsed.skipped_files:
        lines.append(f"files not loaded ({len(parsed.skipped_files)}):")
        lines += [f"  {name}" for name in parsed.skipped_files]
    for note, count in sorted(parsed.notes.items()):
        lines.append(f"note: {note} x{count}")
    return "\n".join(lines)


def _require_local(url: str, allow_remote: bool) -> None:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS and not allow_remote:
        raise SystemExit(
            f"refusing database host {host!r}: client data stays local until the client "
            "approves the sub-processor list (ADR-117 §6). Pass --allow-remote-database "
            "only for Juli's own or public data."
        )


def send_http(posts: list[Post], api_url: str, token: str) -> Counter[str]:
    outcome: Counter[str] = Counter()
    for post in posts:
        request = urllib.request.Request(
            f"{api_url.rstrip('/')}/v1/ingest/shopee/{post.dataset}",
            data=json.dumps(post.body, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.loads(response.read())
            outcome["duplicate" if result.get("duplicate") else "stored"] += 1
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise SystemExit(f"{post.file} {post.dataset}: HTTP {exc.code} {detail}") from None
    return outcome


async def send_direct(posts: list[Post], database_url: str, shop_id: uuid.UUID) -> Counter[str]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.repositories import utc_now_naive
    from juli_backend.services import ingest as svc

    engine = create_async_engine(async_database_url(database_url))
    outcome: Counter[str] = Counter()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        for post in posts:
            async with factory() as session:
                try:
                    async with with_shop_scope(session, shop_id):
                        result = await svc.ingest(
                            session,
                            shop_id=shop_id,
                            platform="shopee",
                            dataset=post.dataset,
                            body=svc.IngestBody.model_validate(post.body),
                            token_id=None,
                            now=utc_now_naive(),
                        )
                    await session.commit()
                except svc.IngestRejected as exc:
                    await session.rollback()
                    raise SystemExit(
                        f"{post.file} {post.dataset}: {exc.code} {exc.errors[:3]}"
                    ) from None
            outcome["duplicate" if result.duplicate else "stored"] += 1
    finally:
        await engine.dispose()
    return outcome


async def bootstrap_local_shop(database_url: str, shop_name: str) -> uuid.UUID:
    """A local user + Shopee shop + ``service`` consent (development only)."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.database import Shop, User
    from juli_backend.repositories import utc_now_naive
    from juli_backend.services.consent import grant_consent
    from juli_backend.services.ingest import connect_shopee_shop

    engine = create_async_engine(async_database_url(database_url))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            existing = (
                await session.execute(select(Shop).where(Shop.shop_name == shop_name))
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id
            user = User(id=uuid.uuid4(), phone=None)
            session.add(user)
            await session.flush()
            shop = await connect_shopee_shop(session, user_id=user.id, shop_name=shop_name)
            await grant_consent(
                session,
                shop.id,
                scope="service",
                method="contract_paper",
                terms_version="local-dev",
                evidence_ref="local database only (ADR-117 §6); not a signed contract",
                granted_by="juli operator (local)",
                granted_at=utc_now_naive(),
            )
            await session.commit()
            return shop.id
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("folder", type=Path, help="the exports folder (raw/)")
    parser.add_argument("--dry-run", action="store_true", help="parse and validate only")
    parser.add_argument("--only", action="append", default=[], help="load only these datasets")
    parser.add_argument("--api-url")
    parser.add_argument("--token-env", default="JULI_INGEST_TOKEN")
    parser.add_argument("--database-url")
    parser.add_argument("--shop-id", type=uuid.UUID)
    parser.add_argument("--bootstrap-local-shop", metavar="SHOP_NAME")
    parser.add_argument("--allow-remote-database", action="store_true")
    args = parser.parse_args(argv)

    parsed = parse_folder(args.folder)
    if args.only:
        parsed.posts = [post for post in parsed.posts if post.dataset in args.only]
    print(summary(parsed))
    problems = validate(parsed, datetime.now(UTC).replace(tzinfo=None))
    if problems:
        print(f"{len(problems)} post(s) the gateway would refuse:", file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"all {len(parsed.posts)} posts validate")
    if args.dry_run:
        return 0

    if args.api_url:
        token = os.environ.get(args.token_env, "").strip()
        if not token:
            raise SystemExit(f"set {args.token_env} to an ingest token")
        outcome = send_http(parsed.posts, args.api_url, token)
    elif args.database_url:
        _require_local(args.database_url, args.allow_remote_database)
        shop_id = args.shop_id
        if args.bootstrap_local_shop:
            _require_local(args.database_url, allow_remote=False)
            shop_id = asyncio.run(
                bootstrap_local_shop(args.database_url, args.bootstrap_local_shop)
            )
            print(f"local shop {shop_id}")
        if shop_id is None:
            raise SystemExit("--shop-id (or --bootstrap-local-shop) is required")
        outcome = asyncio.run(send_direct(parsed.posts, args.database_url, shop_id))
    else:
        raise SystemExit("choose --dry-run, --api-url or --database-url")
    print(", ".join(f"{k}: {v}" for k, v in sorted(outcome.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
