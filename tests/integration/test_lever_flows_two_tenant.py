"""Two-tenant proof for the P10-B lever-flow tables as `juli_app` (fast track
AC-10.2, migration 080).

The SQLite tests (`tests/unit/test_lever_flows_*.py`) prove the services and
routes filter on the caller's shop. This proves the database agrees, under
row-level security, as the runtime role, with real commits:

- a flow row and a photo stored under shop A are invisible from shop B, and a
  photo token of A's resolves to nothing under B's scope;
- B can neither insert a photo, a flow, a calibration nor a day-14 verdict for
  A, and the worker's staged-URI recorder scoped to B changes nothing of A's;
- calibration is per shop: A's update leaves B at the 0.5 start.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from juli_backend.services import lever_flows
from juli_backend.services.lever_flows import measurement, photos
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.lever_flows import png

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

PRODUCT_TIKTOK_ID = "tt-lever-flow-proof"


def _set_scope_sql() -> str:
    return "SELECT set_config('app.current_shop_id', :v, false)"


@asynccontextmanager
async def committing_juli_app_session(shop_id: uuid.UUID):
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.execute(text(_set_scope_sql()).bindparams(v=str(shop_id)))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
                await session.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()


@contextmanager
def juli_app_sync_session(shop_id: uuid.UUID):
    from juli_backend.core.config.runtime import sync_database_url

    engine = create_engine(sync_database_url(os.environ["DATABASE_URL"]))
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            conn.execute(text(_set_scope_sql()), {"v": str(shop_id)})
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def photo_runs(owner_engine, two_tenants):
    """Per tenant: a product and a cover-image run with its flow row."""
    now = datetime.now(UTC).replace(tzinfo=None)
    seeded = {}
    with owner_engine.begin() as conn:
        for tenant in two_tenants:
            product_id, run_id = uuid.uuid4(), uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status, "
                    " revenue, units_sold, update_time, created_at, updated_at) "
                    "VALUES (:id, :shop, :tt, 'lever proof', 'ACTIVE', 0, 0, :now, :now, :now)"
                ),
                {
                    "id": str(product_id),
                    "shop": str(tenant.shop_id),
                    "tt": PRODUCT_TIKTOK_ID,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.workflow_runs (id, shop_id, product_id, state, status, "
                    " prompt_version, prompt_sha256, running_seconds_elapsed, cancel_requested, "
                    " subject_ref, external_wait_reason, created_at, updated_at) "
                    "VALUES (:id, :shop, :product, :state, 'waiting_external', "
                    " 'optimize_product.v3', :sha, 0, false, :product, 'photo', :now, :now)"
                ),
                {
                    "id": str(run_id),
                    "shop": str(tenant.shop_id),
                    "product": str(product_id),
                    "state": json.dumps({}),
                    "sha": "0" * 64,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.run_lever_flows (id, shop_id, workflow_run_id, kind, "
                    " lever, verify_attempts, created_at, updated_at) "
                    "VALUES (:id, :shop, :run, 'photo', 'cover_image', 0, :now, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "shop": str(tenant.shop_id),
                    "run": str(run_id),
                    "now": now,
                },
            )
            seeded[tenant.shop_id] = run_id
    return seeded


def _count(owner_engine, table: str, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM public.{table} WHERE shop_id = :shop"),  # nosec B608
            {"shop": str(shop_id)},
        ).scalar_one()


@pytest.mark.asyncio
async def test_a_photo_and_its_flow_are_invisible_and_unwritable_across_tenants(
    owner_engine, two_tenants, photo_runs
):
    tenant_a, tenant_b = two_tenants
    run_a = photo_runs[tenant_a.shop_id]
    data = png()

    async with committing_juli_app_session(tenant_a.shop_id) as session:
        photo = await lever_flows.save_photo(
            session,
            shop_id=tenant_a.shop_id,
            run_id=run_a,
            role="after",
            data=data,
            report=lever_flows.check_photo(data),
        )
        token = photo.public_token
    assert _count(owner_engine, "run_lever_photos", tenant_a.shop_id) == 1

    async with committing_juli_app_session(tenant_b.shop_id) as session:
        assert await lever_flows.get_flow(session, tenant_a.shop_id, run_a) is None
        assert await lever_flows.photo_by_token(session, tenant_a.shop_id, token) is None
        visible = (await session.execute(text("SELECT shop_id FROM public.run_lever_photos"))).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}
        with pytest.raises(Exception, match="row-level security"):
            await lever_flows.save_photo(
                session,
                shop_id=tenant_a.shop_id,
                run_id=run_a,
                role="before",
                data=data,
                report=lever_flows.check_photo(data),
            )
        await session.rollback()
        with pytest.raises(Exception, match="row-level security"):
            await lever_flows.register_flow(
                session, shop_id=tenant_a.shop_id, run_id=run_a, lever_code="flash_sale"
            )
        await session.rollback()
    assert _count(owner_engine, "run_lever_photos", tenant_a.shop_id) == 1
    assert _count(owner_engine, "run_lever_flows", tenant_a.shop_id) == 1

    # The worker's recorder under B's scope cannot stage a URI on A's photo.
    with juli_app_sync_session(tenant_b.shop_id) as session:
        photos.SqlStagedUriRecorder(session, shop_id=tenant_a.shop_id, workflow_run_id=run_a)(
            "tos-from-b"
        )
    with owner_engine.connect() as conn:
        staged = conn.execute(
            text("SELECT tiktok_uri FROM public.run_lever_photos WHERE workflow_run_id = :r"),
            {"r": str(run_a)},
        ).scalar_one()
    assert staged is None

    async with committing_juli_app_session(tenant_a.shop_id) as session:
        assert (await lever_flows.photo_by_token(session, tenant_a.shop_id, token)) is not None


@pytest.mark.asyncio
async def test_calibration_and_verdicts_are_per_shop(owner_engine, two_tenants, photo_runs):
    tenant_a, tenant_b = two_tenants
    run_a = photo_runs[tenant_a.shop_id]

    async with committing_juli_app_session(tenant_a.shop_id) as session:
        before, after = await measurement._update_calibration(
            session, tenant_a.shop_id, "cover_image", Decimal("0.9")
        )
    assert (before, after) == (Decimal("0.5"), Decimal("0.6000"))

    async with committing_juli_app_session(tenant_b.shop_id) as session:
        assert await measurement.current_calibration(
            session, tenant_b.shop_id, "cover_image"
        ) == Decimal("0.5")
        assert await measurement.current_calibration(
            session, tenant_a.shop_id, "cover_image"
        ) == Decimal("0.5"), "A's row is invisible from B"
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.run_measurement_finals (id, shop_id, workflow_run_id, "
                    " label, computed_at) VALUES (:id, :shop, :run, 'dat', now())"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id), "run": str(run_a)},
            )
        await session.rollback()
    assert _count(owner_engine, "lever_calibrations", tenant_a.shop_id) == 1
    assert _count(owner_engine, "lever_calibrations", tenant_b.shop_id) == 0
    assert _count(owner_engine, "run_measurement_finals", tenant_a.shop_id) == 0
