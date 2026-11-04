"""P91 wave 1b on real Postgres, as ``juli_app`` under RLS: migration 117 (tables, grants, partial
unique indexes, down to 116 and back), the plan code counter, the plan -> executed -> change set
lifecycle with a cut measurement, tenant privacy. Synthetic only."""

from __future__ import annotations

import copy
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_plans import (
    ShopRecoChangeSet,
    ShopRecoPlan,
    ShopRecoPlanCard,
)
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_recommendations import (
    change_sets,
    plan_codes,
    plans,
    product_queue,
    store,
)
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_reco_db import stub_card
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

NOW = datetime(2026, 11, 4, 3, 0)
TABLES = (
    "shop_reco_plans",
    "shop_reco_plan_cards",
    "shop_reco_plan_counters",
    "shop_reco_change_sets",
)


def _draft(sid):
    return ShopRecoPlan(
        id=uuid.uuid4(), shop_id=sid, status="draft", product_windows={}, created_by={},
        created_at=NOW, updated_at=NOW,
    )  # fmt: skip


def _card(item: str, score: float) -> dict:
    card = stub_card(item, "ads_budget")
    card["rank"] = {"position": 1, "score": score}
    card["versions"] = [{"version": 1, "status": "ok", "ranked": True, "label": "x"}]
    return card


async def _approved(session, a, item: str, score: float):
    cid = await store.save_card(
        session, a.shop_id, copy.deepcopy(_card(item, score)), cycle="2026-11", position=1, now=NOW
    )
    await reco.publish(session, a.shop_id, [cid], now=NOW)
    await reco.decide(session, a.shop_id, cid, decision="approve", user_id=a.user_id, now=NOW)
    return cid


def test_migration_117_objects_grants_and_down_to_116_and_back(owner_engine):
    from alembic import command
    from alembic.config import Config

    from tests.integration.test_shopee_reco_p91_db import REPO_ROOT

    with owner_engine.connect() as conn:
        for table in TABLES:
            assert conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE oid =  CAST(:t AS regclass)"),
                {"t": f"public.{table}"},
            ).scalar()
            for verb, want in (
                ("SELECT", True),
                ("INSERT", True),
                ("UPDATE", True),
                ("DELETE", False),
            ):
                assert (
                    conn.execute(
                        text("SELECT has_table_privilege(:r, :t, :v)"),
                        {"r": RUNTIME_ROLE, "t": f"public.{table}", "v": verb},
                    ).scalar()
                    is want
                ), (table, verb)
        idx = {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes"))}
        assert {
            "uq_shop_reco_plans_one_draft",
            "uq_shop_reco_plans_shop_code",
            "uq_shop_reco_plan_cards_open",
            "uq_shop_reco_change_sets_product_day",
            "uq_shop_reco_change_sets_shop_day",
        } <= idx
        check = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_shop_proposals_status'"
            )
        ).scalar()
        assert "planned" in check
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option(
        "sqlalchemy.url", str(owner_engine.url.render_as_string(hide_password=False))
    )
    command.downgrade(cfg, "116_shopee_reco_codes")
    try:
        with owner_engine.connect() as conn:
            for table in TABLES:
                assert conn.execute(
                    text("SELECT to_regclass(:t) IS NULL"), {"t": f"public.{table}"}
                ).scalar()
            assert (
                "planned"
                not in conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'ck_shop_proposals_status'"
                    )
                ).scalar()
            )
    finally:
        command.upgrade(cfg, "head")
    with owner_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.shop_reco_plans') IS NOT NULL")
        ).scalar()


async def test_plan_codes_count_per_shop(shopee_tenants):
    a, b = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            first = await plan_codes.assign_plan_code(session, a.shop_id, NOW)
            second = await plan_codes.assign_plan_code(session, a.shop_id, NOW)
            await session.commit()
        async with with_shop_scope(session, b.shop_id):
            other = await plan_codes.assign_plan_code(session, b.shop_id, NOW)
            await session.commit()
    assert (first, second, other) == ("KH-2611-001", "KH-2611-002", "KH-2611-001")


