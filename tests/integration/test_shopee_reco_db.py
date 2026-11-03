"""ADR-121 / migration 115 on real Postgres, as ``juli_app`` under RLS: a card (action card +
proposal + frozen `proposed` event under one id), its decision cycle and `executed` event with
`change`, the simulation prior runs and the calibration rows are tenant-private; the two new
tables have the migration's grants and policies. Synthetic tenants and figures only."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.card_events import CardEvent
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.card_events.verification import pending_changes
from juli_backend.services.shopee_recommendations import learning, store
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_orders_db import shopee_tenants  # noqa: F401 (fixture)
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

NOW = datetime(2026, 11, 4, 3, 0)
REPO_ROOT = Path(__file__).resolve().parents[2]
MIG_PATH = (
    REPO_ROOT
    / "backend/src/juli_backend/database/migrations/versions/115_shopee_recommendations.py"
)


def _mig():
    spec = importlib.util.spec_from_file_location("mig115_db", MIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIG = _mig()


def stub_card(item: str = "1001", kind: str = "ads_budget", family: str = "ads") -> dict:
    """The parts of a card the persistence and the decision cycle read (no shop data needed)."""
    money = {
        "days": 30,
        "certain": {"dgmv": 0.0, "dprofit": -1000.0, "dchi": 1000.0},
        "predicted": {
            q: {"dgmv": 10.0, "dorders": 1.0, "dprofit": 5.0}
            for q in ("p10", "p25", "p50", "p75", "p90")
        },
        "total": {
            q: {"dgmv": 10.0, "dorders": 1.0, "dprofit": 5.0}
            for q in ("p10", "p25", "p50", "p75", "p90")
        },
    }
    inputs = {"daily_budget": 120_000}
    return {
        "family": family,
        "family_label": "x",
        "change_kind": kind,
        "title": "Thẻ thử",
        "reason": "lý do",
        "metric": {"key": "ads_gmv"},
        "wiring_key": "views",
        "bundle": False,
        "scope": {
            "level": "campaign",
            "product_ids": [item] if item else [],
            "sku_ids": ["K"],
            "campaign_key": "c1",
        },
        "change": {
            "change_kind": kind,
            "target": {"campaign_id": "8001"},
            "before": {"daily_budget": 100_000},
            "after": {"daily_budget": 120_000},
        },
        "inputs": inputs,
        "predicted": {"money_per_month": money, "lift": {"lift": {"p10": 0.0, "p90": 0.1}}},
        "floor": {"ok": True, "breaches": []},
        "measurement_plan": {"planned_days": 14, "label": "Kết quả sau 14 ngày"},
        "execution_sheet": {
            "changes": [
                {
                    "change_kind": "daily_budget",
                    "target": {"campaign_id": "8001"},
                    "expected": {"daily_budget": 120_000},
                }
            ]
        },
        "certain": {},
        "five_numbers": None,
        "rank": {"position": 1, "score": 0.1},
        "rank_inputs": {
            "kpi_p25": {},
            "dgmv_p25": 1.0,
            "dprofit_p50": 1.0,
            "floor_breach": False,
            "spend_after": 1.0,
            "spend_cap": None,
            "in_stock": True,
            "kg_value": None,
            "items": [item],
        },
    }


async def _save(session, shop_id, card=None, **kw):
    return await store.save_card(
        session, shop_id, card or stub_card(), cycle="2026-11", position=1, now=NOW, **kw
    )


async def test_a_card_is_three_rows_under_one_id_and_private_to_its_shop(shopee_tenants):  # noqa: F811
    a, b = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            cid = await _save(session, a.shop_id)
            await session.commit()
        async with with_shop_scope(session, a.shop_id):
            rows = await store.list_cards(session, a.shop_id)
            ((p, card),) = [r for r in rows if r[0].id == cid]
            assert p.status == "draft" and card["change_kind"] == "ads_budget"
            ev = (await session.scalars(select(CardEvent).where(CardEvent.card_id == cid))).all()
            assert [e.event_type for e in ev] == ["proposed"] and ev[0].payload["inputs"] == {
                "daily_budget": 120_000
            }
        async with with_shop_scope(session, b.shop_id):
            assert [r for r in await store.list_cards(session, b.shop_id) if r[0].id == cid] == []
            assert await store.card_payload(session, b.shop_id, cid) is None
            assert (
                await session.execute(
                    text("SELECT count(*) FROM public.action_cards WHERE id = :i"), {"i": cid}
                )
            ).scalar() == 0
    async with juli_app_session() as session:
        async with with_shop_scope(session, b.shop_id):
            with pytest.raises(DBAPIError):  # a card for another shop is refused by the policy
                await _save(session, a.shop_id)
                await session.commit()


async def test_the_decision_cycle_and_the_executed_change_on_postgres(shopee_tenants):  # noqa: F811
    a, _ = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            cid = await _save(session, a.shop_id, stub_card("2002"))
            assert await reco.publish(session, a.shop_id, [cid], now=NOW) == [str(cid)]
            out = await reco.decide(
                session, a.shop_id, cid, decision="approve", user_id=a.user_id, now=NOW
            )
            assert out["status"] == "approved"
            done = await reco.mark_executed(
                session,
                a.shop_id,
                cid,
                now=NOW + timedelta(hours=1),
                executed_at=NOW + timedelta(hours=1),
                user_id=a.user_id,
            )
            assert done["events"] == 1
            await session.commit()
        async with with_shop_scope(session, a.shop_id):
            types = [
                e.event_type
                for e in (
                    await session.scalars(
                        select(CardEvent)
                        .where(CardEvent.card_id == cid)
                        .order_by(CardEvent.occurred_at)
                    )
                ).all()
            ]
            assert types == ["proposed", "accepted", "executed"]
            pend = await pending_changes(session, a.shop_id, NOW + timedelta(hours=2))
            mine = [c for c in pend if c.card_id == cid]
            assert [(c.change_kind, c.expected) for c in mine] == [
                ("daily_budget", {"daily_budget": 120_000})
            ]
            # the product is held while the plan runs, and released after it
            held = await store.locked_products(session, a.shop_id, NOW + timedelta(days=1))
            assert "2002" in held
            assert "2002" not in await store.locked_products(
                session, a.shop_id, NOW + timedelta(days=20)
            )
            # a decided card is not decided twice
            with pytest.raises(Exception, match="cannot move"):
                await reco.decide(
                    session, a.shop_id, cid, decision="dismiss", user_id=a.user_id, now=NOW
                )


async def test_dismiss_reason_is_required_by_the_event_check_and_stored(shopee_tenants):  # noqa: F811
    a, _ = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            cid = await _save(session, a.shop_id, stub_card("3003"))
            await reco.publish(session, a.shop_id, [cid], now=NOW)
            await reco.decide(
                session,
                a.shop_id,
                cid,
                decision="dismiss",
                user_id=a.user_id,
                now=NOW,
                reason_code="already_done",
            )
            await session.commit()
        async with with_shop_scope(session, a.shop_id):
            (ev,) = (
                await session.scalars(
                    select(CardEvent).where(
                        CardEvent.card_id == cid, CardEvent.event_type == "dismissed"
                    )
                )
            ).all()
            assert ev.reason_code == "already_done"
            stats = await store.load_acceptance(session, a.shop_id)
            assert (
                stats.dismissed["ads_budget"] >= 1
                and stats.reasons["ads_budget"]["already_done"] >= 1
            )


async def test_stale_marking_on_postgres(shopee_tenants):  # noqa: F811
    a, _ = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            cid = await _save(session, a.shop_id, stub_card("4004"))
            await reco.publish(session, a.shop_id, [cid], now=NOW)
            assert await reco.mark_stale_for(session, a.shop_id, product_ids=["4004"]) == 1
            assert (await store.card_meta(session, a.shop_id, cid))["stale"] is True
            await session.commit()


def _doc(run="run-pg"):
    return {
        "format": "juli-sim/priors/v1",
        "run_id": run,
        "platform": "shopee",
        "shop_alias": "alias",
        "gate": {"title": {"weight": 0.0, "status": "fail"}},
        "rows": [
            {
                "product_id": "1",
                "change_kind": "title",
                "variant": "v",
                "segment": "all",
                "metric": "ctr",
                "med": 0.01,
                "lo90": -0.1,
                "hi90": 0.2,
                "kg_value": None,
                "eligible": False,
            }
        ],
    }


async def test_sim_runs_and_calibration_are_tenant_private(shopee_tenants):  # noqa: F811
    a, b = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            await reco.save_sim(
                session,
                a.shop_id,
                reco.parse_priors(_doc("one")),
                sha256="0" * 64,
                staff_id=None,
                now=NOW,
            )
            await reco.save_sim(
                session,
                a.shop_id,
                reco.parse_priors(_doc("two")),
                sha256="1" * 64,
                staff_id=None,
                now=NOW,
            )
            obs = [
                learning.Observation("title", "ctr", 0.0, 0.1, 0.05, None, "natural", False, "x")
            ]
            await store.save_calibrations(session, a.shop_id, learning.calibrate(obs), obs, now=NOW)
            await session.commit()
        async with with_shop_scope(session, a.shop_id):
            assert (
                await store.load_sim(session, a.shop_id)
            ).run_id == "two"  # the newer run is active
            n = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM public.shopee_sim_prior_runs WHERE status = 'superseded'"  # noqa: E501
                    )
                )
            ).scalar()
            assert n == 1
            assert (await store.load_calibrations(session, a.shop_id))[
                ("title", "ctr")
            ].n_results == 1
            # importing the same run again replaces it: still one row per run id, and active
            again = await reco.save_sim(
                session,
                a.shop_id,
                reco.parse_priors(_doc("two")),
                sha256="2" * 64,
                staff_id=None,
                now=NOW,
            )
            n = (
                await session.execute(
                    text("SELECT count(*) FROM public.shopee_sim_prior_runs WHERE run_id = 'two'")
                )
            ).scalar()
            assert n == 1 and again.source_sha256 == "2" * 64 and again.status == "active"
            assert (await store.load_sim(session, a.shop_id)).run_id == "two"
        async with with_shop_scope(session, b.shop_id):
            assert await store.load_sim(session, b.shop_id) is None
            assert await store.load_calibrations(session, b.shop_id) == {}
            assert await store.load_observations(session, b.shop_id) == []


def test_the_new_tables_have_rls_the_migrations_grants_and_no_delete(owner_engine):
    verbs = ("SELECT", "INSERT", "UPDATE", "DELETE")
    with owner_engine.connect() as conn:
        for table in MIG.TENANT_TABLES:
            assert (
                conn.execute(
                    text("SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:t AS regclass)"),
                    {"t": f"public.{table}"},
                ).scalar()
                is True
            )
            granted = {
                v
                for v in verbs
                if conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :v)"),
                    {"r": RUNTIME_ROLE, "t": f"public.{table}", "v": v},
                ).scalar()
            }
            assert granted == {"SELECT", "INSERT", "UPDATE"}, table
            pols = {
                r[0]
                for r in conn.execute(
                    text("SELECT cmd FROM pg_policies WHERE tablename = :t"), {"t": table}
                )
            }
            assert pols == {"SELECT", "INSERT", "UPDATE"}, table
        assert MIG.revision == "115_shopee_recommendations" and len(MIG.revision) <= 32
        assert MIG.down_revision == "114_card_verification_events"


def test_the_migration_goes_down_and_up(owner_engine):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option(
        "sqlalchemy.url", str(owner_engine.url.render_as_string(hide_password=False))
    )

    def exists(table):
        with owner_engine.connect() as conn:
            return conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
            ).scalar()

    command.downgrade(cfg, "114_card_verification_events")
    try:
        assert not any(exists(t) for t in MIG.TENANT_TABLES)
    finally:
        command.upgrade(cfg, "head")
    assert all(exists(t) for t in MIG.TENANT_TABLES)


def test_json_helpers_are_plain():
    assert json.loads(json.dumps(stub_card()))["family"] == "ads"
    assert uuid.UUID(str(uuid.uuid4()))
