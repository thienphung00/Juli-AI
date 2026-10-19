"""P50-B privacy on real Postgres (migration ``094_user_privacy_and_consent``, D68).

- ``juli_app`` writes the privacy columns of its own row only, and cannot call
  the purge functions; ``juli_ops`` can.
- ``enumerate_pollable_shops`` drops a shop whose owner has a pending deletion.
- ``privacy_account_purge`` deletes a due account with its shops and every row of
  their data -- including rows without a ``shop_id`` that hang off them and the
  legacy no-write tables -- keeps the subscription periods detached, leaves the
  other tenant untouched, refuses an account that is not due, and the worker
  task runs it from a ``juli_app`` login through ``juli_ops``.
- The catalog assumptions the purge's ordering relies on are pinned.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.repositories.identity import UsersRepo
from juli_backend.services import privacy
from juli_backend.workers.tasks.privacy_account_purge import run_privacy_account_purge
from tests.integration.two_tenant import RUNTIME_ROLE, Tenant, seed_tenant

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

#: Tables without a shop_id that reference a shop-scoped row (purge step 2). A new
#: one is fine as long as its parent carries a shop_id; a deeper chain is not.
DEPENDENT_TABLES = {
    "action_card_approvals",
    "impact_readings",
    "run_confirmations",
    "workflow_run_events",
}


@asynccontextmanager
async def app_session():
    """A ``juli_app`` session (SET ROLE on the owner connection, like production's login)."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
                await session.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()


def _shop_tables(conn) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT c.oid::regclass::text FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'shop_id' "
                "AND NOT a.attisdropped AND a.atttypid = 'uuid'::regtype "
                "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
            )
        ).scalars()
    )


def _rows_for_shop(conn, shop_id: uuid.UUID) -> dict[str, int]:
    counts = {}
    for table in _shop_tables(conn):
        n = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE shop_id = :s"),  # nosec B608
            {"s": shop_id},
        ).scalar_one()
        if n:
            counts[table] = n
    return counts


def _seed_extra(conn, tenant: Tenant) -> None:
    """Rows the two-tenant seeder does not write: kept, guarded and dependent ones."""
    card_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.shop_subscription_periods "
            "(id, shop_id, plan, days, starts_on, ends_on, source, reference, created_at) "
            "VALUES (:id, :s, 'month', 30, :a, :b, 'contract', :ref, now())"
        ),
        {
            "id": uuid.uuid4(),
            "s": tenant.shop_id,
            "a": date(2026, 10, 1),
            "b": date(2026, 10, 31),
            "ref": f"HD-{uuid.uuid4().hex[:8]}",
        },
    )
    conn.execute(
        text(
            "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
            "subject_id, priority, severity, title, description, recommendation_payload, "
            "status, revision, created_at, updated_at) VALUES (:id, :s, 'optimize_product', "
            "'product', :p, 1, 'medium', 'Đổi ảnh bìa', '', '{}', 'active', 1, now(), now())"
        ),
        {"id": card_id, "s": tenant.shop_id, "p": str(tenant.product_id)},
    )
    conn.execute(
        text(
            "INSERT INTO public.action_card_approvals (id, action_card_id, approved_by_user_id, "
            "approved_at, card_snapshot) VALUES (:id, :c, :u, now(), '{}')"
        ),
        {"id": uuid.uuid4(), "c": card_id, "u": tenant.user_id},
    )
    conn.execute(
        text(
            "INSERT INTO public.ops_audit_log (id, actor_email, shop_id, action) "
            "VALUES (:id, 'tester@app-juli.com', :s, 'privacy_test')"
        ),
        {"id": uuid.uuid4(), "s": tenant.shop_id},
    )
    # The legacy read-only table: seeding needs its no-write trigger off, as owner.
    conn.execute(text("ALTER TABLE public.orders DISABLE TRIGGER USER"))
    conn.execute(
        text(
            "INSERT INTO public.orders (id, shop_id, tiktok_order_id, status, total_amount, "
            "currency, update_time, created_at, updated_at) VALUES (:id, :s, :o, 'COMPLETED', "
            "100, 'VND', now(), now(), now())"
        ),
        {"id": uuid.uuid4(), "s": tenant.shop_id, "o": f"o-{uuid.uuid4().hex[:8]}"},
    )
    conn.execute(text("ALTER TABLE public.orders ENABLE TRIGGER USER"))