async def test_plan_lifecycle_to_executed_and_a_cut_measurement_under_rls(shopee_tenants):
    a, b = shopee_tenants
    sid = a.shop_id
    async with juli_app_session() as session:
        async with with_shop_scope(session, sid):
            c1 = await _approved(session, a, "8801", 0.9)
            c2 = await _approved(session, a, "8801", 0.8)
            plan = ShopRecoPlan(
                id=uuid.uuid4(), shop_id=sid, status="confirmed", code="KH-2611-901",
                planned_date=date(2026, 11, 4), window_days=14, product_windows={},
                created_by={}, aggregate={}, created_at=NOW, updated_at=NOW,
            )  # fmt: skip
            session.add(plan)
            await session.flush()
            for n, cid in enumerate((c1, c2)):
                p = await session.get(ShopProposal, cid)
                p.lever_plan_id = plan.id
                session.add(
                    ShopRecoPlanCard(
                        id=uuid.uuid4(), shop_id=sid, plan_id=plan.id, proposal_id=cid,
                        chosen_version=1, inputs={}, prior_status="sent", position=n,
                        added_by={}, added_at=NOW,
                    )
                )  # fmt: skip
            await session.commit()
        async with with_shop_scope(session, sid):
            r1 = await reco.mark_executed(
                session, sid, c1, now=NOW + timedelta(hours=1), user_id=a.user_id
            )
            assert r1["plan_executed"] is False and r1["plan_code"] == "KH-2611-901"
            r2 = await reco.mark_executed(
                session, sid, c2, now=NOW + timedelta(hours=2), user_id=a.user_id
            )
            assert r2["plan_executed"] is True
            assert r2["change_set"]["id"] == r1["change_set"]["id"]
            assert r2["change_set"]["n_cards"] == 2 and r2["change_set"]["window_days"] == 14
            await session.commit()
        async with with_shop_scope(session, sid):
            assert (await session.get(ShopRecoPlan, plan.id)).status == "executed"
            # a partial unique index: one product set per day
            dup = ShopRecoChangeSet(
                id=uuid.uuid4(), shop_id=sid, scope="product", product_id="8801",
                executed_on=NOW.date(), started_at=NOW, card_ids=[], window_days=7,
                created_at=NOW, updated_at=NOW,
            )  # fmt: skip
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(dup)
                    await session.flush()
            # a second draft is refused, a shop-wide set on the same day is allowed
            session.add(_draft(sid))
            await session.flush()
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(_draft(sid))
                    await session.flush()
            await session.rollback()
        # executing again on the product 4 days later cuts the running set: kept, 4 days
        async with with_shop_scope(session, sid):
            c3 = await _approved(session, a, "8801", 0.7)
            later = NOW + timedelta(days=4, hours=1)
            preview = await change_sets.cut_preview(session, sid, ["8801"], later.date())
            assert preview[0]["days_measured"] == 4 and preview[0]["state"] == "kept_partial"
            await reco.mark_executed(session, sid, c3, now=later, user_id=a.user_id)
            await session.commit()
        async with with_shop_scope(session, sid):
            first, second = [s for s in await change_sets.sets_for(session, sid) if s.product_id]
            assert first.status == "cut" and first.result["label"] == "Đo được 4 ngày"
            assert second.status == "measuring" and second.executed_on == later.date()
            m = await product_queue.measuring(session, sid, later + timedelta(days=1))
            assert m["8801"]["change_set"] == str(second.id)
        # tenant privacy: the other shop sees none of it
        async with with_shop_scope(session, b.shop_id):
            assert (await session.scalars(select(ShopRecoPlan))).all() == []
            assert (await session.scalars(select(ShopRecoChangeSet))).all() == []
            assert (await session.scalars(select(ShopRecoPlanCard))).all() == []
            with pytest.raises(Exception):
                await plans.get_plan_row(session, b.shop_id, plan.id)
