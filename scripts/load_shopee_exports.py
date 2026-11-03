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

The affiliate exports ProductPerformance / Open Campaign Analytics / AMSAffiliatePerformance
carry no period: pass ``--window 2026-10-01:2026-10-31`` or they are not loaded. Affiliate order
lines (SellerConversionReport) and the ad change log (ops_log_*) are parsed and validated but
RESERVED: no table yet, so they are counted separately and never sent. Order ids are hashed with
``JULI_ORDER_REF_KEY`` (random per run when unset).

The summary prints counts per dataset, never values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from scripts.shopee_exports.parse import Parsed, Post, parse_folder

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Cloudflare in front of api.app-juli.com refuses the default "Python-urllib/x" agent
# (403 "error code: 1010") before the request reaches the gateway.
USER_AGENT = "juli-shopee-export-loader/1.0"


def validate(parsed: Parsed, now: datetime) -> list[str]:
    """Each post checked by the gateway's own validator (no database)."""
    from juli_backend.services.ingest.gateway import IngestRejected, validate_rows
    from juli_backend.services.ingest.mapping import dataset_spec
    from juli_backend.services.ingest.reserved import RESERVED_DATASETS, validate_reserved
    from juli_backend.services.ingest.schemas import IngestBody

    problems: list[str] = []
    for post in parsed.reserved:
        # Reserved names are validated against their own models and never sent.
        try:
            validate_reserved(post.dataset, IngestBody.model_validate(post.body))
        except (ValidationError, ValueError, KeyError) as exc:
            problems.append(f"{post.file} {post.dataset} (reserved): {str(exc)[:200]}")
        if post.dataset not in RESERVED_DATASETS:
            problems.append(f"{post.file}: {post.dataset} is not a reserved dataset")
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
    if parsed.reserved:
        held: Counter[str] = Counter(post.dataset for post in parsed.reserved)
        held_rows: Counter[str] = Counter()
        for post in parsed.reserved:
            held_rows[post.dataset] += len(post.body["rows"])
        lines.append("reserved (parsed and validated, NOT sent: no table yet):")
        lines += [f"{name:<26}{held[name]:>7}{held_rows[name]:>9}" for name in sorted(held)]
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


def _retry_after(detail: str) -> int | None:
    """Seconds the gateway asks us to wait on a 429 (``retry_after_seconds``), else None."""
    try:
        seconds = json.loads(detail)["detail"]["retry_after_seconds"]
    except (ValueError, KeyError, TypeError):
        return None
    return int(seconds) if isinstance(seconds, int | float) and seconds >= 0 else None


def send_http(
    posts: list[Post],
    api_url: str,
    token: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_waits: int = 10,
) -> Counter[str]:
    """POST each body in order. The gateway allows 120 posts per shop per 10 minutes, so a
    429 waits out ``retry_after_seconds`` and resends the same post (bodies are idempotent);
    any other error stops the load."""
    outcome: Counter[str] = Counter()
    waits = 0
    for index, post in enumerate(posts, start=1):
        while True:
            request = urllib.request.Request(
                f"{api_url.rstrip('/')}/v1/ingest/shopee/{post.dataset}",
                data=json.dumps(post.body, ensure_ascii=False).encode(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    result = json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                seconds = _retry_after(detail) if exc.code == 429 else None
                if seconds is None or waits >= max_waits:
                    raise SystemExit(
                        f"{post.file} {post.dataset}: HTTP {exc.code} {detail}"
                    ) from None
                waits += 1
                print(f"rate limited after {index - 1}/{len(posts)} posts; waiting {seconds + 1}s")
                sleep(seconds + 1)
                continue
            outcome["duplicate" if result.get("duplicate") else "stored"] += 1
            break
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


def _window(text: str) -> tuple[date, date]:
    try:
        start, end = (date.fromisoformat(part) for part in text.split(":"))
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD:YYYY-MM-DD") from None
    if end < start:
        raise argparse.ArgumentTypeError("the window ends before it starts")
    return start, end


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("folder", type=Path, help="the exports folder (raw/)")
    parser.add_argument("--dry-run", action="store_true", help="parse and validate only")
    parser.add_argument("--only", action="append", default=[], help="load only these datasets")
    parser.add_argument(
        "--window",
        type=_window,
        metavar="FROM:TO",
        help="YYYY-MM-DD:YYYY-MM-DD period of the affiliate exports that state none "
        "(ProductPerformance, Open Campaign Analytics, AMSAffiliatePerformance)",
    )
    parser.add_argument("--api-url")
    parser.add_argument("--token-env", default="JULI_INGEST_TOKEN")
    parser.add_argument("--database-url")
    parser.add_argument("--shop-id", type=uuid.UUID)
    parser.add_argument("--bootstrap-local-shop", metavar="SHOP_NAME")
    parser.add_argument("--allow-remote-database", action="store_true")
    args = parser.parse_args(argv)

    parsed = parse_folder(args.folder, window=args.window)
    if args.only:
        parsed.posts = [post for post in parsed.posts if post.dataset in args.only]
        parsed.reserved = [post for post in parsed.reserved if post.dataset in args.only]
    print(summary(parsed))
    problems = validate(parsed, datetime.now(UTC).replace(tzinfo=None))
    if problems:
        print(f"{len(problems)} post(s) the gateway would refuse:", file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        return 1
    held = f" (+ {len(parsed.reserved)} reserved, not sent)" if parsed.reserved else ""
    print(f"all {len(parsed.posts)} posts validate{held}")
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