def _schedule(conn, user_id: uuid.UUID, when: datetime | None) -> None:
    conn.execute(
        text("UPDATE public.users SET deletion_scheduled_for = :w WHERE id = :u"),
        {"w": when, "u": user_id},
    )


# -- grants -------------------------------------------------------------------------------


async def test_juli_app_writes_its_own_privacy_columns_only(owner_engine):
    mine = seed_tenant(owner_engine, label="privacy-own")
    other = seed_tenant(owner_engine, label="privacy-other")
    async with app_session() as session:
        user = await UsersRepo(session).update_privacy(
            mine.user_id, marketing_opt_out=True, deletion_scheduled_for=datetime.now(UTC)
        )
        assert user.marketing_opt_out is True
        await session.commit()
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(
                text("UPDATE public.users SET phone = '+84900000000' WHERE id = :u"),
                {"u": mine.user_id},
            )
        await session.rollback()
        # Another user's row is invisible to the caller's scope: nothing updated.
        await session.execute(
            text("SELECT set_config('app.current_user_id', :u, false)"), {"u": str(mine.user_id)}
        )
        result = await session.execute(
            text("UPDATE public.users SET marketing_opt_out = true WHERE id = :u"),
            {"u": other.user_id},
        )
        assert result.rowcount == 0
    with owner_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT marketing_opt_out FROM public.users WHERE id = :u"),
                {"u": other.user_id},
            ).scalar_one()
            is False
        )


@pytest.mark.parametrize(
    "call",
    [
        "SELECT * FROM public.privacy_due_accounts(now())",
        "SELECT * FROM public.privacy_purge_account(gen_random_uuid())",
    ],
)
async def test_juli_app_cannot_call_the_purge_functions(owner_engine, call):
    async with app_session() as session:
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text(call))


# -- shop sync ----------------------------------------------------------------------------


async def test_enumeration_skips_a_shop_whose_owner_asked_for_deletion(owner_engine):
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    keep = seed_tenant(owner_engine, label="privacy-sync-keep")
    gone = seed_tenant(owner_engine, label="privacy-sync-gone")
    with owner_engine.begin() as conn:
        for tenant in (keep, gone):
            conn.execute(
                text(
                    "UPDATE public.tiktok_credentials SET capability = 'seller_connect', "
                    "merchant_authorization_id = :m WHERE id = :id"
                ),
                {"m": f"merchant-{tenant.shop_id.hex[:8]}", "id": tenant.fresh_credential_id},
            )

    async def listed() -> set[uuid.UUID]:
        async with app_session() as session:
            return {s.shop_id for s in await enumerate_pollable_shops(session)}

    before = await listed()
    assert {keep.shop_id, gone.shop_id} <= before
    with owner_engine.begin() as conn:
        _schedule(conn, gone.user_id, datetime.now(UTC) + timedelta(days=30))
    after = await listed()
    assert keep.shop_id in after and gone.shop_id not in after


# -- purge --------------------------------------------------------------------------------


