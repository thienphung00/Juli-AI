"""Hashes, per-field attribution and ``seller_change`` on real Postgres (fast track P60-1b).

ADR-107 "Amendment 2026-10-20" §6, §8 and its Verification paragraph, layer (2):

- the end-to-end walk, per tenant, as ``juli_app`` under that tenant's scope: a
  Juli write recorded with hashes -> product re-reads equal to Juli's after
  (``juli``), to Juli's before (``seller_revert``) and different
  (``seller_change``) -> ``external_changes.attribution`` / ``field_attribution``
  -> ``card_events`` ``seller_change`` rows with the card that wrote the field,
  and NULL for a product with no card; tenant B sees none of A's rows;
- the 096 CHECK, unchanged append-only grants (``juli_app`` cannot UPDATE /
  DELETE ``external_changes``, ``run_write_values`` or ``card_events``) and the
  identifiers-only ``enumerate_history_shops()``;
- the migration's data step: rows seeded at 095 get hashes, the audit link only
  when exactly one audit row matches, and attribution; then the backfill as
  ``juli_app`` writes ``seller_change`` rows, and a second run writes nothing;
- ``downgrade`` to 095 and back to head.

The tenants are fresh shops seeded by ``two_tenant.seed_tenant`` -- not the demo
or reference shop. Not marked ``migration_heavy`` (the amendment: issue tier).
It downgrades, so it is in ``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES``.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from juli_backend.services.agent.runner.write_capture import FieldWrite
from juli_backend.services.card_events.backfill import backfill_shop
from juli_backend.services.product_history import store
from juli_backend.services.product_history.normalize import field_value_hash, normalize_detail
from juli_backend.services.run_changes.recorder import SqlWriteValueRecorder
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@asynccontextmanager
async def app_session(shop_id: uuid.UUID):
    """A ``juli_app`` async session scoped to one shop whose commits really commit."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.execute(
                text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                    v=str(shop_id)
                )
            )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


@contextmanager
def sync_app_session(shop_id: uuid.UUID):
    """The worker's synchronous ``juli_app`` session (what the recorder runs on)."""
    from juli_backend.core.config.runtime import sync_database_url

    engine = create_engine(sync_database_url(os.environ["DATABASE_URL"]))
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            conn.execute(
                text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)}
            )
            conn.commit()
            with Session(bind=conn) as session:
                yield session
    finally:
        engine.dispose()


def _tiktok_id(owner_engine, product_id: uuid.UUID) -> str:
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT tiktok_product_id FROM public.products WHERE id = :id"),
            {"id": str(product_id)},
        ).scalar_one()


def _seed_card_and_run(owner_engine, tenant, product_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """A card and its executed run on ``product_id`` (set-up, as the owner)."""
    card_id, run_id = uuid.uuid4(), uuid.uuid4()
    now = _now()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                " subject_id, revision, priority, severity, title, description, "
                " recommendation_payload, status, metadata_json, computed_at) "
                "VALUES (:id, :shop, :wk, 'product', :subject, 1, 1, 'high', 'Tối ưu', 'd', "
                " '{}', 'approved', '{}', :now)"
            ),
            {
                "id": str(card_id),
                "shop": str(tenant.shop_id),
                "wk": f"attr_{card_id.hex[:6]}",
                "subject": str(product_id),
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.workflow_runs (id, shop_id, product_id, action_card_id, "
                " state, status, stop_reason, prompt_version, prompt_sha256, "
                " running_seconds_elapsed, cancel_requested, subject_ref, completed_at, "
                " created_at, updated_at) "
                "VALUES (:id, :shop, :product, :card, '{}', 'completed', 'final_response', "
                " 'optimize_product.v3', :sha, 0, false, :ref, :done, :now, :now)"
            ),
            {
                "id": str(run_id),
                "shop": str(tenant.shop_id),
                "product": str(product_id),
                "card": str(card_id),
                "sha": "0" * 64,
                "ref": f"attr-{run_id.hex[:12]}",
                "done": now.replace(tzinfo=UTC),
                "now": now,
            },
        )
    return {"card": card_id, "run": run_id}


