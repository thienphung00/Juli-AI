"""P90 step 9c acceptance on loaded data. PRINTS COUNTS AND AGGREGATES ONLY.

    python scripts/shopee_listing_acceptance.py --database-url postgresql://...@127.0.0.1/... \\
        --shop-id UUID [--as-of 2026-10-28] [--seed-targets 1.3]

The shop's Shopee files must be loaded first (``scripts/load_shopee_exports.py``). Local database
only. Because a fresh local database has no keyword key list, the run first decomposes the
shop's own titles into keyword seeds and gives every product up to five "Chính" keywords (the
longest combinations first) -- an acceptance stand-in for the operator's choice, written only
when the shop has no roled seed yet. Then: the listing cards (counts by kind, title lengths,
banned terms), the ranking with the listing cards in it, the card references on the analytics
payloads (Demo sees published cards only, Ops drafts too) and the new analytics fields.
No title, product name, SKU text or row value is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services import shop_keywords
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_analytics import queries
from juli_backend.services.shopee_recommendations import config, store
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations.loader import load_env
from scripts.shopee_reco_acceptance import seed_targets

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        FAILS.append(name)


async def ensure_keyword_roles(session, shop_id: uuid.UUID, now: datetime) -> str:
    have = await session.scalar(
        select(func.count())
        .select_from(ShopKeywordSeed)
        .where(ShopKeywordSeed.shop_id == shop_id, ShopKeywordSeed.role.is_not(None))
    )
    if have:
        return f"{have} roled seeds already stored"
    res = await shop_keywords.generate(
        session, shop_id, "shopee", brand=None, staff_id=None, now=now
    )
    seeds = (
        await session.scalars(select(ShopKeywordSeed).where(ShopKeywordSeed.shop_id == shop_id))
    ).all()
    used: Counter[str] = Counter()
    for seed in sorted(seeds, key=lambda s: (-len(s.keyword), s.keyword)):
        if all(used[i] < config.MAX_CORE_KEYWORDS for i in seed.item_ids):
            seed.role = "chinh"
            for i in seed.item_ids:
                used[i] += 1
        else:
            seed.role = "phu"
        seed.item_scope = None
    await session.flush()
    return f"{res.titles} titles -> {res.candidates} combinations, {sum(used.values())} core slots"


async def main_async(args: argparse.Namespace) -> None:
    host = urlparse(args.database_url).hostname
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"refusing {host!r}: local databases only")
    engine = create_async_engine(async_database_url(args.database_url))
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with with_shop_scope(session, args.shop_id):
                as_of = args.as_of
                env0 = await load_env(session, args.shop_id, as_of=as_of)
                assert env0 is not None, "the shop has no Shopee numbers"
                as_of = env0.as_of
                print(f"== window to {as_of}; products with orders {len(env0.item_ids())}")
                print("== keywords:", await ensure_keyword_roles(session, args.shop_id, now))
                if args.seed_targets:
                    print(
                        "== targets:",
                        await seed_targets(session, args.shop_id, as_of, args.seed_targets),
                    )
                await session.commit()
                env = await load_env(session, args.shop_id, as_of=as_of)
                report = await reco.generate_cards(
                    session, args.shop_id, now=now, as_of=as_of, env=env, max_cards=200
                )
                await session.commit()
                print(
                    f"== cards generated {report.generated}, persisted {report.persisted}; "
                    f"by family {dict(report.by_family)}"
                )
                print(f"== by kind {dict(report.by_kind)}")
                print(f"== ranking {report.rank.json() if report.rank else None}")
                rows = await store.list_cards(session, args.shop_id)
                listing = [(p, c) for p, c in rows if c["family"] == "listing"]
                kinds = Counter(c["change_kind"] for _, c in listing)
                check("listing cards generated", bool(listing), f"{dict(kinds)}")
                titles = [c for _, c in listing if c["change_kind"] == "title"]
                lens = [len(c["inputs"]["title"]) for c in titles]
                check(
                    "titles <= 120 characters",
                    all(n <= config.MAX_TITLE_CHARS for n in lens),
                    f"{len(lens)} titles, longest {max(lens, default=0)}, "
                    f"shortest {min(lens, default=0)}",
                )
                dirty = [
                    c for c in titles if not lst.is_clean(c["inputs"]["title"], env.banned_terms)
                ]
                check(
                    "0 banned terms in proposed titles",
                    not dirty,
                    f"{len(dirty)} of {len(titles)} (seller terms {len(env.banned_terms)}, "
                    f"generic patterns {len(lst.BANNED_PATTERNS)})",
                )
                fixed = Counter()
                for c in titles:
                    b, a = c["certain"]["audit_before"], c["certain"]["audit_after"]
                    fixed["missing_before"] += len(b["core_missing"])
                    fixed["late_before"] += len(b["core_late"])
                    fixed["missing_after"] += len(a["core_missing"])
                    fixed["late_after"] += len(a["core_late"])
                    fixed["too_long_before"] += int(b["too_long"])
                    fixed["too_long_after"] += int(a["too_long"])
                print(f"   title audit (summed over cards): {dict(fixed)}")
                check(
                    "titles fix more than they leave",
                    fixed["missing_after"] + fixed["late_after"]
                    < fixed["missing_before"] + fixed["late_before"]
                    or not titles,
                    "",
                )
                pos = Counter(
                    c["rank"]["position"] <= config.DEFAULT_TOP_N
                    for _, c in rows
                    if c["family"] == "listing"
                )
                print(f"   listing cards in the top {config.DEFAULT_TOP_N}: {pos[True]}")
                lift = [c["predicted"]["money_per_month"]["predicted"] for _, c in listing]
                check(
                    "listing cards carry a predicted range and no certain layer",
                    all(
                        c["certain"]["traffic_lever"] is True
                        and c["predicted"]["money_per_month"]["certain"]["dgmv"] == 0
                        for _, c in listing
                    ),
                    f"{len(lift)} cards",
                )
                sheets = Counter(
                    ch["change_kind"] for _, c in listing for ch in c["execution_sheet"]["changes"]
                )
                print(f"   execution-sheet read-back kinds: {dict(sheets)}")

                # ---- card references: publish the first three, read the screens both ways
                first = [uuid.UUID(c) for c in report.card_ids[:3]]
                sent = await reco.publish(session, args.shop_id, first, now=now)
                drafts_left = len(await store.list_cards(session, args.shop_id, statuses=["draft"]))
                print(f"== published {len(sent)} cards (drafts left {drafts_left})")
                await session.commit()
                p = {"period": "30d", "as_of": as_of}
                for audience in ("seller", "ops"):
                    matrix = await reco.attach_card_refs(
                        session,
                        args.shop_id,
                        "matrix",
                        await queries.matrix(session, args.shop_id, **p),
                        audience=audience,
                    )
                    crit = await reco.attach_card_refs(
                        session,
                        args.shop_id,
                        "critical",
                        await queries.critical(session, args.shop_id, **p),
                        audience=audience,
                    )
                    rank = await reco.attach_card_refs(
                        session,
                        args.shop_id,
                        "ranking",
                        await queries.ranking(session, args.shop_id, kind="products", **p),
                        audience=audience,
                    )
                    n_m = sum("card" in r for r in matrix["products"])
                    n_c = sum("card" in i for i in crit["items"])
                    n_r = sum("card" in r for r in [*rank.get("down", []), *rank.get("up", [])])
                    print(
                        f"   card refs ({audience}): matrix rows {n_m}/{len(matrix['products'])}, "
                        f"critical items {n_c}/{len(crit['items'])}, ranking rows {n_r}"
                    )
                    ok = all(
                        set(r["card"]) == {"id", "family", "title", "at_stake_per_month"}
                        for r in matrix["products"]
                        if "card" in r
                    )
                    check(f"card ref shape ({audience})", ok, "")
                    if audience == "seller":
                        n_seller = n_m
                    else:
                        n_ops = n_m
                check(
                    "Ops sees at least what the seller sees",
                    n_ops >= n_seller,
                    f"{n_ops} >= {n_seller}",
                )

                # ---- the new analytics fields
                matrix = await queries.matrix(session, args.shop_id, **p)
                with_five = sum("five_numbers" in r for r in matrix["products"])
                with_disc = sum(
                    r["five_numbers"]["discount"]["pct_after"] is not None
                    for r in matrix["products"]
                )
                kids = sum(r["card_children"] is not None for r in matrix["products"])
                print(
                    f"== matrix: rows {len(matrix['products'])}, with numbers 1+2 {with_five} "
                    f"(discount known {with_disc}), with Thẻ sản phẩm children {kids}"
                )
                ids = [r["product_id"] for r in matrix["products"][:10]]
                daily = versions = campaigns = 0
                for pid in ids:
                    page = await queries.product_page(
                        session, args.shop_id, pid, period="30d", as_of=as_of
                    )
                    daily += bool(page["daily"]["days"])
                    versions += bool(page["header"]["versions"])
                    campaigns += bool(page["ads"]["campaigns"])
                print(
                    f"== product pages ({len(ids)} sampled): daily series {daily}, "
                    f"snapshot versions {versions}, ad campaigns {campaigns}"
                )
                over = await queries.overview(session, args.shop_id, **p)
                fresh = over["freshness"]["datasets"]
                stale = sum(1 for v in fresh.values() if v["age_days"] > 3)
                newest = min(v["age_days"] for v in fresh.values())
                print(
                    f"== freshness: {len(fresh)} datasets, newest {newest}d "
                    f"behind the window end, {stale} more than 3 days behind"
                )
                check("freshness reported", bool(fresh), f"{len(fresh)} datasets")
                await session.rollback()  # the acceptance run leaves the cards it created; no more
    finally:
        await engine.dispose()
    print("\nALL PASS" if not FAILS else f"\nFAILED: {FAILS}")
    if FAILS:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--shop-id", required=True, type=uuid.UUID)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--seed-targets", type=float, default=0.0)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
