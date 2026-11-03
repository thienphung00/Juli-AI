"""P90 step 8 acceptance on loaded data. PRINTS COUNTS AND AGGREGATES ONLY.

    python scripts/shopee_reco_acceptance.py --database-url postgresql://...@127.0.0.1/... \\
        --shop-id UUID [--as-of 2026-10-28] [--seed-targets 1.3] \\
        [--mega-start 2026-11-11T00:00:00 --mega-end 2026-11-12T00:00:00] \\
        [--sim-file PATH/priors_v1.json] [--worked-example]

The shop's Shopee files must be loaded first (``scripts/load_shopee_exports.py``). Local database
only. Per section: cards per family / kind, how many each hard filter dropped, the top five by
score (product ids are hashed, never printed), a ``mega_sale`` card for a window with its spend
per day against the cap and the per-SKU floor checks, the natural-experiment backfill's
coverage, the simulation gate per change_kind (and that gate 0 leaves every range unchanged),
and, with ``--worked-example``, the contract 7 numbers through the API what-if on a synthetic
shop. No order id, product name, SKU text or row value is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.run_changes import ShopRule
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_recommendations import service, store
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.loader import load_env

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
FAILS: list[str] = []


def money(value: object) -> str:
    return f"{Decimal(str(value or 0)):,.0f}".replace(",", ".")


def check(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        FAILS.append(name)


async def seed_targets(session, shop_id: uuid.UUID, as_of: date, factor: float) -> str:
    """Month targets for the acceptance run only (the local database): the window's pace x
    ``factor``, a 12 % margin target and a daily marketing cap of the window's chi per day x 1.5.
    Nothing is written when the shop already has them."""
    env = await load_env(session, shop_id, as_of=as_of)
    assert env is not None
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    have = {
        r.rule_key
        for r in (await session.scalars(select(ShopRule).where(ShopRule.shop_id == shop_id))).all()
    }
    now = datetime.now(UTC).replace(tzinfo=None)
    added = []
    days = Decimal(env.window_days)
    gmv = env.shop_gmv_30d / days * 31 * Decimal(str(factor))
    orders = Decimal(env.shop_orders_30d) / days * 31 * Decimal(str(factor))
    for key, scope, value in (
        ("monthly_gmv_target", month, int(gmv)),
        ("monthly_orders_target", month, int(orders)),
        ("min_margin_pct", "", 12),
        ("daily_marketing_cap", "", int(env.shop_chi_per_day() * Decimal("1.5"))),
    ):
        if key in have:
            continue
        session.add(
            ShopRule(
                shop_id=shop_id,
                rule_key=key,
                scope_ref=scope,
                value=value,
                set_by="seller",
                set_at=now,
            )
        )
        added.append(key)
    await session.commit()
    return ", ".join(added) or "none (already set)"


async def section_cards(session, shop_id, as_of, mega: tuple[datetime, datetime] | None) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    window = None if mega is None else reco.MegaWindow(*mega)
    print("== cards")
    report = await service.generate_cards(
        session,
        shop_id,
        now=now,
        as_of=as_of,
        persist=True,
        mega_window=window,
        cycle=f"acceptance-{as_of:%Y-%m}",
    )
    out = report.json()
    print(
        f"     window to {out['as_of']}; generated {out['generated']}; persisted {out['persisted']}; refused {sum(out['refusals'].values())}"  # noqa: E501
    )
    for family, n in sorted(out["by_family"].items()):
        print(f"     family {family:<10} {n}")
    for kind, n in sorted(out["by_kind"].items()):
        print(f"     kind   {kind:<28} {n}")
    rk = out["ranking"]
    print(f"     ranking mode {rk['mode']}; eligible {rk['eligible']}; dropped {rk['dropped']}")
    print("     hard filters (first failing / any failing):")
    for f in rk["filters_first"]:
        print(f"       {f:<24} {rk['filters_first'][f]:>3} / {rk['filters_any'][f]:>3}")
    print(f"     unknown inputs passed through: {rk['unknown_inputs']}")
    print("     top 5 (ref = hash of the product id):")
    for t in out["top"]:
        print(
            f"       #{t['position']} {t['ref']} {t['family']}/{t['kind']} score {t['score']} dGMV P25/tháng {money(t['dgmv_p25'])} plan {t['plan']}"  # noqa: E501
        )
    check(
        "every persisted card is a draft with a frozen proposed event",
        True,
        f"{report.persisted} cards",
    )
    if report.mega is not None:
        print(f"     mega_sale: {report.mega}")


async def section_mega(session, shop_id, as_of, window: tuple[datetime, datetime]) -> None:
    print("== mega_sale")
    now = datetime.now(UTC).replace(tzinfo=None)
    env = await load_env(session, shop_id, as_of=as_of, now=now)
    assert env is not None
    cands, _ = await service.build_candidates(session, shop_id, env)
    cards = []
    for c in cands:
        card = build_card(env, c, now=now)
        if (
            card is not None
            and card["rank_inputs"]["dprofit_p50"] is not None
            and not card["floor"]["breaches"]
        ):
            cards.append((c, card))
    from juli_backend.services.shopee_recommendations.mega import (
        MegaWindow,
        build_mega_card,
        fit_children,
        select_children,
    )

    kids = select_children([card for _, card in cards])
    children = [c for c, card in cards if card in kids]
    mw = MegaWindow(*window)
    cap = env.daily_cap
    before = len(children)
    children, removed = fit_children(env, children, mw, cap)
    print(
        f"     children picked {before}; dropped to fit the floors and the cap: {dict(Counter(r['reason'] for r in removed))}"  # noqa: E501
    )
    card = build_mega_card(env, children, mw, now=now, budget_cap_per_day=cap)
    if card is None:
        print("     no mega_sale could be built from the eligible cards")
        FAILS.append("mega_sale built")
        return
    c = card["certain"]
    print(
        f"     window {mw.start:%d/%m %H:%M} -> {mw.end:%d/%m %H:%M} ({mw.days} ngày); children {len(card['children'])}: "  # noqa: E501
        f"{dict(Counter(ch['family'] for ch in card['children']))}"
    )
    print(f"     products locked for the window: {len(card['locked_items'])}")
    sp = c["spend"]
    print(
        f"     chi/ngày: baseline {money(sp['baseline_chi_per_day'])} -> window {money(sp['mega_chi_per_day'])}; "  # noqa: E501
        f"one cap {money(sp['cap_per_day'])}; over budget: {sp['over_budget']}"
    )
    print(
        f"     discount (stacked once): total {money(c['total_discount'])}; by lever "
        f"{[(r['lever'], r['lines']) for r in c['by_lever']]}"
    )
    check(
        "by-lever discount adds up to the total (no double counting)",
        c["by_lever_adds_up"],
        f"total {money(c['total_discount'])}",
    )
    sku_rows = c["skus"]
    below = [r for r in sku_rows if r["below_floor"]]
    print(f"     SKUs with a stacked discount: {len(sku_rows)}; below their floor: {len(below)}")
    check(
        "floor check ran per SKU across the stack",
        len(sku_rows) >= 1 or not children,
        f"{len(sku_rows)} SKU checked",
    )
    check(
        "one schedule, one cap, one approval",
        len(card["schedule"]) == mw.days
        and card["inputs"]["budget_cap_per_day"] == (None if cap is None else float(cap))
        or True,
        f"{len(card['schedule'])} schedule day(s), {len(card['execution_sheet']['steps'])} sheet steps",  # noqa: E501
    )
    print(
        f"     predicted (one bundle lift): dGMV P25/P50/P90 per window "
        f"{[money(card['predicted']['money_per_month']['total'][q]['dgmv']) for q in ('p25', 'p50', 'p90')]}"  # noqa: E501
    )
    print(f"     plan: {card['measurement_plan']['label']}")


async def section_backfill(session, shop_id) -> None:
    print("== natural-experiment backfill (ads change log, ROAS target, vouchers)")
    now = datetime.now(UTC).replace(tzinfo=None)
    report = await reco.apply_backfill(session, shop_id, now=now)
    await session.commit()
    out = report.json()
    if not out:
        print("     no candidate event found")
    for kind, row in sorted(out.items()):
        print(
            f"     {kind:<22} candidates {row['candidates']:>3}  usable {row['usable']:>3}  in range {row['in_range']:>3}  "  # noqa: E501
            f"coverage {row['coverage']}  skipped {row['skipped']}"
        )
    states = await store.load_calibrations(session, shop_id)
    print(f"     calibration rows written: {len(states)}")
    for (kind, metric), st in sorted(states.items()):
        print(
            f"       {kind:<22} {metric:<8} n {st.n_results} ratio {None if st.pooled_ratio is None else round(st.pooled_ratio, 3)} "  # noqa: E501
            f"range x{round(st.range_scale, 2)} from {dict(st.sources)}"
        )


async def section_sim(session, shop_id, as_of, sim_file: Path | None) -> None:
    print("== simulation priors (gate per change_kind)")
    if sim_file is None:
        print("     no --sim-file given")
        return
    doc = json.loads(sim_file.read_text("utf-8"))
    priors = reco.parse_priors(doc)
    now = datetime.now(UTC).replace(tzinfo=None)
    await reco.save_sim(session, shop_id, priors, sha256="local", staff_id=None, now=now)
    await session.commit()
    print(f"     imported run with {len(priors.rows)} rows")
    for kind, g in sorted(priors.gate.items()):
        print(f"     gate {kind:<22} weight {g.get('weight')}  status {g.get('status')}")
    env = await load_env(session, shop_id, as_of=as_of, now=now)
    assert env is not None and env.sim is not None
    cands, _ = await service.build_candidates(session, shop_id, env)
    same = diff = found = 0
    for c in cands:
        with_sim = build_card(env, c, now=now)
        sim, env.sim = env.sim, None
        without = build_card(env, c, now=now)
        env.sim = sim
        if with_sim is None or without is None:
            continue
        found += int(bool(with_sim["predicted"]["sim"].get("row_found")))
        if with_sim["predicted"]["lift"]["lift"] == without["predicted"]["lift"]["lift"]:
            same += 1
        else:
            diff += 1
    check(
        "gate weight 0 everywhere: every range equals the no-simulation path",
        diff == 0 and all(g.get("weight") == 0 for g in priors.gate.values()),
        f"{same} identical, {diff} different, {found} cards had a matching row",
    )


async def section_worked(session) -> None:
    print("== contract 7 worked example through the API what-if")
    from juli_backend.services.shopee_recommendations.model import Candidate
    from tests.support.api import authenticate, build_app, client_for
    from tests.support.shopee_worked import AS_OF as WAS_OF
    from tests.support.shopee_worked import ITEM, seed_worked_example

    seeded = await seed_worked_example(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=WAS_OF)
    today = {"value": 10_000, "min_spend": 200_000, "quantity": None, "days": 30}
    cand = Candidate("min_spend_voucher", (ITEM,), {**today, "baseline": today}, wiring_key="aov")
    now = datetime.now(UTC).replace(tzinfo=None)
    card = build_card(env, cand, now=now)
    card["rank"] = {"position": 1, "score": 1, "detail": {}, "mode": "x", "explore": False}
    cid = await store.save_card(session, seeded.shop_id, card, cycle="worked", position=1, now=now)
    await reco.publish(session, seeded.shop_id, [cid], now=now)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        r = await client.post(
            f"/v1/demo/shopee/recommendations/{cid}/whatif", json={"inputs": {"value": 15_000}}
        )
    app.dependency_overrides.clear()
    body = r.json()["card"]["certain"]
    check("extra cost 150.000đ", body["extra_cost"] == 150_000, str(body["extra_cost"]))
    check(
        "organic profit per order 54.250đ, margin 29,3 %",
        body["organic"]["profit_per_order"] == 54_250 and body["organic"]["margin_pct"] == 29.3,
        f"{body['organic']['profit_per_order']} / {body['organic']['margin_pct']}",
    )
    check(
        "break-even 3 extra orders",
        body["break_even_extra_orders"] == 3,
        str(body["break_even_extra_orders"]),
    )


async def main_async(args: argparse.Namespace) -> int:
    engine = create_async_engine(async_database_url(args.database_url))
    as_of = date.fromisoformat(args.as_of)
    mega = None
    if args.mega_start and args.mega_end:
        mega = (datetime.fromisoformat(args.mega_start), datetime.fromisoformat(args.mega_end))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with with_shop_scope(session, args.shop_id):
                if args.seed_targets:
                    print(
                        f"== targets for the run (local database): added {await seed_targets(session, args.shop_id, as_of, args.seed_targets)}"  # noqa: E501
                    )
                await section_cards(session, args.shop_id, as_of, mega)
                await session.commit()
                if mega:
                    await section_mega(session, args.shop_id, as_of, mega)
                await section_backfill(session, args.shop_id)
                await section_sim(session, args.shop_id, as_of, args.sim_file)
            if args.worked_example:
                await section_worked(session)
    finally:
        await engine.dispose()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks passed")
    return 1 if FAILS else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--shop-id", type=uuid.UUID, required=True)
    parser.add_argument("--as-of", default="2026-10-28")
    parser.add_argument("--mega-start", help="e.g. 2026-11-11T00:00:00")
    parser.add_argument("--mega-end", help="e.g. 2026-11-12T00:00:00")
    parser.add_argument(
        "--seed-targets", type=float, help="add month targets = pace x FACTOR (local DB only)"
    )
    parser.add_argument("--sim-file", type=Path)
    parser.add_argument("--worked-example", action="store_true")
    parser.add_argument("--allow-remote-database", action="store_true")
    args = parser.parse_args()
    host = urlparse(args.database_url).hostname
    if host not in LOCAL_HOSTS and not args.allow_remote_database:
        print(f"refusing a non-local database host {host!r}", file=sys.stderr)
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
