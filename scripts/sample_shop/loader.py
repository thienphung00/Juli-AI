"""Load the synthetic shop: JSONL for a dry run, or in-process into a LOCAL database.

    python -m scripts.sample_shop --end-date 2026-11-10 --dry-run --out /tmp/sample
    python -m scripts.sample_shop --end-date 2026-11-10 --database-url postgresql://...@127.0.0.1/db

``--database-url`` runs the same ``services.ingest.ingest`` a Connector's POST reaches (consent,
validation, writers, the materialize hook), then ``materialize.backfill_shop``. Safety, all
refusals raised as :class:`SampleShopRefused` before anything is written:

- a database host other than localhost / 127.0.0.1 / ::1 needs ``--allow-remote-database``;
- the loader writes only a shop IT created: platform shopee, ``shopee_shop_id`` inside the
  reserved synthetic range (``catalog.SAMPLE_SHOPEE_SHOP_ID_MIN..MAX``) and no credential
  (TikTok credential, ingest token, production-write row);
- Fujiwa and the Juli sandbox shop ids are refused by name.

Re-running is idempotent: the shop is found by its reserved id, every write is an upsert.
No LLM, no network.

``--reset`` (``scripts/sample_shop/reset.py``) first deletes the rows reviewers' actions left
(preview unless ``--yes``), keeping the shop row, consent and the audit log, then loads as above.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts.sample_shop import decisions, reset
from scripts.sample_shop.catalog import (
    SAMPLE_SHOP_NAME,
    SAMPLE_SHOPEE_SHOP_ID,
    SAMPLE_SHOPEE_SHOP_ID_MAX,
    SAMPLE_SHOPEE_SHOP_ID_MIN,
)
from scripts.sample_shop.generator import Post, SampleShop, generate

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: Fujiwa (a client's real shop) and Juli's TikTok sandbox shop: never written, whatever else holds.
FORBIDDEN_SHOP_IDS = frozenset(
    {
        uuid.UUID("2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f"),
        uuid.UUID("1862f13b-de2c-4fae-a4ad-70298cead913"),
    }
)
COST_REASON = "Dữ liệu mẫu: giá vốn tổng hợp"


class SampleShopRefused(Exception):
    """A safety rule stopped the load; nothing was written."""


def require_local(url: str, allow_remote: bool) -> None:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS and not allow_remote:
        raise SampleShopRefused(
            f"refusing database host {host!r}: the sample loader writes to a local database "
            "unless --allow-remote-database is given"
        )


def in_reserved_range(shopee_shop_id: str | None) -> bool:
    return (
        shopee_shop_id is not None
        and shopee_shop_id.isdigit()
        and SAMPLE_SHOPEE_SHOP_ID_MIN <= int(shopee_shop_id) <= SAMPLE_SHOPEE_SHOP_ID_MAX
    )


def check_target(
    shop_id: uuid.UUID | None,
    *,
    platform: str,
    shopee_shop_id: str | None,
    has_credentials: bool,
) -> None:
    """Refuse any existing shop this loader did not create."""
    if shop_id in FORBIDDEN_SHOP_IDS:
        raise SampleShopRefused(f"shop {shop_id} is never written by the sample loader")
    if platform != "shopee":
        raise SampleShopRefused("target shop is not a Shopee shop")
    if not in_reserved_range(shopee_shop_id):
        raise SampleShopRefused(
            f"shopee_shop_id {shopee_shop_id!r} is outside the reserved sample range "
            f"{SAMPLE_SHOPEE_SHOP_ID_MIN}..{SAMPLE_SHOPEE_SHOP_ID_MAX}: not a sample shop"
        )
    if has_credentials:
        raise SampleShopRefused("target shop holds a credential: not a sample shop")


def check_new_shopee_id(shopee_shop_id: str) -> None:
    if not in_reserved_range(shopee_shop_id):
        raise SampleShopRefused(f"shopee shop id {shopee_shop_id} is outside the reserved range")


async def _has_credentials(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    from juli_backend.models.ingest import IngestToken
    from juli_backend.models.models import ProductionWriteShop, TikTokCredential

    for model in (TikTokCredential, IngestToken, ProductionWriteShop):
        found = await session.scalar(
            select(func.count()).select_from(model).where(model.shop_id == shop_id)
        )
        if found:
            return True
    return False


@dataclass
class LoadReport:
    shop_id: uuid.UUID
    created: bool
    outcome: Counter[str]
    days_materialized: int
    decisions: decisions.DecisionsReport | None = None


async def ensure_shop(
    factory: async_sessionmaker[AsyncSession],
    shopee_shop_id: str,
    *,
    shop_id: uuid.UUID | None = None,
    now: datetime,
) -> tuple[uuid.UUID, bool]:
    """The sample shop's id (created with its user and ``service`` consent when absent)."""
    from juli_backend.database import Shop, User
    from juli_backend.services.consent import has_consent
    from juli_backend.services.ingest import connect_shopee_shop

    check_new_shopee_id(shopee_shop_id)
    if shop_id in FORBIDDEN_SHOP_IDS:
        raise SampleShopRefused(f"shop {shop_id} is never written by the sample loader")
    async with factory() as session:
        stmt = select(Shop).where(Shop.shopee_shop_id == shopee_shop_id)
        if shop_id is not None:
            stmt = select(Shop).where(Shop.id == shop_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            check_target(
                existing.id,
                platform=existing.platform,
                shopee_shop_id=existing.shopee_shop_id,
                has_credentials=await _has_credentials(session, existing.id),
            )
            if not await has_consent(session, existing.id, "service"):
                await _grant(session, existing.id, now)
                await session.commit()
            return existing.id, False
        if shop_id is not None:
            raise SampleShopRefused(f"shop {shop_id} does not exist; the loader creates its own")
        user = User(id=uuid.uuid4(), phone=None)
        session.add(user)
        await session.flush()
        shop = await connect_shopee_shop(
            session, user_id=user.id, shop_name=SAMPLE_SHOP_NAME, shopee_shop_id=shopee_shop_id
        )
        await _grant(session, shop.id, now)
        await session.commit()
        return shop.id, True


async def _grant(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> None:
    from juli_backend.services.consent import grant_consent

    await grant_consent(
        session,
        shop_id,
        scope="service",
        method="contract_paper",
        terms_version="sample-shop",
        evidence_ref="synthetic sample shop; no client data",
        granted_by="juli operator (sample shop loader)",
        granted_at=now,
    )


async def load(
    factory: async_sessionmaker[AsyncSession],
    sample: SampleShop,
    *,
    shop_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> LoadReport:
    """Ensure the shop, write its costs, ingest every post, rebuild the stored daily rows."""
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.repositories import utc_now_naive
    from juli_backend.services.shop_inputs import Actor, RuleChange, write_versions
    from juli_backend.services.shop_rules.rules import SKU_COST
    from juli_backend.services.shopee_analytics import materialize

    now = now or utc_now_naive()
    if sample.end_date > (now + timedelta(hours=7)).date():
        raise SampleShopRefused(f"--end-date {sample.end_date} is in the future (GMT+7)")
    sid, created = await ensure_shop(factory, sample.shopee_shop_id, shop_id=shop_id, now=now)
    # Costs first: with no data day yet, saving them rebuilds nothing.
    async with factory() as session:
        async with with_shop_scope(session, sid):
            await write_versions(
                session,
                sid,
                [RuleChange(SKU_COST, scope, cost) for scope, cost in sorted(sample.costs.items())],
                actor=Actor("team", None),
                reason=COST_REASON,
                now=now.replace(tzinfo=UTC),
            )
        await session.commit()
    # The gateway rebuilds the stored daily rows after every post (13 posts x 30 days); the loader
    # skips that hook and rebuilds every day once at the end (`backfill_shop`): the same rows.
    # the catalogue reads after the first one carry the title change: the seller changes the title
    # (decisions.run) before the Connector reads the new name
    catalogs = [i for i, p in enumerate(sample.posts) if p.dataset == "item_catalog"]
    late_ix = set(catalogs[1:]) if sample.title_change else set()
    early = [p for i, p in enumerate(sample.posts) if i not in late_ix]
    late = [p for i, p in enumerate(sample.posts) if i in late_ix]
    with mock.patch.object(materialize, "after_ingest", _no_hook):
        outcome = await _ingest_all(factory, early, sid, now)
    async with factory() as session:
        async with with_shop_scope(session, sid):
            report = await materialize.backfill_shop(session, sid)
        await session.commit()

    async def ingest_late() -> None:
        with mock.patch.object(materialize, "after_ingest", _no_hook):
            outcome.update(await _ingest_all(factory, late, sid, now))

    made = await decisions.run(factory, sample, sid, now=now, ingest_late=ingest_late)
    if late and made.skipped:  # a re-run: the late posts are duplicates, post them all the same
        await ingest_late()
    return LoadReport(sid, created, outcome, report.days_written, made)


async def _no_hook(*_args: object, **_kwargs: object) -> None:
    return None


async def _ingest_all(
    factory: async_sessionmaker[AsyncSession], posts: list[Post], sid: uuid.UUID, now: datetime
) -> Counter[str]:
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services import ingest as svc

    outcome: Counter[str] = Counter()
    for post in posts:
        body_dict = dict(post.body)
        captured = datetime.fromisoformat(body_dict["captured_at"])
        if captured.astimezone(UTC).replace(tzinfo=None) > now:
            body_dict["captured_at"] = now.replace(tzinfo=UTC).isoformat()
        async with factory() as session:
            try:
                async with with_shop_scope(session, sid):
                    result = await svc.ingest(
                        session,
                        shop_id=sid,
                        platform="shopee",
                        dataset=post.dataset,
                        body=svc.IngestBody.model_validate(body_dict),
                        token_id=None,
                        now=now,
                    )
                await session.commit()
            except svc.IngestRejected as exc:
                await session.rollback()
                raise SampleShopRefused(
                    f"gateway refused {post.dataset}: {exc.code} {exc.errors[:3]}"
                ) from None
        outcome["duplicate" if result.duplicate else "stored"] += 1
    return outcome


def write_jsonl(sample: SampleShop, out: Path) -> dict[str, int]:
    """One JSONL file per dataset (a post per line: the exact body a Connector would send)."""
    out.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    for post in sample.posts:
        with (out / f"{post.dataset}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(post.body, ensure_ascii=False, sort_keys=True) + "\n")
        counts[post.dataset] += len(post.body["rows"])
    costs = {scope: cost for scope, cost in sorted(sample.costs.items())}
    (out / "shop_inputs_sku_cost.json").write_text(
        json.dumps(costs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dict(counts)


def _end_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None


def main(argv: list[str] | None = None, *, clock: Callable[[], datetime] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--end-date", type=_end_date, help="last day (default: yesterday, GMT+7)")
    parser.add_argument("--dry-run", action="store_true", help="write JSONL only")
    parser.add_argument("--out", type=Path, help="directory for --dry-run")
    parser.add_argument("--database-url", help="a LOCAL Postgres (the gateway runs in-process)")
    parser.add_argument("--shop-id", type=uuid.UUID, help="re-use a shop the loader created")
    parser.add_argument("--allow-remote-database", action="store_true")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the sample shop's rows, then re-seed (preview without --yes)",
    )
    parser.add_argument("--yes", action="store_true", help="with --reset: commit the delete")
    args = parser.parse_args(argv)

    now = (clock or (lambda: datetime.now(UTC).replace(tzinfo=None)))()
    end = args.end_date or (now + timedelta(hours=7)).date() - timedelta(days=1)
    sample = generate(end)
    if args.dry_run:
        if args.out is None:
            parser.error("--dry-run needs --out DIR")
        for name, rows in sorted(write_jsonl(sample, args.out).items()):
            print(f"{name:<24}{rows:>7} rows")
        print(
            f"{len(sample.posts)} posts, {sample.start_date}..{sample.end_date}, "
            f"written to {args.out}"
        )
        return 0
    if not args.database_url:
        parser.error("choose --dry-run or --database-url")
    if args.yes and not args.reset:
        parser.error("--yes only goes with --reset")
    try:
        require_local(args.database_url, args.allow_remote_database)
        if args.reset:
            wiped = asyncio.run(
                _run_reset(args.database_url, sample.shopee_shop_id, args.shop_id, args.yes)
            )
            for table, rows in sorted(wiped.deleted.items()):
                print(f"{table:<48}{rows:>7} rows")
            if not wiped.committed:
                print(
                    f"preview: {wiped.total} rows of shop {wiped.shop_id} would be deleted; "
                    "rolled back. Re-run with --yes to reset."
                )
                return 0
            print(f"deleted {wiped.total} rows of shop {wiped.shop_id}; re-seeding")
        report = asyncio.run(_run(args.database_url, sample, args.shop_id, now))
    except (SampleShopRefused, reset.ResetRefused) as exc:
        print(f"refused: {exc}")
        return 2
    print(
        f"shop {report.shop_id} ({'created' if report.created else 'existing'}); "
        + ", ".join(f"{k}: {v}" for k, v in sorted(report.outcome.items()))
        + f"; {report.days_materialized} days materialized"
    )
    return 0


async def _run(
    database_url: str, sample: SampleShop, shop_id: uuid.UUID | None, now: datetime
) -> LoadReport:
    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(database_url))
    try:
        return await load(
            async_sessionmaker(engine, expire_on_commit=False), sample, shop_id=shop_id, now=now
        )
    finally:
        await engine.dispose()


async def _run_reset(
    database_url: str, shopee_shop_id: str, shop_id: uuid.UUID | None, commit: bool
) -> reset.ResetReport:
    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.database import Shop

    engine = create_async_engine(async_database_url(database_url))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        if shop_id is None:
            async with factory() as session:
                shop_id = await session.scalar(
                    select(Shop.id).where(Shop.shopee_shop_id == shopee_shop_id)
                )
            if shop_id is None:
                raise SampleShopRefused(f"no shop with shopee_shop_id {shopee_shop_id} to reset")
        if shop_id in FORBIDDEN_SHOP_IDS:
            raise SampleShopRefused(f"shop {shop_id} is never written by the sample loader")
        return await reset.wipe(factory, shop_id, commit=commit)
    finally:
        await engine.dispose()


__all__ = [
    "FORBIDDEN_SHOP_IDS",
    "LoadReport",
    "SampleShopRefused",
    "SAMPLE_SHOPEE_SHOP_ID",
    "check_target",
    "ensure_shop",
    "load",
    "main",
    "require_local",
    "write_jsonl",
]
