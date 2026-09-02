"""A two-tenant Postgres fixture that can run work as `juli_app` (#1483 / ADR-089).

The evidence substrate for W7-bis. Every remaining slice of #1469 has to prove that a beat task
**does work** as the runtime role — not that it completes — because the failure ADR-089 exists
for is a task that finishes having read nothing. That claim needs two tenants and a session
whose row visibility is actually governed by RLS.

WHY NOT THE EXISTING FIXTURES.

`tests/integration/conftest.py` gives every integration test an `engine`/`session` pair backed
by **SQLite in-memory**, with a `schema_translate_map` folding `ops`/`bronze`/`gold`/`silver`
into the default schema. SQLite has no roles, no row-level security and no row locks, so nothing
built on those fixtures can make an isolation claim at all.

WHY `SET ROLE` RATHER THAN A SECOND CONNECTION.

`juli_app` is `NOLOGIN` in the repository and its `LOGIN` is granted out of band (ADR-086
decision 7), so CI cannot open a connection as it — there is no password and there must not be
one in git. `SET ROLE juli_app` on the superuser connection changes `current_user`, and both
RLS policy evaluation and the table-owner exemption key off `current_user`. So the role switch
puts the session under exactly the policies the deployed runtime will face. This is the
mechanism `test_two_tenant_isolation_proof.py` (#1329) already uses; it is lifted here rather
than reinvented.

WHAT THE SEEDER COVERS, AND WHY THAT IS ASSERTED.

`_seed_tenant_data` in #1329's proof documents itself as seeding "across all tenant-scoped
tables" and seeds three: `users`, `shops`, `tiktok_credentials`. The overclaim is harmless there
because that module only reads what it wrote, and actively misleading anywhere else. So this
seeder names its tables in `SEEDED_TABLES` and a test asserts every one of them actually has a
row — the coverage is checked against the database, not described in a docstring.

WHY THE CONSUMING MODULE MUST BE ISOLATED.

This seeds rows. `test_rls_policies.py` was moved onto a private database (#1425) precisely
because it asserts on unscoped global counts, and seeded rows from a module sharing the database
would corrupt that class of assertion. Any module using these fixtures belongs in
`_ISOLATED_DATABASE_MODULES`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

RUNTIME_ROLE = "juli_app"

# Every table the seeder writes. Asserted, not described — see the module
# docstring for why this is a list rather than a sentence.
SEEDED_TABLES: tuple[str, ...] = (
    "users",
    "shops",
    "tiktok_credentials",
    "products",
    "workflow_runs",
    "tool_executions",
)

# `credential_refresh_beat` selects on an expiry window, so one credential must
# fall inside it and one outside, or "found the right rows" is unfalsifiable.
_EXPIRING_SOON = timedelta(hours=1)
_EXPIRING_LATER = timedelta(days=30)

# `reaper` compares against a staleness threshold, so the same applies to runs.
# How many rows in an active status `seed_tenant` writes per tenant: two
# RUNNING and two WAITING_APPROVAL. Consumers assert against this rather than a
# literal, so adding a row to the seeder does not silently turn an isolation
# assertion elsewhere into a failure about arithmetic.
ACTIVE_RUNS_PER_TENANT = 4

_STALE_AGE = timedelta(hours=6)
_FRESH_AGE = timedelta(minutes=1)
# OPTIMIZE_PRODUCT_TERMINATION_POLICY.approval_timeout_h is 4, so 6h is
# expired and 1 minute is not.
_EXPIRED_APPROVAL_AGE = timedelta(hours=6)
_FRESH_APPROVAL_AGE = timedelta(minutes=1)


@dataclass(frozen=True)
class Tenant:
    """One seeded tenant, and the ids a test needs to assert against it."""

    user_id: uuid.UUID
    shop_id: uuid.UUID
    # Two products, one per run. `uq_workflow_runs_active_shop_product` permits
    # only ONE active run per (shop, product), and the reaper needs a stale run
    # and a fresh one both in RUNNING — so they cannot share a product. The
    # schema is right and the first version of this seeder was wrong.
    product_id: uuid.UUID
    second_product_id: uuid.UUID
    # A third, for the expired-approval run. `waiting_approval` counts as
    # active in `uq_workflow_runs_active_shop_product` (034), so it cannot
    # share a product with either of the two RUNNING rows.
    third_product_id: uuid.UUID
    fourth_product_id: uuid.UUID
    expiring_credential_id: uuid.UUID
    fresh_credential_id: uuid.UUID
    stale_run_id: uuid.UUID
    fresh_run_id: uuid.UUID
    expired_approval_run_id: uuid.UUID
    fresh_approval_run_id: uuid.UUID
    execution_id: uuid.UUID


def _database_url() -> str:
    import os

    return os.environ.get("DATABASE_URL", "").strip()


def seed_tenant(engine: Engine, *, label: str) -> Tenant:
    """Seed one complete tenant and return its identifiers.

    Writes exactly the tables in `SEEDED_TABLES`. `label` only makes the rows
    legible when a failing assertion prints them; nothing keys off it.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    tenant = Tenant(
        user_id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        second_product_id=uuid.uuid4(),
        third_product_id=uuid.uuid4(),
        fourth_product_id=uuid.uuid4(),
        expiring_credential_id=uuid.uuid4(),
        fresh_credential_id=uuid.uuid4(),
        stale_run_id=uuid.uuid4(),
        fresh_run_id=uuid.uuid4(),
        expired_approval_run_id=uuid.uuid4(),
        fresh_approval_run_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
    )

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, display_name, created_at, updated_at) "
                "VALUES (:id, :phone, :name, :now, :now)"
            ),
            {
                "id": str(tenant.user_id),
                "phone": f"+1555{tenant.user_id.hex[:7]}",
                "name": f"{label} owner",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :now, :now)"
            ),
            {
                "id": str(tenant.shop_id),
                "user_id": str(tenant.user_id),
                "name": f"{label} shop",
                "now": now,
            },
        )

        # Two credentials: one inside `credential_refresh_beat`'s window, one
        # well outside it. A seeder that produced only expiring credentials
        # would let a task that refreshes *everything* pass.
        for credential_id, expires_in in (
            (tenant.expiring_credential_id, _EXPIRING_SOON),
            (tenant.fresh_credential_id, _EXPIRING_LATER),
        ):
            conn.execute(
                text(
                    "INSERT INTO public.tiktok_credentials "
                    "(id, shop_id, access_token, refresh_token, token_expires_at, status, "
                    " refresh_count, created_at, updated_at) "
                    "VALUES (:id, :shop_id, :access, :refresh, :expires, 'active', 0, :now, :now)"
                ),
                {
                    "id": str(credential_id),
                    "shop_id": str(tenant.shop_id),
                    "access": f"access-{credential_id.hex[:8]}",
                    "refresh": f"refresh-{credential_id.hex[:8]}",
                    "expires": now + expires_in,
                    "now": now,
                },
            )

        for product_id in (
            tenant.product_id,
            tenant.second_product_id,
            tenant.third_product_id,
            tenant.fourth_product_id,
        ):
            conn.execute(
                text(
                    "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status, "
                    " revenue, units_sold, update_time, created_at, updated_at) "
                    "VALUES (:id, :shop_id, :tiktok_id, :name, 'ACTIVE', 0, 0, :now, :now, :now)"
                ),
                {
                    "id": str(product_id),
                    "shop_id": str(tenant.shop_id),
                    "tiktok_id": f"tt-{product_id.hex[:10]}",
                    "name": f"{label} product {product_id.hex[:4]}",
                    "now": now,
                },
            )

        # Four runs, in two qualifying/non-qualifying pairs — one pair per
        # reaper path. Same reasoning as the credentials: a reaper that
        # terminates everything must fail, and so must one that terminates
        # nothing. `waiting_approval` is an active status in
        # `uq_workflow_runs_active_shop_product` (034), which is why each run
        # gets its own product.
        for run_id, product_id, age, status, approval_age in (
            (tenant.stale_run_id, tenant.product_id, _STALE_AGE, "running", None),
            (tenant.fresh_run_id, tenant.second_product_id, _FRESH_AGE, "running", None),
            (
                tenant.expired_approval_run_id,
                tenant.third_product_id,
                _STALE_AGE,
                "waiting_approval",
                _EXPIRED_APPROVAL_AGE,
            ),
            (
                tenant.fresh_approval_run_id,
                tenant.fourth_product_id,
                _FRESH_AGE,
                "waiting_approval",
                _FRESH_APPROVAL_AGE,
            ),
        ):
            conn.execute(
                text(
                    "INSERT INTO public.workflow_runs "
                    "(id, shop_id, product_id, state, status, prompt_version, prompt_sha256, "
                    " running_seconds_elapsed, cancel_requested, waiting_approval_since, "
                    " created_at, updated_at) "
                    "VALUES (:id, :shop_id, :product_id, :state, :status, 'v1', :sha, "
                    " :elapsed, false, :approval_since, :created, :created)"
                ),
                {
                    "id": str(run_id),
                    "shop_id": str(tenant.shop_id),
                    "product_id": str(product_id),
                    "state": json.dumps({}),
                    "status": status,
                    "sha": "0" * 64,
                    "elapsed": int(age.total_seconds()),
                    # Aware, unlike every other stamp here. `waiting_approval_since`
                    # is `timestamp with time zone` while `created_at` is not, so a
                    # naive UTC value would be read in the server's TimeZone — under
                    # `Asia/Ho_Chi_Minh` that stores an instant 7h earlier and pushes
                    # an intentionally-fresh row past the 4h approval timeout. CI runs
                    # UTC, so the bug would surface only on a developer's machine.
                    "approval_since": (
                        None if approval_age is None else (now - approval_age).replace(tzinfo=UTC)
                    ),
                    "created": now - age,
                },
            )

        conn.execute(
            text(
                "INSERT INTO public.tool_executions "
                "(id, shop_id, approval_id, tool_name, payload_json, status, created_at, "
                " updated_at) "
                "VALUES (:id, :shop_id, :approval, :tool, :payload, 'succeeded', :then, :then)"
            ),
            {
                "id": str(tenant.execution_id),
                "shop_id": str(tenant.shop_id),
                "approval": f"approval-{tenant.execution_id.hex[:8]}",
                "tool": "update_product_price",
                # `product_id` and `price_update`, not `tiktok_product_id`:
                # impact_reader's pipeline reads `payload["product_id"]` and
                # classify_mutation_kinds keys off `price_update`. A payload
                # missing either is logged `impact_reader_execution_unclassified`
                # and skipped, so the task completes having written nothing —
                # which is the exact silent no-op this fixture exists to expose.
                # The first version of this seeder used the wrong key and the
                # coverage test did not notice: it asserted a row EXISTS, not
                # that the row is usable by the task that reads it (#1483).
                "payload": json.dumps(
                    {
                        "product_id": f"tt-{tenant.product_id.hex[:10]}",
                        "price_update": {"new_price": "19.99"},
                    }
                ),
                # Far enough back that impact_reader's elapse gate has passed.
                "then": now - timedelta(days=30),
            },
        )

    return tenant


