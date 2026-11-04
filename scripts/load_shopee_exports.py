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
carry no period: pass ``--window 2026-10-01:2026-10-31`` or they are not loaded. The order export
(Order.all.*.xlsx) is read through ``scripts/shopee_exports/orders.py`` (the buyer's columns are
never decoded) and posted FIRST as ``order_lines``; affiliate order lines (SellerConversionReport)
then mark the matching lines. Order ids are hashed with the shop's key when
``JULI_ORDER_REF_MASTER_KEY`` and ``--shop-id`` are set (the key the Ops upload page is handed, so
the browser and this loader agree on an order), else with ``JULI_ORDER_REF_KEY``, else a random
run-local key.

The income export (``Income.T<m>.<from>_<to>.xlsx``, Tài chính › Doanh thu) is read through
``scripts/shopee_exports/income.py`` (the buyer's name and payment method, the invoice tax code,
product names and voucher text are never decoded) and posted as ``order_income``: what Shopee
actually charged and paid per order, keyed by the same hashed order id as the order lines. After
the summary the loader prints, per income file, how many of its orders match an order line (the
ones of this folder, plus the shop's stored ones with ``--database-url``) and how many do not, and
the month's reconciliation: the sum of the Order rows against the file's own Summary sheet,
line by line.

The summary prints counts per dataset, never values (the income reconciliation prints the
month's totals - shop aggregates, not an order).
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

#: Outcome keys that start with this carry a gateway warning code (P91 D-14); the text is shown
#: to Ops.
WARNING_PREFIX = "warning: "
WARNING_TEXT = {
    "seller_support_shipping_nonzero": (
        'WARNING (Ops): "Phí vận chuyển - Người bán hỗ trợ" has a non-zero value for the '
        "first time in this shop's income export. It is stored for reference only and is "
        "NOT subtracted from the profit. Ops: check what it is (a seller-funded shipping "
        "subsidy?) and decide whether the net shipping cost needs it before anyone relies "
        "on the shipping figure."
    ),
}


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
    if parsed.skipped_reasons:
        lines.append(f"files not loaded ({len(parsed.skipped_reasons)}):")
        lines += [f"  {name}: {why}" for name, why in sorted(parsed.skipped_reasons.items())]
    for note, count in sorted(parsed.notes.items()):
        lines.append(f"note: {note} x{count}")
    return "\n".join(lines)


def income_report(parsed: Parsed, stored_refs: set[str] | None = None) -> str:
    """Per income file: orders matched to order lines vs unmatched, and the monthly totals of
    the Order rows against the Summary sheet. ``stored_refs``: order refs already in the shop's
    database (None = not looked up, only this run's order exports count)."""
    if not parsed.income_files:
        return ""
    known = {
        row["order_ref"]
        for post in parsed.posts
        if post.dataset == "order_lines"
        for row in post.body["rows"]
    } | (stored_refs or set())
    scope = "this folder's order exports" + (" and the database" if stored_refs is not None else "")
    lines = [f"income orders vs order lines ({scope}):"]
    for income in parsed.income_files:
        refs = income.refs
        matched = len(refs & known)
        share = f"{matched / len(refs) * 100:.1f}%" if refs else "n/a"
        lines.append(
            f"  {income.file}: {len(refs)} orders, {matched} matched ({share}), "
            f"{len(refs) - matched} not in the order lines"
        )
        lines.append(
            f"    payout = sum of parts on {len(refs) - income.unreconciled}/{len(refs)} orders"
        )
        off = [r for r in income.recon if r.diff != 0]
        lines.append(
            f"    Summary reconciliation: {len(income.recon) - len(off)}/{len(income.recon)} "
            "lines add up"
        )
        for row in off:
            lines.append(
                f"      DIFF {row.label}: Summary {row.summary} vs orders {row.orders} "
                f"({row.diff:+})"
            )
    return "\n".join(lines)


async def stored_order_refs(database_url: str, shop_id: uuid.UUID, refs: set[str]) -> set[str]:
    """Which of ``refs`` already have an order line in the shop's (local) database."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.models.shopee_profit import ShopeeOrderLine

    engine = create_async_engine(async_database_url(database_url))
    found: set[str] = set()
    try:
        ordered = sorted(refs)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with with_shop_scope(session, shop_id):
                for start in range(0, len(ordered), 1000):
                    part = ordered[start : start + 1000]
                    rows = await session.execute(
                        select(ShopeeOrderLine.order_ref)
                        .where(
                            ShopeeOrderLine.shop_id == shop_id,
                            ShopeeOrderLine.order_ref.in_(part),
                        )
                        .distinct()
                    )
                    found.update(rows.scalars())
    finally:
        await engine.dispose()
    return found


def _shop_order_ref_key(shop_id: uuid.UUID | None) -> bytes | None:
    """The shop's ``order_ref`` key when ``JULI_ORDER_REF_MASTER_KEY`` and ``--shop-id`` are both
    given: the same key the Ops upload page is handed, so the CLI and the browser agree on an
    order. None otherwise (``JULI_ORDER_REF_KEY`` or a run-local random key, as before)."""
    from juli_backend.services.ingest import order_ref

    if shop_id is None or not os.environ.get(order_ref.ENV_MASTER, "").strip():
        return None
    return order_ref.shop_key(order_ref.master_key(), shop_id)


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
            for code in result.get("warnings") or ():
                outcome[f"{WARNING_PREFIX}{code}"] += 1
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
            for code in result.warnings:
                outcome[f"{WARNING_PREFIX}{code}"] += 1
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

    parsed = parse_folder(
        args.folder, window=args.window, order_ref_key=_shop_order_ref_key(args.shop_id)
    )
    if args.only:
        parsed.posts = [post for post in parsed.posts if post.dataset in args.only]
    print(summary(parsed))
    stored: set[str] | None = None
    if parsed.income_files and args.database_url and args.shop_id:
        _require_local(args.database_url, args.allow_remote_database)
        income_refs = set().union(*(f.refs for f in parsed.income_files))
        stored = asyncio.run(stored_order_refs(args.database_url, args.shop_id, income_refs))
    print(income_report(parsed, stored))
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
    for key in sorted(outcome):
        if key.startswith(WARNING_PREFIX):
            code = key[len(WARNING_PREFIX) :]
            print(WARNING_TEXT.get(code, f"WARNING (Ops): the gateway reported {code}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
