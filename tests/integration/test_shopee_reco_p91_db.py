"""P91 on real Postgres, as ``juli_app`` under RLS: migration 116 (columns, counter table, grants,
down to 115 and back), every card persisted with a per-product queue that renumbers on each close
path, card codes unique under concurrency, the backfill in ``created_at`` order. Synthetic only."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_recommendations import codes, product_queue, store
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_reco_db import NOW, stub_card
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
MIG_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/116_shopee_reco_codes.py"
)


def _mig():
    spec = importlib.util.spec_from_file_location("mig116_db", MIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIG = _mig()


def card_for(item: str, score: float, kind: str = "ads_budget") -> dict:
    card = stub_card(item, kind)
    card["rank"] = {"position": 1, "score": score}
    card["versions"] = [{"version": 1, "status": "ok", "ranked": True, "label": "x"}]
    return card


async def save(session, shop_id, card, **kw):
    return await store.save_card(
        session, shop_id, copy.deepcopy(card), cycle="2026-11", position=1, now=NOW, **kw
    )


async def queue_of(session, ids):
    rows = (await session.scalars(select(ShopProposal).where(ShopProposal.id.in_(ids)))).all()
    by = {p.id: p.product_queue for p in rows}
    return [by[i] for i in ids]


async def test_all_cards_of_a_product_persist_and_the_queue_renumbers_on_every_close_path(
    shopee_tenants,
):
    a, _ = shopee_tenants
    sid = a.shop_id
    async with juli_app_session() as session:
        async with with_shop_scope(session, sid):
            ids = [await save(session, sid, card_for("7001", 1.0 - n / 10)) for n in range(5)]
            other = await save(session, sid, card_for("7002", 0.5))
            await product_queue.requeue_products(session, sid, ["7001", "7002"], NOW)
            assert await queue_of(session, ids) == [1, 2, 3, 4, 5]
            assert await queue_of(session, [other]) == [1]
            await reco.publish(session, sid, ids, now=NOW)
            # dismissed
            await reco.decide(session, sid, ids[0], decision="dismiss", user_id=a.user_id, now=NOW)
            assert await queue_of(session, ids) == [None, 1, 2, 3, 4]
            # withdrawn (Ops)
            await reco.withdraw(session, sid, ids[1], now=NOW)
            assert await queue_of(session, ids) == [None, None, 1, 2, 3]
            # executed closes at once
            await reco.decide(session, sid, ids[2], decision="approve", user_id=a.user_id, now=NOW)
            assert await queue_of(session, ids) == [None, None, 1, 2, 3]  # approved keeps the head
            await reco.mark_executed(
                session, sid, ids[2], now=NOW + timedelta(hours=1), user_id=a.user_id
            )
            assert await queue_of(session, ids) == [None, None, None, 1, 2]
            # expired
            assert await reco.expire_old(session, sid, now=NOW + timedelta(days=9)) == 2
            assert await queue_of(session, ids) == [None] * 5
            assert await queue_of(session, [other]) == [1]  # another product, untouched
            await session.commit()
        async with with_shop_scope(session, sid):
            assert await reco.requeue(session, sid, now=NOW + timedelta(days=30)) == 0  # idempotent


async def test_default_list_shows_the_head_and_a_product_filter_shows_all(shopee_tenants):
    a, _ = shopee_tenants
    sid = a.shop_id
    async with juli_app_session() as session:
        async with with_shop_scope(session, sid):
            ids = [await save(session, sid, card_for("7101", 0.9 - n / 10)) for n in range(3)]
            await product_queue.requeue_products(session, sid, ["7101"], NOW)
            await reco.publish(session, sid, ids, now=NOW)
            top = await reco.list_cards(session, sid, audience="seller", now=NOW)
            mine = [c for c in top["cards"] if c["product_id"] == "7101"]
            assert [c["id"] for c in mine] == [str(ids[0])]
            full = await reco.list_cards(
                session, sid, audience="seller", product_id="7101", now=NOW
            )
            assert [c["product_queue"] for c in full["cards"]] == [1, 2, 3]
            assert all(c["code"] for c in full["cards"])


async def test_codes_stay_unique_and_gapless_under_concurrent_writers(shopee_tenants):
    a, _ = shopee_tenants
    sid = a.shop_id

    async def writer(n: int) -> list[str]:
        out = []
        async with juli_app_session() as session:
            async with with_shop_scope(session, sid):
                for k in range(3):
                    cid = await save(session, sid, card_for(f"72{n}{k}", 0.1))
                    out.append((await session.get(ShopProposal, cid)).code)
                await session.commit()
        return out

    results = await asyncio.gather(*(writer(n) for n in range(5)))
    got = sorted(c for r in results for c in r)
    assert len(got) == 15 == len(set(got))
    seqs = sorted(int(c.rsplit("-", 1)[1]) for c in got)
    assert seqs == list(range(seqs[0], seqs[0] + 15))
    async with juli_app_session() as session:
        async with with_shop_scope(session, sid):
            last = (
                await session.execute(
                    text("SELECT last_seq FROM shop_proposal_code_counters WHERE shop_id = :s"),
                    {"s": sid},
                )
            ).scalar()
            assert last >= seqs[-1]


async def test_the_backfill_codes_old_cards_in_created_at_order_and_is_private(shopee_tenants):
    a, b = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            ids = [await save(session, a.shop_id, card_for(f"73{n}", 0.1)) for n in range(3)]
            for n, i in enumerate(ids):
                await session.execute(
                    text("UPDATE shop_proposals SET code = NULL, created_at = :t WHERE id = :i"),
                    {"t": NOW - timedelta(days=30 - n), "i": i},
                )
            # reverse the insert order: the backfill must follow created_at, not insertion
            await session.execute(
                text("UPDATE shop_proposals SET created_at = :t WHERE id = :i"),
                {"t": NOW - timedelta(days=90), "i": ids[2]},
            )
            session.expire_all()
            assert await codes.backfill_codes(session, a.shop_id, NOW) == 3
            assert await codes.backfill_codes(session, a.shop_id, NOW) == 0
            rows = [await session.get(ShopProposal, i) for i in ids]
            seq = [int(r.code.rsplit("-", 1)[1]) for r in rows]
            assert seq[2] < seq[0] < seq[1] and max(seq) - min(seq) == 2
            assert rows[2].code.startswith("JC-2608-")
            await session.commit()
        async with with_shop_scope(session, b.shop_id):
            assert await codes.backfill_codes(session, b.shop_id, NOW) == 0
            with pytest.raises(Exception):  # another shop's proposal is not visible by code
                await reco.card_by_code(session, b.shop_id, rows[0].code)


def test_migration_116_objects_grants_and_down_to_115_and_back(owner_engine):
    from alembic import command
    from alembic.config import Config

    assert MIG.revision == "116_shopee_reco_codes" and len(MIG.revision) <= 32
    assert MIG.down_revision == "115_shopee_recommendations"
    with owner_engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.shop_proposal_code_counters'::regclass"
            )
        ).scalar()
        for verb, want in (("SELECT", True), ("INSERT", True), ("UPDATE", True), ("DELETE", False)):
            assert (
                conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :v)"),
                    {"r": RUNTIME_ROLE, "t": "public.shop_proposal_code_counters", "v": verb},
                ).scalar()
                is want
            ), verb
        idx = {
            r[0]
            for r in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'shop_proposals'")
            )
        }
        assert {MIG.CODE_INDEX, MIG.QUEUE_INDEX} <= idx

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option(
        "sqlalchemy.url", str(owner_engine.url.render_as_string(hide_password=False))
    )

    def columns() -> set[str]:
        with owner_engine.connect() as conn:
            return {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'shop_proposals'"
                    )
                )
            }

    command.downgrade(cfg, "115_shopee_recommendations")
    try:
        assert not {"code", "product_queue"} & columns()
        with owner_engine.connect() as conn:
            assert conn.execute(
                text("SELECT to_regclass('public.shop_proposal_code_counters') IS NULL")
            ).scalar()
    finally:
        command.upgrade(cfg, "head")
    assert {"code", "product_queue"} <= columns()