@asynccontextmanager
async def juli_app_session(shop_id: uuid.UUID | None = None) -> AsyncIterator[AsyncSession]:
    """An async session whose row visibility is governed by RLS as `juli_app`.

    `SET ROLE` is connection-scoped, so the session is bound to one explicit
    connection rather than taken from the pool — a session that checked out a
    different connection would silently run as the owner and see everything,
    which is the failure mode most likely to make a broken test look green.

    `shop_id` sets `app.current_shop_id` for the session. It is left unset when
    None, which is the "no context" state the policies must deny on. The user
    GUC is never set here: `with_shop_scope` withholds it by design (#1478), and
    a fixture that set it would hide that.
    """
    # `async_database_url` swaps the driver to asyncpg. Passing the raw URL
    # yields "The asyncio extension requires an async driver", because a bare
    # postgresql:// resolves to psycopg2.
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(_database_url()))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            if shop_id is not None:
                await conn.execute(
                    text("SELECT set_config('app.current_shop_id', :val, false)").bindparams(
                        val=str(shop_id)
                    )
                )
            session = AsyncSession(bind=conn)
            try:
                yield session
                # Commit the CONNECTION, not just the session.
                #
                # The session is bound to a connection opened with
                # `engine.connect()`, which in SQLAlchemy 2.0 is
                # commit-as-you-go: `session.commit()` ends the session's
                # transaction but leaves the connection's open, and closing the
                # block rolls it back. Without this, every write made through
                # this fixture is silently discarded — the caller sees its own
                # success counters and the database has nothing.
                #
                # That is exactly how it shipped in #1483: the fixture was
                # verified only with reads, so nothing noticed. #1488's
                # impact_reader test found it by reporting 30 written readings
                # against a table holding zero rows.
                await conn.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()
