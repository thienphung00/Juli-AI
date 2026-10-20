"""``card_events`` on real Postgres as ``juli_app`` (fast track P60-1a, migration 095).

ADR-107 "Amendment 2026-10-20" §2 and its Verification paragraph, layer (2):

- RLS on, ``juli_app`` granted SELECT and INSERT only, one policy per verb;
- two tenants (ADR-089): the writer under shop A's scope writes A's rows; under
  B's scope A's rows are invisible and B cannot insert a row for A;
- append-only: ``juli_app`` UPDATE / DELETE are refused;
- CHECK: ``card_id`` NULL only for ``seller_change`` / ``shadow``; a dismissal
  needs a ``reason_code``; the partial unique (``card_id``, ``event_type``) for
  single-occurrence types, and ``dedup_key`` per shop;
- the backfill as ``juli_app`` under the shop's scope, run twice = same rows;
- the migration's ``downgrade -1`` drops the table and ``upgrade head`` restores it.

Deliberately NOT marked ``migration_heavy`` (the amendment: these run at issue
tier). It downgrades one revision, so it is in
``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES`` and gets a database of its
own; ``owner_engine`` migrates that database to head.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import card_events
from juli_backend.services.card_events.backfill import backfill_shop
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)


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


def _seed_card(conn, tenant, *, product_id: uuid.UUID, workflow_key: str) -> uuid.UUID:
    card_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
            " subject_id, revision, priority, severity, title, description, "
            " recommendation_payload, status, metadata_json, computed_at, surfaced_at) "
            "VALUES (:id, :shop, :wk, 'product', :subject, 1, 1, 'high', 'Tối ưu', 'Mô tả', "
            " :payload, 'approved', '{}', :now, :now)"
        ),
        {
            "id": str(card_id),
            "shop": str(tenant.shop_id),
            "wk": workflow_key,
            "subject": str(product_id),
            "payload": json.dumps({"lever": "description"}),
            "now": NOW,
        },
    )
    return card_id


def _seed_history(conn, tenant) -> dict[str, uuid.UUID]:
    """A card approved and executed, with its approval, run and terminal event."""
    card_id = _seed_card(conn, tenant, product_id=tenant.product_id, workflow_key="ce_proof")
    run_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.action_card_approvals (id, action_card_id, approved_by_user_id, "
            " approved_at, card_snapshot) VALUES (:id, :card, :user, :at, '{}')"
        ),
        {
            "id": str(uuid.uuid4()),
            "card": str(card_id),
            "user": str(tenant.user_id),
            "at": NOW.replace(tzinfo=None),
        },
    )
    conn.execute(
        text(
            "INSERT INTO public.workflow_runs (id, shop_id, product_id, action_card_id, state, "
            " status, stop_reason, prompt_version, prompt_sha256, running_seconds_elapsed, "
            " cancel_requested, subject_ref, completed_at, created_at, updated_at) "
            "VALUES (:id, :shop, :product, :card, '{}', 'completed', 'final_response', "
            " 'optimize_product.v3', :sha, 0, false, :ref, :done, :created, :created)"
        ),
        {
            "id": str(run_id),
            "shop": str(tenant.shop_id),
            "product": str(tenant.product_id),
            "card": str(card_id),
            "sha": "0" * 64,
            "ref": f"ce-{run_id.hex[:12]}",
            "done": NOW + timedelta(hours=1),
            "created": NOW.replace(tzinfo=None),
        },
    )
    conn.execute(
        text(
            "INSERT INTO public.workflow_run_events (id, workflow_run_id, sequence_number, "
            " event_type, timestamp, payload, v) "
            "VALUES (:id, :run, 0, 'workflow.completed', :at, :payload, 1)"
        ),
        {
            "id": str(uuid.uuid4()),
            "run": str(run_id),
            "at": NOW + timedelta(hours=1),
            "payload": json.dumps({"status": "completed", "stop_reason": "final_response"}),
        },
    )
    return {"card": card_id, "run": run_id}


@pytest.fixture(scope="module")
def seeded(owner_engine, two_tenants):
    with owner_engine.begin() as conn:
        return {tenant.shop_id: _seed_history(conn, tenant) for tenant in two_tenants}


def _count(owner_engine, shop_id: uuid.UUID, **where: str) -> int:
    clauses = "".join(f" AND {k} = :{k}" for k in where)
    with owner_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM public.card_events WHERE shop_id = :shop{clauses}"),  # nosec B608
            {"shop": str(shop_id), **where},
        ).scalar_one()


def test_rls_on_and_juli_app_may_only_select_and_insert(owner_engine):
    with owner_engine.connect() as conn:
        rls = conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.card_events'::regclass")
        ).scalar_one()
        grants = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = 'card_events' "
                    "AND grantee = :role"
                ),
                {"role": RUNTIME_ROLE},
            )
        }
        policies = {
            row[0]
            for row in conn.execute(
                text("SELECT cmd FROM pg_policies WHERE tablename = 'card_events'")
            )
        }
    assert rls is True
    assert grants == {"SELECT", "INSERT"}
    assert policies == {"SELECT", "INSERT"}


@pytest.mark.asyncio
async def test_the_writer_writes_only_under_its_own_shop(owner_engine, two_tenants, seeded):
    tenant_a, tenant_b = two_tenants
    card_a = seeded[tenant_a.shop_id]["card"]
    from juli_backend.models.models import ActionCard

    async with app_session(tenant_a.shop_id) as session:
        card = await session.get(ActionCard, card_a)
        assert card is not None
        await card_events.record_proposed(session, card, occurred_at=NOW, model_version="rules:t")
        await session.commit()
    assert _count(owner_engine, tenant_a.shop_id, event_type="proposed") == 1

    async with app_session(tenant_b.shop_id) as session:
        visible = (await session.execute(text("SELECT shop_id FROM public.card_events"))).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}
        # A's card is invisible to B, so the writer finds nothing to write ...
        assert await session.get(ActionCard, card_a) is None
        # ... and a raw insert for A is refused by RLS.
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.card_events (id, card_id, shop_id, workflow_key, "
                    " subject_type, subject_id, event_type, actor, occurred_at, source, "
                    " payload, schema_version, dedup_key) "
                    "VALUES (:id, NULL, :shop, 'natural', 'product', 'tt', 'seller_change', "
                    " 'seller', now(), 'live', '{}', 1, :key)"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id), "key": "b-for-a"},
            )
        await session.rollback()
    assert _count(owner_engine, tenant_a.shop_id) == 1


@pytest.mark.asyncio
async def test_a_refused_live_write_leaves_the_callers_transaction_usable(
    owner_engine, two_tenants, seeded, caplog
):
    """RLS refuses B's write for A's card inside the writer's SAVEPOINT: logged, not
    raised, and the caller's transaction goes on to commit its own work."""
    tenant_a, tenant_b = two_tenants
    from juli_backend.models.models import ActionCard

    foreign = ActionCard(
        id=seeded[tenant_a.shop_id]["card"],
        shop_id=tenant_a.shop_id,
        workflow_key="ce_proof",
        subject_type="product",
        subject_id=str(tenant_a.product_id),
    )
    before = _count(owner_engine, tenant_a.shop_id)
    async with app_session(tenant_b.shop_id) as session:
        await card_events.record_dismissed(session, foreign, occurred_at=NOW)
        assert "card_event_write_failed" in caplog.text
        # Still usable: the caller's own write lands.
        await card_events.record_proposed(
            session,
            ActionCard(
                id=seeded[tenant_b.shop_id]["card"],
                shop_id=tenant_b.shop_id,
                workflow_key="ce_proof",
                subject_type="product",
                subject_id=str(tenant_b.product_id),
                title="t",
                description="d",
                recommendation_payload="{}",
                revision=1,
                priority=1,
                severity="high",
            ),
            occurred_at=NOW,
            model_version="rules:t",
        )
        await session.commit()
    assert _count(owner_engine, tenant_a.shop_id) == before
    assert _count(owner_engine, tenant_b.shop_id, event_type="proposed") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE public.card_events SET payload = '{}' WHERE shop_id = :shop",
        "DELETE FROM public.card_events WHERE shop_id = :shop",
    ],
)
async def test_juli_app_cannot_update_or_delete(owner_engine, two_tenants, seeded, statement):
    tenant_a, _ = two_tenants
    before = _count(owner_engine, tenant_a.shop_id)
    assert before > 0  # the writer test left A a row to try it on
    async with app_session(tenant_a.shop_id) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(text(statement), {"shop": str(tenant_a.shop_id)})
        await session.rollback()
    assert _count(owner_engine, tenant_a.shop_id) == before