def _raw(tiktok_id: str, title: str) -> dict:
    return {
        "id": tiktok_id,
        "title": title,
        "description": "<p>mô tả</p>",
        "main_images": [{"uri": "img-a"}],
        "skus": [{"id": "s1", "price": {"tax_exclusive_price": "50000", "currency": "VND"}}],
        "status": "ACTIVATE",
    }


async def _read(shop_id, tiktok_id, title, *, previous, at, baseline=False):
    async with app_session(shop_id) as session:
        prev = None
        if previous:
            prev = (await store.latest_snapshots(session, shop_id, [tiktok_id])).get(tiktok_id)
        outcome = await store.record_read(
            session,
            shop_id=shop_id,
            new=normalize_detail(_raw(tiktok_id, title)),
            previous=prev,
            source="reconcile",
            now=at,
            baseline=baseline,
        )
        await session.commit()
        return [
            (row.id, row.attribution, row.field_attribution, row.juli_write)
            for row in outcome.changes
        ]


def _rows(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


# -- the end-to-end walk, two tenants --------------------------------------------------------


@pytest.fixture(scope="module")
def walked(owner_engine, two_tenants):
    """Run the walk for both tenants; return what each produced."""
    import asyncio

    out = {}
    for tenant in two_tenants:
        out[tenant.shop_id] = asyncio.run(_walk(owner_engine, tenant))
    return out


async def _walk(owner_engine, tenant) -> dict:
    seeded = _seed_card_and_run(owner_engine, tenant, tenant.product_id)
    pid = _tiktok_id(owner_engine, tenant.product_id)
    cardless_pid = _tiktok_id(owner_engine, tenant.second_product_id)
    start = _now()

    # Baselines: the product as it was before Juli's write.
    await _read(
        tenant.shop_id, pid, "Cũ", previous=False, at=start - timedelta(days=3), baseline=True
    )
    await _read(
        tenant.shop_id,
        cardless_pid,
        "Gốc",
        previous=False,
        at=start - timedelta(days=3),
        baseline=True,
    )

    # 1. Juli writes the title (recorder on the worker's sync session, as juli_app).
    with sync_app_session(tenant.shop_id) as session:
        SqlWriteValueRecorder(
            session, shop_id=tenant.shop_id, workflow_run_id=seeded["run"]
        ).record(
            tool_name="update_product_listing",
            tool_call_id="call-1",
            tiktok_product_id=pid,
            writes=[FieldWrite("title", "Cũ", "Mới", "read_back", before_read_at=start)],
        )

    # 2. Re-reads: Juli's after, then the seller's revert, then the seller's own change.
    juli = await _read(tenant.shop_id, pid, "Mới", previous=True, at=_now() + timedelta(minutes=5))
    revert = await _read(tenant.shop_id, pid, "Cũ", previous=True, at=_now() + timedelta(days=2))
    change = await _read(tenant.shop_id, pid, "Khác", previous=True, at=_now() + timedelta(days=3))
    # 3. A product with no card: a natural action.
    natural = await _read(
        tenant.shop_id, cardless_pid, "Seller viết", previous=True, at=_now() + timedelta(days=1)
    )
    return {
        **seeded,
        "pid": pid,
        "juli": juli,
        "revert": revert,
        "change": change,
        "natural": natural,
    }


def test_juli_write_is_recorded_with_hashes(owner_engine, two_tenants, walked):
    for tenant in two_tenants:
        [row] = _rows(
            owner_engine,
            "SELECT before_hash, after_hash, before_read_at, production_write_audit_id "
            "FROM public.run_write_values WHERE shop_id = :shop",
            shop=str(tenant.shop_id),
        )
        assert row["before_hash"] == field_value_hash("title", "Cũ")
        assert row["after_hash"] == field_value_hash("title", "Mới")
        assert row["before_read_at"] is not None
        assert row["production_write_audit_id"] is None  # no audit row for this mutation


def test_each_reread_is_attributed_per_field(two_tenants, walked):
    for tenant in two_tenants:
        got = walked[tenant.shop_id]
        [(_, juli_label, juli_fields, juli_write)] = got["juli"]
        assert (juli_label, juli_fields, juli_write) == ("juli", {"title": "juli"}, True)
        [(_, revert_label, revert_fields, revert_write)] = got["revert"]
        assert (revert_label, revert_fields, revert_write) == (
            "seller_revert",
            {"title": "seller_revert"},
            False,
        )
        [(_, change_label, change_fields, _w)] = got["change"]
        assert (change_label, change_fields) == ("seller_change", {"title": "seller_change"})


def test_seller_change_events_carry_the_card_or_null(owner_engine, two_tenants, walked):
    for tenant in two_tenants:
        got = walked[tenant.shop_id]
        events = {
            row["key"]: row
            for row in _rows(
                owner_engine,
                "SELECT dedup_key AS key, card_id, workflow_run_id, source, payload, subject_id "
                "FROM public.card_events WHERE shop_id = :shop AND event_type = 'seller_change'",
                shop=str(tenant.shop_id),
            )
        }
        juli_id = got["juli"][0][0]
        revert_id, change_id = got["revert"][0][0], got["change"][0][0]
        natural_id = got["natural"][0][0]
        assert f"seller_change:{juli_id}" not in events  # Juli's own write is not an event
        revert = events[f"seller_change:{revert_id}"]
        assert revert["card_id"] == got["card"] and revert["workflow_run_id"] == got["run"]
        assert revert["payload"]["attribution"] == "seller_revert"
        assert revert["payload"]["card_link"] == "last_write"
        change = events[f"seller_change:{change_id}"]
        assert change["card_id"] == got["card"]
        assert change["payload"]["attribution"] == "seller_change"
        natural = events[f"seller_change:{natural_id}"]
        assert natural["card_id"] is None and natural["payload"]["card_link"] is None
        assert {row["source"] for row in events.values()} == {"live"}
        assert len(events) == 3


@pytest.mark.asyncio
async def test_tenant_b_sees_none_of_tenant_a(owner_engine, two_tenants, walked):
    tenant_a, tenant_b = two_tenants
    async with app_session(tenant_b.shop_id) as session:
        for table in ("external_changes", "run_write_values", "card_events"):
            shops = {
                row[0]
                for row in (
                    await session.execute(text(f"SELECT shop_id FROM public.{table}"))  # nosec B608
                ).all()
            }
            assert shops == {tenant_b.shop_id}, table
        # B cannot write a seller_change for A.
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.external_changes (id, shop_id, tiktok_product_id, kind, "
                    " fields, occurred_at, detected_at, source, juli_write, dedup_key, "
                    " attribution, field_attribution) VALUES (:id, :shop, 'tt', 'content', "
                    " '[\"title\"]', now(), now(), 'reconcile', false, 'b-for-a', "
                    " 'seller_change', '{\"title\": \"seller_change\"}')"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
        await session.rollback()
    # Each tenant's events name only its own card.
    for tenant, other in ((tenant_a, tenant_b), (tenant_b, tenant_a)):
        cards = {
            row["card_id"]
            for row in _rows(
                owner_engine,
                "SELECT card_id FROM public.card_events WHERE shop_id = :shop "
                "AND event_type = 'seller_change' AND card_id IS NOT NULL",
                shop=str(tenant.shop_id),
            )
        }
        assert cards == {walked[tenant.shop_id]["card"]}
        assert walked[other.shop_id]["card"] not in cards


# -- grants, CHECK, enumeration ----------------------------------------------------------------


def _grants(owner_engine, table: str) -> set[str]:
    return {
        row["privilege_type"]
        for row in _rows(
            owner_engine,
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND table_name = :t AND grantee = :role",
            t=table,
            role=RUNTIME_ROLE,
        )
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE public.external_changes SET attribution = 'juli' WHERE shop_id = :shop",
        "DELETE FROM public.external_changes WHERE shop_id = :shop",
        "UPDATE public.run_write_values SET after_hash = NULL WHERE shop_id = :shop",
        "UPDATE public.card_events SET payload = '{}' WHERE shop_id = :shop",
        "DELETE FROM public.card_events WHERE shop_id = :shop",
    ],
)
async def test_append_only_for_juli_app(owner_engine, two_tenants, walked, statement):
    tenant_a, _ = two_tenants
    for table in ("external_changes", "run_write_values", "card_events"):
        assert _grants(owner_engine, table) == {"SELECT", "INSERT"}, table
    async with app_session(tenant_a.shop_id) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(text(statement), {"shop": str(tenant_a.shop_id)})
        await session.rollback()


def test_attribution_check(owner_engine, two_tenants):
    tenant_a, _ = two_tenants
    before = _rows(
        owner_engine,
        "SELECT count(*) AS n FROM public.external_changes WHERE shop_id = :s",
        s=str(tenant_a.shop_id),
    )[0]["n"]
    with pytest.raises(IntegrityError, match="ck_external_changes_attribution"):
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO public.external_changes (id, shop_id, kind, fields, "
                    " occurred_at, detected_at, source, juli_write, dedup_key, attribution) "
                    "VALUES (:id, :shop, 'content', '[]', now(), now(), 'reconcile', false, "
                    " :key, 'bogus')"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id), "key": uuid.uuid4().hex},
            )
    after = _rows(
        owner_engine,
        "SELECT count(*) AS n FROM public.external_changes WHERE shop_id = :s",
        s=str(tenant_a.shop_id),
    )[0]["n"]
    assert after == before


