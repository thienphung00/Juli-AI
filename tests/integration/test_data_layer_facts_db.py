"""Data layer, migration 140 on real Postgres (batch-1124-c-data, decisions #62-#66).

- ``product_channel_metrics_daily``, ``shop_channel_metrics_daily``, ``campaign_metrics_daily``,
  ``shopee_opportunities``: RLS on,
  ``juli_app`` grants (DELETE only on the two sparse fact tables), ``juli_ops`` nothing; a shop
  sees and writes only its own rows; the natural keys and the CHECKs hold; the grain comment;
- the synthetic shop rebuilt on Postgres: a same-data rerun writes no tuple (owner rule 9:
  ``pg_stat_xact_user_tables.n_tup_upd`` unchanged, every ``ctid`` unchanged);
- last: ``downgrade`` to 138 drops what 140 added, ``upgrade head`` restores it.

Synthetic tenants and the synthetic shop only; the tables hold aggregates, no buyer data.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.shopee_analytics import materialize
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres
from tests.support.shopee_analytics import seed_shopee_shop

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
DAY = date(2026, 11, 5)
NEW_TABLES = {
    "product_channel_metrics_daily": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "shop_channel_metrics_daily": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "shop_facts_status": {"SELECT", "INSERT", "UPDATE"},
    "campaign_metrics_daily": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "shopee_opportunities": {"SELECT", "INSERT", "UPDATE"},
}
FACT_TABLES = (
    "shop_metrics_daily",
    "product_metrics_daily",
    "source_metrics_daily",
    "product_channel_metrics_daily",
    "shop_channel_metrics_daily",
    "campaign_metrics_daily",
)


def _verbs(conn, role: str, table: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{table}", "v": verb},
        ).scalar()
    }


def _role_exists(conn, role: str) -> bool:
    return bool(
        conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def _cell(conn, shop_id: uuid.UUID, *, channel: str = "ads", discounted: str = "with") -> None:
    conn.execute(
        text(
            "INSERT INTO public.product_channel_metrics_daily (id, shop_id, day, item_id, channel, "
            "discounted, gmv, orders, derivation_version) "
            "VALUES (:id, :shop, :day, '1001', :ch, :d, 50000, 1, 'v')"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "day": DAY, "ch": channel, "d": discounted},
    )


def _opp(
    conn, shop_id: uuid.UUID, *, outcome: str = "published", source: str | None = None
) -> None:
    cols, vals = "", ""
    if source is not None:
        cols, vals = ", source", ", :src"
    conn.execute(
        text(
            "INSERT INTO public.shopee_opportunities (id, shop_id, run_date, kind, scope, outcome, "
            f"derivation_version{cols}) "
            f"VALUES (:id, :shop, :day, 'product_discount', 'product', :o, 'v'{vals})"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "day": DAY, "o": outcome, "src": source},
    )


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


@pytest.mark.parametrize("table", sorted(NEW_TABLES))
def test_the_new_tables_have_rls_and_upsert_grants_for_the_runtime_role(owner_engine, table):
    with owner_engine.connect() as conn:
        on = conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = :t"
            ),
            {"t": table},
        ).scalar()
        assert on is True
        assert _verbs(conn, RUNTIME_ROLE, table) == NEW_TABLES[table]
        if _role_exists(conn, "juli_ops"):
            assert _verbs(conn, "juli_ops", table) == set()


@pytest.mark.parametrize("table", FACT_TABLES)
def test_each_fact_table_states_its_grain(owner_engine, table):
    with owner_engine.connect() as conn:
        comment = conn.execute(
            text("SELECT obj_description(to_regclass(:t), 'pg_class')"), {"t": f"public.{table}"}
        ).scalar()
    assert comment is not None and comment.startswith("grain: shop_id x day")


def test_a_shop_sees_and_writes_only_its_own_cells(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _cell(conn, a.shop_id, channel="organic")
        _cell(conn, b.shop_id, channel="organic")
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        shops = set(
            conn.execute(text("SELECT shop_id FROM public.product_channel_metrics_daily")).scalars()
        )
        assert shops == {a.shop_id}
        _cell(conn, a.shop_id, channel="affiliate")
        with pytest.raises(DBAPIError):
            _cell(conn, b.shop_id, channel="affiliate")
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_the_natural_keys_and_the_checks_hold(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.connect() as conn:
        _cell(conn, a.shop_id, channel="ads", discounted="without")
        with pytest.raises(IntegrityError):
            _cell(conn, a.shop_id, channel="ads", discounted="without")
        conn.rollback()
        with pytest.raises(IntegrityError):
            _cell(conn, a.shop_id, channel="quang_cao")
        conn.rollback()
        with pytest.raises(IntegrityError):
            _cell(conn, a.shop_id, discounted="maybe")
        conn.rollback()
        _opp(conn, a.shop_id)
        with pytest.raises(IntegrityError):
            _opp(conn, a.shop_id)  # same run, kind, scope, version: one row
        conn.rollback()
        with pytest.raises(IntegrityError):
            _opp(conn, a.shop_id, outcome="maybe")
        conn.rollback()
        with pytest.raises(IntegrityError):
            _opp(conn, a.shop_id, outcome="ranked_out", source="chat")
        conn.rollback()
        _opp(conn, a.shop_id, outcome="refused")
        assert (
            conn.execute(text("SELECT source FROM public.shopee_opportunities LIMIT 1")).scalar()
            == "daily"
        )
        conn.rollback()


@asynccontextmanager
async def pg_session():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    conn = await engine.connect()
    outer = await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await outer.rollback()
        await conn.close()
        await engine.dispose()


async def _writes(session) -> dict[str, int]:
    rows = await session.execute(
        text(
            "SELECT relname, n_tup_upd + n_tup_ins + n_tup_del FROM pg_stat_xact_user_tables "
            "WHERE relname = ANY(:t)"
        ),
        {"t": list(FACT_TABLES)},
    )
    return {name: int(n) for name, n in rows.all()}


async def _ctids(session, shop_id) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table in FACT_TABLES:
        found = await session.execute(
            text(f"SELECT ctid::text FROM public.{table} WHERE shop_id = :s"),  # nosec B608
            {"s": shop_id},
        )
        out[table] = set(found.scalars().all())
    return out


async def test_a_same_data_rebuild_writes_no_tuple_on_postgres():
    async with pg_session() as session:
        seeded = await seed_shopee_shop(session, rules=True)
        sid = seeded.shop_id
        before_ctid = await _ctids(session, sid)
        before = await _writes(session)
        report = await materialize.backfill_shop(session, sid)
        await session.flush()
        assert report.days_written > 0
        assert await _writes(session) == before  # n_tup_upd / ins / del unchanged
        assert await _ctids(session, sid) == before_ctid
        assert before_ctid["product_channel_metrics_daily"]  # the cells exist


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 138, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def state() -> tuple[bool, bool]:
        with owner_engine.connect() as conn:
            tables = all(
                conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{t}"}).scalar()
                for t in NEW_TABLES
            )
            column = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                    "AND table_name = 'shop_metrics_daily' AND column_name = 'derivation_version'"
                )
            ).scalar()
            return tables, bool(column)

    assert state() == (True, True)
    command.downgrade(cfg, "139_hot_path_indexes")
    try:
        assert state() == (False, False)
    finally:
        command.upgrade(cfg, "head")
    assert state() == (True, True)


async def test_a_second_backfill_run_skips_while_one_holds_the_lock():
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.services.shopee_analytics import facts_backfill

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as holder:
            await holder.begin()
            held = await holder.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"),
                {"k": facts_backfill.ADVISORY_LOCK_KEY},
            )
            assert held.scalar() is True
            result = await facts_backfill.run(async_sessionmaker(engine, expire_on_commit=False))
            assert result.skipped == "locked" and result.shops == 0
            await holder.rollback()
    finally:
        await engine.dispose()