def _insert(conn, tenant, **overrides):
    values = {
        "id": str(uuid.uuid4()),
        "card": None,
        "shop": str(tenant.shop_id),
        "event_type": "seller_change",
        "reason": None,
        "key": uuid.uuid4().hex,
    }
    values.update(overrides)
    conn.execute(
        text(
            "INSERT INTO public.card_events (id, card_id, shop_id, workflow_key, subject_type, "
            " subject_id, event_type, actor, occurred_at, source, model_version, reason_code, "
            " payload, schema_version, dedup_key) "
            "VALUES (:id, :card, :shop, 'natural', 'product', 'tt', :event_type, 'seller', "
            " now(), 'live', NULL, :reason, '{}', 1, :key)"
        ),
        values,
    )


def test_card_id_may_be_null_only_for_seller_change_and_shadow(owner_engine, two_tenants):
    tenant_a, _ = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, tenant_a, event_type="seller_change")
        _insert(conn, tenant_a, event_type="shadow")
    for event_type in ("accepted", "proposed", "executed"):
        with pytest.raises(IntegrityError, match="ck_card_events_card_id"):
            with owner_engine.begin() as conn:
                _insert(conn, tenant_a, event_type=event_type)
    assert _count(owner_engine, tenant_a.shop_id, event_type="shadow") == 1
    assert _count(owner_engine, tenant_a.shop_id, event_type="accepted") == 0