@pytest.mark.asyncio
async def test_enumerate_history_shops_is_ids_only_and_app_only(owner_engine, two_tenants, walked):
    [fn] = _rows(
        owner_engine,
        "SELECT prosecdef, has_function_privilege('public', oid, 'EXECUTE') AS public_can, "
        " has_function_privilege(:role, oid, 'EXECUTE') AS app_can, "
        " pg_get_function_result(oid) AS result "
        "FROM pg_proc WHERE proname = 'enumerate_history_shops'",
        role=RUNTIME_ROLE,
    )
    assert fn["prosecdef"] and not fn["public_can"] and fn["app_can"]
    assert fn["result"] == "TABLE(out_shop_id uuid)"
    # Called with no shop scope at all, as the fan-out is: both tenants (no
    # pollable credential is needed for a shop with history).
    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.workers.tasks.card_events_backfill import enumerate_backfill_shops

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            session = AsyncSession(bind=conn)
            found = {shop.shop_id for shop in await enumerate_backfill_shops(session)}
            await session.close()
    finally:
        await engine.dispose()
    assert {t.shop_id for t in two_tenants} <= found


# -- the migration's data step, the backfill, the round trip ---------------------------------


def _alembic():
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))
    return cfg


def _head(owner_engine) -> str:
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _seed_legacy(conn, tenant, *, run_id: uuid.UUID, pid: str) -> dict[str, uuid.UUID]:
    """Rows as pre-096 code wrote them: no hashes, no attribution."""
    at = datetime(2026, 9, 1, 3, 0)
    ids = {"write": uuid.uuid4(), "price": uuid.uuid4(), "snap": uuid.uuid4()}
    ids |= {"revert": uuid.uuid4(), "juli": uuid.uuid4(), "promo": uuid.uuid4()}
    for key, field, before, after, tool in (
        ("write", "description", "<p>cũ</p>", "<p>mới</p>", "update_product_listing"),
        (
            "price",
            "price",
            [{"sku_id": "s1", "amount": "40000"}],
            [{"sku_id": "s1", "amount": "50000"}],
            "update_product_price",
        ),
    ):
        conn.execute(
            text(
                "INSERT INTO public.run_write_values (id, shop_id, workflow_run_id, tool_call_id, "
                " tool_name, tiktok_product_id, field, before_value, after_value, after_source, "
                " recorded_at) VALUES (:id, :shop, :run, :call, :tool, :pid, :field, "
                " CAST(:before AS json), CAST(:after AS json), 'read_back', :at)"
            ),
            {
                "id": str(ids[key]),
                "shop": str(tenant.shop_id),
                "run": str(run_id),
                "call": f"legacy-{key}",
                "tool": tool,
                "pid": pid,
                "field": field,
                "before": json.dumps(before),
                "after": json.dumps(after),
                "at": at,
            },
        )
    # Exactly one audit row for the listing write; two for the price write.
    for kind, count in (("update_product_listing", 1), ("update_product_price", 2)):
        for _ in range(count):
            conn.execute(
                text(
                    "INSERT INTO public.production_write_audit (id, run_id, shop_id, "
                    " tiktok_product_id, mutation_kind, release_sha) "
                    "VALUES (:id, :run, :shop, :pid, :kind, :sha)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run": str(run_id),
                    "shop": str(tenant.shop_id),
                    "pid": pid,
                    "kind": kind,
                    "sha": "0" * 40,
                },
            )
    # The product as the seller put it back: description = Juli's before.
    conn.execute(
        text(
            "INSERT INTO public.product_snapshots (id, shop_id, tiktok_product_id, "
            " snapshot_date, taken_at, content_hash, state_hash, title, description_hash, "
            " main_images, skus, source) VALUES (:id, :shop, :pid, :day, :at, :h, :h2, 'T', "
            " :dh, CAST(:imgs AS json), CAST(:skus AS json), 'reconcile')"
        ),
        {
            "id": str(ids["snap"]),
            "shop": str(tenant.shop_id),
            "pid": pid,
            "day": (at + timedelta(days=10)).date(),
            "at": at + timedelta(days=10),
            "h": "c" * 64,
            "h2": "d" * 64,
            "dh": field_value_hash("description", "<p>cũ</p>"),
            "imgs": json.dumps([{"uri": "img-a", "hash": "x"}]),
            "skus": json.dumps([{"sku_id": "s1", "list_price": "50000", "sale_price": None}]),
        },
    )
    for key, kind, fields, juli, details in (
        (
            "revert",
            "content",
            ["description", "attributes"],
            False,
            {"snapshot_id": str(ids["snap"])},
        ),
        ("juli", "price", ["price", "list_price"], True, {"snapshot_id": str(ids["snap"])}),
        ("promo", "promotion", ["promotion"], False, {"activity_id": "a1"}),
    ):
        conn.execute(
            text(
                "INSERT INTO public.external_changes (id, shop_id, tiktok_product_id, kind, "
                " fields, occurred_at, detected_at, source, juli_write, details, dedup_key) "
                "VALUES (:id, :shop, :pid, :kind, CAST(:fields AS json), :at, :at, 'reconcile', "
                " :juli, CAST(:details AS json), :key)"
            ),
            {
                "id": str(ids[key]),
                "shop": str(tenant.shop_id),
                "pid": pid,
                "kind": kind,
                "fields": json.dumps(fields),
                "at": at + timedelta(days=10),
                "juli": juli,
                "details": json.dumps(details),
                "key": f"legacy:{key}:{uuid.uuid4().hex[:6]}",
            },
        )
    return ids


