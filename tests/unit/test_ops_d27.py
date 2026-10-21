"""P18 Juli Ops speed + audit (DECISIONS D27), SQLite.

- D27.1 overview from ``ops_shop_daily_summary`` + "Làm mới" endpoints (roles, audit)
- D27.2 compact daily tables: write, simulation read, refresh
- D27.4 audit retention (kinds, nightly task)
- D27.6 audit merging (merge, revert deletes, multi-key one row)
- ``GET /v1/ops/audit?kind=``
- migration 085 shape
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.api.routes.ops import get_ops_user
from juli_backend.core.security import get_current_user
from juli_backend.models.models import Shop, User
from juli_backend.models.ops import OpsAuditLog, OpsShopDailySummary, OpsStaff
from juli_backend.models.shop_diagnosis import (
    ShopDailyProduct,
    ShopDailyStream,
    ShopDiagnosisReport,
)
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops import simulation as sim
from juli_backend.services.shop_diagnosis_daily import compact
from tests.support.api import build_app, client_for
from tests.support.builders import make_tenant, make_user

REPO = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPO / "backend/src/juli_backend/database/migrations/versions/085_ops_daily_precompute.py"
)
END = date(2026, 10, 9)


@pytest.fixture(autouse=True)
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


async def _staff(session, role: str, email: str | None = None) -> User:
    email = email or f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    return user


def _client_as(session, user: User):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current

    app.dependency_overrides[get_ops_user] = current
    return client_for(app)


def _report(days: int = 60, *, end: date = END, imp: float = 1000.0, products: bool = True) -> dict:
    streams = {
        s: {(end - timedelta(days=i)).isoformat(): [imp, 50, 5, 750_000] for i in range(days)}
        for s in sim.STREAMS
    }
    daily_products = (
        {
            "product_card": {
                pid: {
                    (end - timedelta(days=i)).isoformat(): [100 + 10 * n + (i % 3), 5, 1, 9000]
                    for i in range(days)
                }
                for n, pid in enumerate(("p1", "p2"))
            }
        }
        if products
        else {}
    )
    return {
        "daily_streams": streams,
        "daily_products": daily_products,
        "titles": {"p1": "Áo thun", "p2": "Quần"},
        "seller_skus": {"p1": "SKU-1"},
    }


def _stored(shop: Shop, report: dict, *, end: date = END) -> ShopDiagnosisReport:
    return ShopDiagnosisReport(
        shop_id=shop.id, end_date=end, ranking="60d", report=report, built_at=datetime(2026, 10, 10)
    )


async def _count(session, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for key, value in where.items():
        stmt = stmt.where(getattr(model, key) == value)
    return int((await session.execute(stmt)).scalar_one())


# -- D27.2 compact tables -------------------------------------------------------------


async def test_compact_write_then_simulation_reads_the_same_payload(session):
    _, shop = await make_tenant(session)
    report = _report()
    written = await compact.write_report_days(session, shop.id, [report])
    assert written == 4 * 60 + 2 * 60
    assert await _count(session, ShopDailyStream, shop_id=shop.id) == 240
    history = await sim.load_history(session, shop.id, today=END + timedelta(days=1))
    from_table = sim.baseline(history, 30)
    from_json = sim.baseline(sim.merge_reports([report]), 30)
    for key in ("streams", "volatility", "windows", "status", "from", "to"):
        assert from_table[key] == from_json[key], key
    rows = from_table["volatility"]["product_card"]["rows"]
    assert {r["name"] for r in rows} == {"SKU-1 Áo thun", "Quần"}
    assert from_table["data_through"] == END.isoformat()
    assert from_table["generated_at"] is not None


async def test_compact_upsert_newer_wins_and_history_grows(session):
    _, shop = await make_tenant(session)
    await compact.write_report_days(session, shop.id, [_report(10, end=END - timedelta(days=5))])
    await compact.write_report_days(session, shop.id, [_report(10, imp=2000.0, products=False)])
    rows = (
        (await session.execute(select(ShopDailyStream).where(ShopDailyStream.stream == "shop_tab")))
        .scalars()
        .all()
    )
    by_day = {r.day: float(r.impressions) for r in rows}
    assert len(by_day) == 15  # 10 + 10 with a 5-day overlap
    assert by_day[END] == 2000.0 and by_day[END - timedelta(days=9)] == 2000.0
    assert by_day[END - timedelta(days=14)] == 1000.0
    assert await _count(session, ShopDailyProduct, shop_id=shop.id) == 2 * 10


async def test_compact_reads_only_the_scoped_shop(session):
    _, a = await make_tenant(session)
    _, b = await make_tenant(session)
    await compact.write_report_days(session, a.id, [_report(10)])
    history = await sim.load_history(session, b.id, today=END)
    assert history.days_available == 0


# -- simulation endpoints ----------------------------------------------------------------


async def test_simulation_get_fills_compact_rows_once_from_stored_reports(session, monkeypatch):
    monkeypatch.setattr(sim, "HISTORY_DAYS", 100_000)
    _, shop = await make_tenant(session)
    session.add(_stored(shop, _report()))
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        body = (await client.get(f"/v1/ops/shops/{shop.id}/simulation?window=30")).json()
    assert body["status"]["baseline_available"] is True and body["rebuilding"] is False
    assert body["data_through"] == END.isoformat() and body["generated_at"]
    assert await _count(session, ShopDailyStream, shop_id=shop.id) == 240


@pytest.mark.parametrize(("role", "status"), [("viewer", 403), ("operator", 200), ("admin", 200)])
async def test_simulation_refresh_roles_rebuild_and_audit(session, monkeypatch, role, status):
    monkeypatch.setattr(sim, "HISTORY_DAYS", 100_000)
    _, shop = await make_tenant(session)
    session.add(_stored(shop, _report(20)))
    user = await _staff(session, role)
    async with _client_as(session, user) as client:
        response = await client.post(f"/v1/ops/shops/{shop.id}/simulation/refresh?window=7")
    assert response.status_code == status, response.text
    if status != 200:
        assert await _count(session, ShopDailyStream, shop_id=shop.id) == 0
        return
    body = response.json()
    assert body["window"] == 7 and len(body["streams"]) == 4
    assert body["data_through"] == END.isoformat() and body["generated_at"]
    assert "scenarios" in body and body["rebuilding"] is False
    assert await _count(session, ShopDailyStream, shop_id=shop.id) == 80
    assert await _count(session, OpsShopDailySummary, shop_id=shop.id) == 1
    row = (
        (await session.execute(select(OpsAuditLog).where(OpsAuditLog.action == "data_refresh")))
        .scalars()
        .one()
    )
    assert row.shop_id == shop.id and audit.kind_of(row.action) == "view"
    assert row.after == {"target": "simulation", "window": 7}


async def test_simulation_refresh_refuses_an_unknown_window(session):
    _, shop = await make_tenant(session)
    user = await _staff(session, "operator")
    async with _client_as(session, user) as client:
        response = await client.post(f"/v1/ops/shops/{shop.id}/simulation/refresh?window=60")
    assert response.status_code == 422


# -- D27.1 overview from the daily summary -------------------------------------------------


async def test_overview_stores_missing_summaries_then_reads_them(session):
    _, shop = await make_tenant(session)
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        first = (await client.get("/v1/ops/overview")).json()
        assert await _count(session, OpsShopDailySummary, shop_id=shop.id) == 1
        # The stored row is what the next GET shows (no live recompute).
        summary = await session.get(OpsShopDailySummary, shop.id)
        summary.payload = {**summary.payload, "failed_runs_30d": 42}
        summary.data_through = END
        await session.commit()
        second = (await client.get("/v1/ops/overview")).json()
    row = next(r for r in second["shops"] if r["shop_id"] == str(shop.id))
    assert row["failed_runs_30d"] == 42
    assert row["data_through"] == END.isoformat() and row["generated_at"]
    assert first["generated_at"] and "data_through" in first
    assert second["generated_at"] <= datetime.now().isoformat()


@pytest.mark.parametrize(("role", "status"), [("viewer", 403), ("operator", 200)])
async def test_overview_refresh_recomputes_every_shop(session, role, status):
    _, shop = await make_tenant(session)
    session.add(
        OpsShopDailySummary(
            shop_id=shop.id,
            payload={"connection": "none", "failed_runs_30d": 42},
            data_through=None,
            generated_at=datetime(2026, 1, 1),
        )
    )
    await session.commit()
    user = await _staff(session, role)
    async with _client_as(session, user) as client:
        response = await client.post("/v1/ops/overview/refresh")
    assert response.status_code == status, response.text
    if status != 200:
        return
    body = response.json()
    row = next(r for r in body["shops"] if r["shop_id"] == str(shop.id))
    assert row["failed_runs_30d"] == 0
    assert body["generated_at"] > "2026-01-01T00:00:00"
    assert set(body) >= {"generated_at", "data_through", "totals", "shops"}
    entries = await audit.list_entries(session, kind="view")
    assert [e.action for e in entries] == ["data_refresh"] and entries[0].shop_id is None


async def test_find_shop_returns_one_listing_or_none(session):
    from juli_backend.services.ops import overview

    _, shop = await make_tenant(session)
    found = await overview.find_shop(session, shop.id)
    assert found is not None and found.shop_id == shop.id
    assert await overview.find_shop(session, uuid.uuid4()) is None


# -- D27.6 audit merging -----------------------------------------------------------------


async def _actor(session) -> audit.Actor:
    staff = OpsStaff(
        id=uuid.uuid4(), email=f"op-{uuid.uuid4().hex[:6]}@app-juli.com", role="operator"
    )
    session.add(staff)
    await session.flush()
    return audit.Actor(staff_id=staff.id, email=staff.email)


async def test_same_field_within_ten_minutes_merges_into_one_row(session):
    _, shop = await make_tenant(session)
    actor = await _actor(session)
    t0 = utc_now_naive()
    kwargs = {"shop_id": shop.id, "field": "card_daily_limit"}
    first = await audit.record(
        session,
        actor,
        "settings_update",
        before={"card_daily_limit": None},
        after={"card_daily_limit": 3},
        at=t0,
        **kwargs,
    )
    merged = await audit.record(
        session,
        actor,
        "settings_update",
        before={"card_daily_limit": 3},
        after={"card_daily_limit": 7},
        at=t0 + timedelta(minutes=9),
        **kwargs,
    )
    assert merged is first
    rows = (await session.execute(select(OpsAuditLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.before == {"card_daily_limit": None} and row.after == {"card_daily_limit": 7}
    assert row.merged_count == 2 and row.at == t0 + timedelta(minutes=9)
    # Ten minutes after the LAST edit is a new row.
    await audit.record(
        session,
        actor,
        "settings_update",
        before={"card_daily_limit": 7},
        after={"card_daily_limit": 8},
        at=t0 + timedelta(minutes=20),
        **kwargs,
    )
    assert await _count(session, OpsAuditLog) == 2


async def test_reverting_to_the_original_value_deletes_the_row(session):
    _, shop = await make_tenant(session)
    actor = await _actor(session)
    t0 = utc_now_naive()
    kwargs = {"shop_id": shop.id, "field": "stage"}
    await audit.record(
        session,
        actor,
        "settings_update",
        before={"stage": "trial"},
        after={"stage": "pilot"},
        at=t0,
        **kwargs,
    )
    gone = await audit.record(
        session,
        actor,
        "settings_update",
        before={"stage": "pilot"},
        after={"stage": "trial"},
        at=t0 + timedelta(minutes=2),
        **kwargs,
    )
    await session.flush()
    assert gone is None
    assert await _count(session, OpsAuditLog) == 0


async def test_no_merge_across_actor_shop_field_or_kind(session):
    _, shop = await make_tenant(session)
    _, other = await make_tenant(session)
    a, b = await _actor(session), await _actor(session)
    t0 = utc_now_naive()

    async def rec(actor, shop_id, field, action="settings_update"):
        await audit.record(
            session,
            actor,
            action,
            shop_id=shop_id,
            before={field: 1},
            after={field: 2},
            at=t0,
            field=field,
        )

    await rec(a, shop.id, "card_daily_limit")
    await rec(b, shop.id, "card_daily_limit")
    await rec(a, other.id, "card_daily_limit")
    await rec(a, shop.id, "card_open_limit")
    await rec(a, shop.id, "card_daily_limit", action="settings_reset")
    await audit.record(session, a, "view_as_view", shop_id=shop.id, after={"mode": "view"}, at=t0)
    await audit.record(session, a, "view_as_view", shop_id=shop.id, after={"mode": "view"}, at=t0)
    assert await _count(session, OpsAuditLog) == 7


async def test_settings_put_single_key_merges_and_multi_key_is_one_row(session):
    _, shop = await make_tenant(session)
    user = await _staff(session, "operator", "merge@app-juli.com")
    url = f"/v1/ops/shops/{shop.id}/settings"
    async with _client_as(session, user) as client:
        for value in (3, 4, 6):
            assert (
                await client.put(url, json={"changes": {"card_daily_limit": value}})
            ).status_code == 200
        multi = await client.put(
            url,
            json={"changes": {"enabled_streams": ["product_card"], "content_cards_enabled": False}},
        )
        assert multi.status_code == 200
        # Same value again: nothing changed, nothing logged.
        assert (await client.put(url, json={"changes": {"card_daily_limit": 6}})).status_code == 200
    rows = (await session.execute(select(OpsAuditLog).order_by(OpsAuditLog.at))).scalars().all()
    assert len(rows) == 2
    single, several = rows
    assert single.field == "card_daily_limit" and single.merged_count == 3
    assert single.before == {"card_daily_limit": None} and single.after == {"card_daily_limit": 6}
    assert several.field is None and several.merged_count == 1
    assert several.before == {"content_cards_enabled": None, "enabled_streams": None}
    assert several.after == {"content_cards_enabled": False, "enabled_streams": ["product_card"]}


async def test_settings_put_back_to_the_original_value_leaves_no_row(session):
    _, shop = await make_tenant(session)
    user = await _staff(session, "operator")
    url = f"/v1/ops/shops/{shop.id}/settings"
    async with _client_as(session, user) as client:
        await client.put(url, json={"changes": {"stage": "pilot"}})
        await client.put(url, json={"changes": {"stage": "trial"}})
    assert await _count(session, OpsAuditLog) == 0


# -- audit list: kind filter, kind / merged_count fields ------------------------------------


async def test_audit_list_filters_by_kind_and_returns_kind_and_merged_count(session):
    _, shop = await make_tenant(session)
    actor = await _actor(session)
    await audit.record(session, actor, "settings_update", shop_id=shop.id, after={"stage": "self"})
    await audit.record(session, actor, "view_as_view", shop_id=shop.id, after={"mode": "view"})
    await audit.record(session, audit.SYSTEM_ACTOR, "system_cap_alert", shop_id=shop.id)
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        everything = (await client.get("/v1/ops/audit")).json()["data"]
        by_kind = {
            kind: (await client.get(f"/v1/ops/audit?kind={kind}")).json()["data"]
            for kind in ("config", "view", "system")
        }
        bad = await client.get("/v1/ops/audit?kind=other")
    assert bad.status_code == 422
    assert {r["kind"] for r in everything} == {"config", "view", "system"}
    assert all(r["merged_count"] == 1 for r in everything)
    assert [r["action"] for r in by_kind["config"]] == ["settings_update"]
    assert [r["action"] for r in by_kind["view"]] == ["view_as_view"]
    assert [r["action"] for r in by_kind["system"]] == ["system_cap_alert"]


def test_kind_of_actions():
    assert audit.kind_of("settings_update") == "config"
    assert audit.kind_of("rule_set") == "config"
    assert audit.kind_of("shop_disconnect") == "config"
    assert audit.kind_of("view_as_view") == "view"
    assert audit.kind_of("view_as_exit") == "view"
    assert audit.kind_of("data_refresh") == "view"
    assert audit.kind_of("system_cap_alert") == "system"


# -- D27.4 retention -------------------------------------------------------------------------


async def test_retention_deletes_by_kind_age(session):
    actor = await _actor(session)
    now = datetime(2026, 10, 11, 3, 0)
    ages = {
        ("settings_update", 364): True,
        ("settings_update", 366): False,
        ("view_as_view", 89): True,
        ("view_as_view", 91): False,
        ("data_refresh", 91): False,
        ("system_job", 91): False,
        ("system_job", 30): True,
    }
    for (action, days), _kept in ages.items():
        session.add(
            OpsAuditLog(
                id=uuid.uuid4(),
                actor_staff_id=actor.staff_id,
                actor_email=actor.email,
                action=action,
                at=now - timedelta(days=days),
            )
        )
    await session.flush()
    deleted = await audit.purge_expired(session, now=now)
    assert deleted == 4
    left = {
        (r.action, (now - r.at).days)
        for r in (await session.execute(select(OpsAuditLog))).scalars()
    }
    assert left == {key for key, kept in ages.items() if kept}


async def test_retention_task_body_commits(engine, session):
    from juli_backend.workers.tasks.ops_audit_retention import run_ops_audit_retention

    actor = await _actor(session)
    session.add(
        OpsAuditLog(
            id=uuid.uuid4(),
            actor_staff_id=actor.staff_id,
            actor_email=actor.email,
            action="view_as_exit",
            at=utc_now_naive() - timedelta(days=200),
        )
    )
    await session.commit()
    deleted = await run_ops_audit_retention(async_sessionmaker(engine, expire_on_commit=False))
    assert deleted == 1
    session.expire_all()
    assert await _count(session, OpsAuditLog) == 0


def test_retention_task_is_registered_nightly_on_the_default_queue():
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["ops-audit-retention"]
    assert entry["task"] == "juli_backend.ops_audit_retention"
    assert "juli_backend.ops_audit_retention" in celery_app.tasks
    assert "juli_backend.ops_audit_retention" not in celery_app.conf.task_routes
    assert entry["schedule"].hour == {20} and entry["schedule"].minute == {31}


# -- migration 085 -------------------------------------------------------------------------


def test_migration_085_chain_and_shape():
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "085_ops_daily_precompute"' in text
    assert len("085_ops_daily_precompute") <= 32
    assert 'down_revision: str | None = "084_onboarding_speed"' in text
    deferred = (
        MIGRATION.parents[1] / "deferred" / "074_users_placeholder_phone_cleanup.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "097_production_write_shops"' in deferred
    for table in ("shop_daily_streams", "shop_daily_products", "ops_shop_daily_summary"):
        assert f'"{table}"' in text
    for model in (ShopDailyStream, ShopDailyProduct, OpsShopDailySummary):
        for column in model.__table__.columns.keys():
            assert f'"{column}"' in text, (model.__tablename__, column)
    for column in ("merged_count", "field"):
        assert f'"{column}"' in text
    assert "app_current_shop_id()" in text
    assert "FOR ALL TO {OPS_ROLE}" in text
    assert 'AUDIT_NEW_VERBS = "UPDATE, DELETE"' in text
    assert "SECURITY DEFINER" in text and "ops_find_shop" in text


def test_new_tables_are_classified():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "shop_daily_streams")] == "tenant_direct"
    assert TABLE_CLASSIFICATION_MAP[("public", "shop_daily_products")] == "tenant_direct"
    assert TABLE_CLASSIFICATION_MAP[("public", "ops_shop_daily_summary")] == "ops_only"