def test_dismissal_reason_and_uniqueness(owner_engine, two_tenants, seeded):
    tenant_a, _ = two_tenants
    card = str(seeded[tenant_a.shop_id]["card"])
    with pytest.raises(IntegrityError, match="ck_card_events_dismissed_reason"):
        with owner_engine.begin() as conn:
            _insert(conn, tenant_a, card=card, event_type="dismissed")
    with pytest.raises(IntegrityError, match="ck_card_events_reason_code"):
        with owner_engine.begin() as conn:
            _insert(conn, tenant_a, card=card, event_type="dismissed", reason="bored")
    with owner_engine.begin() as conn:
        _insert(conn, tenant_a, card=card, event_type="dismissed", reason="later")
    # Single per card: a second dismissal under another key is refused ...
    with pytest.raises(IntegrityError, match="uq_card_events_card_single"):
        with owner_engine.begin() as conn:
            _insert(conn, tenant_a, card=card, event_type="dismissed", reason="not_needed")
    # ... a per-run event is not (a card can be approved again after a failed run) ...
    with owner_engine.begin() as conn:
        _insert(conn, tenant_a, card=card, event_type="accepted")
        _insert(conn, tenant_a, card=card, event_type="accepted")
    # ... and a dedup key is unique per shop.
    with pytest.raises(IntegrityError, match="uq_card_events_dedup"):
        with owner_engine.begin() as conn:
            _insert(conn, tenant_a, key="same")
            _insert(conn, tenant_a, key="same")
    assert _count(owner_engine, tenant_a.shop_id, event_type="dismissed") == 1
    assert _count(owner_engine, tenant_a.shop_id, event_type="accepted") == 2


@pytest.mark.asyncio
async def test_backfill_as_juli_app_twice_is_the_same_rows(owner_engine, two_tenants, seeded):
    tenant_a, tenant_b = two_tenants
    before_b = _count(owner_engine, tenant_b.shop_id)

    async def run() -> dict:
        async with app_session(tenant_a.shop_id) as session:
            async with with_shop_scope(session, tenant_a.shop_id):
                report = await backfill_shop(session, tenant_a.shop_id)
            await session.commit()
        return report.as_dict()

    first = await run()
    after_first = _count(owner_engine, tenant_a.shop_id, source="backfill")
    second = await run()
    assert _count(owner_engine, tenant_a.shop_id, source="backfill") == after_first
    assert first["inserted_total"] == after_first > 0
    assert second["inserted_total"] == 0
    for event_type in ("shown", "accepted", "executed"):
        assert _count(owner_engine, tenant_a.shop_id, event_type=event_type, source="backfill") == 1
    # The live `proposed` row from the writer test (when it ran first) is kept, not doubled.
    assert _count(owner_engine, tenant_a.shop_id, event_type="proposed") == 1
    assert _count(owner_engine, tenant_b.shop_id) == before_b


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: down to 094 (below 095), then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def exists() -> bool:
        with owner_engine.connect() as conn:
            return (
                conn.execute(text("SELECT to_regclass('public.card_events')")).scalar_one()
                is not None
            )

    def head() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    # P60-1b put 096_change_attribution on top: down to 094 crosses both.
    assert head() == "096_change_attribution" and exists()
    command.downgrade(cfg, "094_user_privacy_and_consent")
    assert head() == "094_user_privacy_and_consent" and not exists()
    command.upgrade(cfg, "head")
    assert head() == "096_change_attribution" and exists()
