"""Builds the two example reports (Tổng quan, Kế hoạch) from the synthetic sample shop.

Loads "Dữ liệu mẫu" (scripts/sample_shop) into a throwaway in-memory SQLite, creates one EXECUTED
plan (Đang chạy) and one DRAFT plan through the app's plan services, reads every number through the
app's functions (``services/exports/collect``) and writes both .xlsx files plus a JSON of the
source numbers next to each.

    PYTHONPATH=backend/src:. python -m scripts.exports.make_examples --out DIR
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database import Base
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import Shop
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_plans import PLAN_DRAFT, PLAN_EXECUTED, ShopRecoPlan
from juli_backend.services.exports import ke_hoach_xlsx, tong_quan_xlsx
from juli_backend.services.exports.collect import collect_ke_hoach, collect_tong_quan
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import manual, month_plan, plans, service
from scripts.sample_shop import loader
from scripts.sample_shop.generator import generate

SCHEMAS = ("ops", "bronze", "gold", "silver")


def _item(n: int) -> str:
    return f"910000000000{n}"


def _voucher(item: str, start: date, days: int, value: int) -> sp.VoucherSpec:
    return sp.VoucherSpec(
        kind="voucher", scope="product", item_ids=[item], discount_type="amount", value=value,
        min_spend=60_000, usage_limit=50, start=start, end=start + timedelta(days=days - 1),
    )  # fmt: skip


async def _seed_plans(session, shop_id: uuid.UUID, end: date, now: datetime) -> None:
    """One executed plan (3 vouchers: 5/11 -> 14 days, 12/11 -> 19 days, 16/11 -> 15 days, plus
    the engine's sent title card) and one draft (a voucher from 20/11 and the sent cover card)."""
    shop = await session.get(Shop, shop_id)
    actor, staff = (
        manual.Actor("seller", shop.user_id),
        manual.Actor("staff", shop.user_id, shop.user_id),
    )
    first = end.replace(day=1)

    async def add_spec(spec: sp.VersionSpec) -> None:
        saved = await builder.choose(
            session, shop_id, [spec], 0, primary=False, acknowledge_breaches=True, actor=staff,
            as_of=end, now=now,
        )  # fmt: skip
        await session.commit()
        card = await session.get(ShopProposal, uuid.UUID(saved["id"]))
        card.status = "sent"
        await session.commit()
        await plans.add_card(
            session, shop_id, card.id, actor=actor, now=now, acknowledge_breaches=True
        )

    async def add_sent(kind: str) -> None:
        listed = (
            await service.list_cards(session, shop_id, audience="seller", queue="all", now=now)
        )["cards"]
        card = next(c for c in listed if c["status"] == "sent" and c["change_kind"] == kind)
        await plans.add_card(
            session, shop_id, uuid.UUID(card["id"]), actor=actor, now=now, acknowledge_breaches=True
        )  # fmt: skip

    await add_spec(_voucher(_item(1), first + timedelta(days=4), 14, 15_000))
    await add_spec(_voucher(_item(2), first + timedelta(days=15), 15, 20_000))
    await add_spec(_voucher(_item(3), first + timedelta(days=11), 19, 10_000))
    await add_sent("title")
    await plans.confirm(session, shop_id, actor=actor, now=now, acknowledge_breaches=True)
    plan = await session.scalar(select(ShopRecoPlan).where(ShopRecoPlan.status != PLAN_DRAFT))
    plan.status = PLAN_EXECUTED  # the plan is running (the Connector's fills are out of scope)
    await session.commit()
    await add_spec(_voucher(_item(4), first + timedelta(days=19), 5, 30_000))
    await add_sent("cover_image")


def _verify(tq_data, kh_data, both) -> None:
    """The cross-checks the owner asked for, on the real numbers (raises on a mismatch)."""
    now = tq_data.now
    for key, getter in (("gmv", lambda d: d.gmv), ("orders", lambda d: d.orders)):
        days = tq_data.days
        by_day = (
            [sum(v for v in d.gmv.values() if v) for d in days]
            if key == "gmv"
            else [sum(v for v in d.orders.values() if v) for d in days]
        )
        assert abs(sum(by_day) - getter(now)) < 1e-3 * max(1, abs(getter(now))), key
    for ch in tong_quan_xlsx.CHANNELS:
        assert abs(sum(d.gmv[ch] or 0 for d in tq_data.days) - (now.channel(ch).gmv or 0)) < 1, ch
    assert abs(sum(d.ads_cost or 0 for d in tq_data.days) - (now.ads_cost or 0)) < 1
    print("profit by day vs period:", sum(d.profit or 0 for d in tq_data.days), now.profit)

    def shop_sum(attr: str) -> float:
        return sum(getattr(r.now, attr) or 0 for r in tq_data.products)

    assert (
        abs(shop_sum("gmv") - (now.gmv or 0)) < 1
        and abs(shop_sum("profit") - (now.profit or 0)) < 1
    )
    for attr in ("goal_gmv", "goal_profit", "baseline_gmv", "baseline_profit"):
        got = sum(getattr(r.now, attr) or 0 for r in tq_data.products)
        assert abs(got - (getattr(now, attr) or 0)) < 1e-3, attr
    rows = ke_hoach_xlsx.daily_targets(kh_data)
    for scope, g, p in (
        ("running", "goal_gmv", "goal_profit"),
        ("running+draft", "goal_gmv_draft", "goal_profit_draft"),
    ):
        assert abs(sum(r[g] for r in rows) - both[scope]["goal_gmv"]) < 1, scope
        assert abs(sum(r[p] for r in rows) - both[scope]["goal_profit"]) < 1, scope


def _plain(x):
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x


def _json(obj) -> str:
    return json.dumps(_plain(asdict(obj)), default=str, ensure_ascii=False, indent=1)


async def run(out: Path, end: date) -> dict[str, Path]:
    now = datetime.combine(end, datetime.min.time()) + timedelta(days=1, hours=3)  # 10:00 GMT+7
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": dict.fromkeys(SCHEMAS)},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    report = await loader.load(factory, generate(end), now=now)
    sid = report.shop_id
    out.mkdir(parents=True, exist_ok=True)
    async with factory() as session:
        async with with_shop_scope(session, sid):
            shop = await session.get(Shop, sid)
            name = shop.name if getattr(shop, "name", None) else "Dữ liệu mẫu"
            await _seed_plans(session, sid, end, now)
            tq_data = await collect_tong_quan(session, sid, shop_name=name, now=now)
            kh_data = await collect_ke_hoach(session, sid, shop_name=name, now=now)
            both = await month_plan.month_plans(session, sid, now=now)
            rp = await month_plan.range_plan(
                session, sid, tq_data.start, tq_data.end, scope="running", now=now
            )
    for k in ("baseline_gmv", "goal_gmv", "baseline_profit", "goal_profit"):
        got, want = getattr(tq_data.now, k), rp[k]
        assert (got is None) == (want is None) and (got is None or abs(got - want) < 1), k
    _verify(tq_data, kh_data, both)
    paths: dict[str, Path] = {}
    for data, mod, label in (
        (tq_data, tong_quan_xlsx, "tong_quan"),
        (kh_data, ke_hoach_xlsx, "ke_hoach"),
    ):
        path = out / mod.file_name(data)
        path.write_bytes(mod.build_bytes(data))
        path.with_suffix(".json").write_text(_json(data), encoding="utf-8")
        paths[label] = path
    (out / "month_plan.json").write_text(json.dumps(both, default=str, indent=1), encoding="utf-8")
    await engine.dispose()
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--end-date", default="2026-11-10")
    args = ap.parse_args(argv)
    for label, path in asyncio.run(run(args.out, date.fromisoformat(args.end_date))).items():
        print(label, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