@pytest.mark.asyncio
async def test_zz_data_step_backfill_and_round_trip(owner_engine, two_tenants, walked):
    """Last in the module: down to 095, seed pre-096 rows, up to head, backfill twice."""
    from alembic import command

    tenant_a, tenant_b = two_tenants
    from alembic.script import ScriptDirectory

    cfg = _alembic()
    # Later migrations sit on top of 096; the round trip names 096's parent and returns to
    # whatever the script head is (not a pinned revision, which breaks on every new one).
    script_head = ScriptDirectory.from_config(cfg).get_current_head()
    assert _head(owner_engine) == script_head
    command.downgrade(cfg, "095_card_events")
    assert _head(owner_engine) == "095_card_events"
    with owner_engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_name = "
                    "'external_changes' AND column_name IN ('attribution', 'field_attribution')"
                )
            ).scalar_one()
            == 0
        )
    legacy_run = _seed_card_and_run(owner_engine, tenant_a, tenant_a.third_product_id)
    pid = _tiktok_id(owner_engine, tenant_a.third_product_id)
    with owner_engine.begin() as conn:
        ids = _seed_legacy(conn, tenant_a, run_id=legacy_run["run"], pid=pid)

    command.upgrade(cfg, "head")
    assert _head(owner_engine) == script_head

    writes = {
        row["id"]: row
        for row in _rows(
            owner_engine,
            "SELECT id, before_hash, after_hash, production_write_audit_id "
            "FROM public.run_write_values WHERE shop_id = :shop",
            shop=str(tenant_a.shop_id),
        )
    }
    assert writes[ids["write"]]["before_hash"] == field_value_hash("description", "<p>cũ</p>")
    assert writes[ids["write"]]["after_hash"] == field_value_hash("description", "<p>mới</p>")
    assert writes[ids["write"]]["production_write_audit_id"] is not None  # exactly one match
    assert writes[ids["price"]]["production_write_audit_id"] is None  # two matches: ambiguous
    assert writes[ids["price"]]["after_hash"] == field_value_hash(
        "price", [{"sku_id": "s1", "amount": "50000"}]
    )
    changes = {
        row["id"]: row
        for row in _rows(
            owner_engine,
            "SELECT id, attribution, field_attribution FROM public.external_changes "
            "WHERE shop_id = :shop",
            shop=str(tenant_a.shop_id),
        )
    }
    assert changes[ids["revert"]]["attribution"] == "mixed"
    assert changes[ids["revert"]]["field_attribution"] == {
        "description": "seller_revert",
        "attributes": "seller_change",
    }
    assert changes[ids["juli"]]["attribution"] == "juli"
    assert changes[ids["promo"]]["attribution"] == "seller_change"
    # The walk's rows, dropped with the columns, were recomputed the same way.
    walked_revert = walked[tenant_a.shop_id]["revert"][0][0]
    assert changes[walked_revert]["field_attribution"] == {"title": "seller_revert"}
    assert all(row["attribution"] is not None for row in changes.values())

    async def backfill() -> dict:
        async with app_session(tenant_a.shop_id) as session:
            report = await backfill_shop(session, tenant_a.shop_id)
            await session.commit()
        return report.as_dict()

    before_b = _rows(
        owner_engine,
        "SELECT count(*) AS n FROM public.card_events WHERE shop_id = :s",
        s=str(tenant_b.shop_id),
    )[0]["n"]
    first = await backfill()
    events = {
        row["key"]: row
        for row in _rows(
            owner_engine,
            "SELECT dedup_key AS key, card_id, source, payload FROM public.card_events "
            "WHERE shop_id = :shop AND event_type = 'seller_change'",
            shop=str(tenant_a.shop_id),
        )
    }
    revert_event = events[f"seller_change:{ids['revert']}"]
    assert revert_event["source"] == "backfill"
    assert revert_event["card_id"] == legacy_run["card"]  # its run last wrote the description
    assert revert_event["payload"]["attribution"] == "seller_change"  # mixed revert + change
    assert f"seller_change:{ids['juli']}" not in events
    promo = events[f"seller_change:{ids['promo']}"]
    assert promo["source"] == "backfill"
    assert first["inserted"]["seller_change"] == 2  # the walk's live rows are kept, not doubled
    count = len(events)
    second = await backfill()
    assert second["inserted_total"] == 0
    assert (
        len(
            _rows(
                owner_engine,
                "SELECT 1 FROM public.card_events WHERE shop_id = :shop "
                "AND event_type = 'seller_change'",
                shop=str(tenant_a.shop_id),
            )
        )
        == count
    )
    after_b = _rows(
        owner_engine,
        "SELECT count(*) AS n FROM public.card_events WHERE shop_id = :s",
        s=str(tenant_b.shop_id),
    )[0]["n"]
    assert after_b == before_b