async def test_purge_deletes_the_due_account_and_keeps_periods_and_other_tenants(owner_engine):
    gone = seed_tenant(owner_engine, label="privacy-purge-gone")
    keep = seed_tenant(owner_engine, label="privacy-purge-keep")
    with owner_engine.begin() as conn:
        _seed_extra(conn, gone)
        _seed_extra(conn, keep)
        _schedule(conn, gone.user_id, datetime.now(UTC) - timedelta(minutes=1))
        _schedule(conn, keep.user_id, datetime.now(UTC) + timedelta(days=29))
        keep_before = _rows_for_shop(conn, keep.shop_id)
        gone_before = _rows_for_shop(conn, gone.shop_id)
    assert "orders" in gone_before and "products" in gone_before

    summary = await run_privacy_account_purge(app_session)

    assert summary["purged"] >= 1 and summary["failed"] == 0
    assert summary["shops"] >= 1 and summary["rows"] >= sum(gone_before.values())
    with owner_engine.connect() as conn:
        # Only the staff audit row is left (kept; its own 90/365-day retention).
        assert _rows_for_shop(conn, gone.shop_id) == {"ops_audit_log": 1}
        for table, column, value in (
            ("public.users", "id", gone.user_id),
            ("public.shops", "id", gone.shop_id),
            ("public.action_card_approvals", "approved_by_user_id", gone.user_id),
        ):
            n = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :v"),  # nosec B608
                {"v": value},
            ).scalar_one()
            assert n == 0, table
        detached = conn.execute(
            text(
                "SELECT count(*) FROM public.shop_subscription_periods "
                "WHERE shop_id IS NULL AND reference LIKE 'HD-%'"
            )
        ).scalar_one()
        assert detached >= 1
        assert _rows_for_shop(conn, keep.shop_id) == keep_before
        assert (
            conn.execute(
                text("SELECT count(*) FROM public.users WHERE id = :u"), {"u": keep.user_id}
            ).scalar_one()
            == 1
        )
        # The no-write guard is back on after the purge.
        enabled = conn.execute(
            text("SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_orders_no_write'")
        ).scalar_one()
        assert enabled == "O"


async def test_purge_refuses_an_account_that_is_not_due(owner_engine):
    later = seed_tenant(owner_engine, label="privacy-purge-later")
    with owner_engine.begin() as conn:
        _schedule(conn, later.user_id, datetime.now(UTC) + timedelta(days=1))
    async with app_session() as session:
        assert later.user_id not in await privacy.due_account_ids(session, now=datetime.now(UTC))
        with pytest.raises(Exception, match="not due"):
            await privacy.purge_account(session, later.user_id)
        await session.rollback()
    with owner_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM public.shops WHERE id = :s"), {"s": later.shop_id}
            ).scalar_one()
            == 1
        )


# -- catalog assumptions ------------------------------------------------------------------


def test_every_dependent_table_hangs_off_a_shop_scoped_table(owner_engine):
    """Purge step 2 handles ONE level of shop_id-less children; pin that shape."""
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.conrelid::regclass::text, c.confrelid::regclass::text, "
                "EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.confrelid "
                "AND a.attname = 'shop_id' AND NOT a.attisdropped) "
                "FROM pg_constraint c WHERE c.contype = 'f' AND NOT EXISTS ("
                "SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.conrelid "
                "AND a.attname = 'shop_id' AND NOT a.attisdropped)"
            )
        ).all()
    children = {child for child, parent, _ in rows if parent not in ("users", "public.users")}
    children.discard("shops")
    assert children == DEPENDENT_TABLES
    for child, parent, parent_has_shop in rows:
        if child in DEPENDENT_TABLES and parent not in ("users", "public.users"):
            assert parent_has_shop, (child, parent)


def test_the_guarded_tables_are_the_only_user_triggers_on_shop_data(owner_engine):
    with owner_engine.connect() as conn:
        triggered = set(
            conn.execute(
                text(
                    "SELECT DISTINCT t.tgrelid::regclass::text FROM pg_trigger t "
                    "JOIN pg_attribute a ON a.attrelid = t.tgrelid AND a.attname = 'shop_id' "
                    "WHERE NOT t.tgisinternal"
                )
            ).scalars()
        )
    assert triggered == {"orders", "returns", "analytics_kpi_envelopes"}
