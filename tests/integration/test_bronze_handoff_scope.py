"""The bronze append asserts its own shop scope (#1627).

WHY A NON-OWNER ROLE IS MANDATORY HERE. Postgres exempts a table's owner from
RLS, so this whole file would pass against the BROKEN code on an owner
connection. That exemption is what hid the bug for as long as the runtime owned
its tables; once #1339 moved it to `juli_app`, every bronze append whose
connection lacked `app.current_shop_id` was REFUSED rather than filtered:

    InsufficientPrivilegeError: new row violates row-level security policy
    for table "order_raw_payloads"

`mock_analytics_hourly_reconcile` hit that on every run. The sessions here are
therefore `juli_app_session(shop_id=None)` — the runtime role with no ambient
tenant context, which is the state the failing beat was actually in.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from tests.integration.two_tenant import juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="requires Postgres",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


def _order_payload(order_id: str) -> bytes:
    return json.dumps(
        {
            "id": order_id,
            "order_id": order_id,
            "create_time": int(datetime.now(tz=UTC).timestamp()),
            "order_status": "COMPLETED",
        }
    ).encode()


@pytest.mark.asyncio
async def test_the_append_succeeds_with_no_ambient_tenant_context(two_tenants):
    """The regression. Pre-fix this raises the production RLS error.

    Nothing sets a scope on this session — that is the point. The handoff must
    establish it from the shop_id it was already given.
    """
    tenant = two_tenants[0]
    tracker = BronzeAppendTracker()

    async with juli_app_session(shop_id=None) as session:
        handoff = make_targeted_fetch_bronze_handoff(
            session,
            shop_id=tenant.shop_id,
            job_token=f"test-{uuid.uuid4()}",
            tracker=tracker,
        )
        await handoff("tiktok.orders.raw", "shop-key", _order_payload(str(uuid.uuid4())))

        assert tracker.order_row_ids, (
            "the bronze append wrote nothing; with no ambient tenant context the "
            "handoff must assert its own scope rather than rely on a caller"
        )

    # Read back UNDER SCOPE. The handoff releases its scope on exit (asserted by
    # the next test), so an unscoped read here would return zero rows and say
    # nothing about durability — RLS filtering is not absence.
    async with juli_app_session(shop_id=tenant.shop_id) as reader:
        written = (
            await reader.execute(
                text(
                    "SELECT count(*) FROM bronze.order_raw_payloads WHERE id = ANY(:ids)"
                ).bindparams(ids=tracker.order_row_ids)
            )
        ).scalar()

    assert written == len(tracker.order_row_ids), "rows were not durable under the asserted scope"


@pytest.mark.asyncio
async def test_the_scope_does_not_leak_past_the_append(two_tenants):
    """A scope that outlived the append would be worse than the bug it fixes.

    The session is reused across the whole fetch plan, so a leaked
    `app.current_shop_id` would grant later work this shop's visibility.
    """
    tenant = two_tenants[0]
    tracker = BronzeAppendTracker()

    async with juli_app_session(shop_id=None) as session:
        handoff = make_targeted_fetch_bronze_handoff(
            session,
            shop_id=tenant.shop_id,
            job_token=f"test-{uuid.uuid4()}",
            tracker=tracker,
        )
        await handoff("tiktok.orders.raw", "shop-key", _order_payload(str(uuid.uuid4())))

        scope_after = (await session.execute(text("SELECT app_current_shop_id()::text"))).scalar()

    assert scope_after is None, (
        f"the shop scope leaked past the append (app.current_shop_id={scope_after!r}); "
        "later work on this session would inherit this tenant's visibility"
    )


@pytest.mark.asyncio
async def test_an_unparseable_payload_is_skipped_without_scoping_anything(two_tenants):
    """The early return must stay early — no scope taken for a payload we drop."""
    tenant = two_tenants[0]
    tracker = BronzeAppendTracker()

    async with juli_app_session(shop_id=None) as session:
        handoff = make_targeted_fetch_bronze_handoff(
            session,
            shop_id=tenant.shop_id,
            job_token=f"test-{uuid.uuid4()}",
            tracker=tracker,
        )
        await handoff("tiktok.orders.raw", "shop-key", b"not json")

    assert not tracker.order_row_ids, "an unparseable payload must write nothing"


@pytest.mark.asyncio
async def test_the_append_writes_under_the_shop_it_was_given(two_tenants):
    """Scoping must not become "scoped to whatever the row says".

    Writes land under the shop the handoff was constructed with, and the other
    tenant sees none of them.
    """
    mine, theirs = two_tenants[0], two_tenants[1]
    tracker = BronzeAppendTracker()

    async with juli_app_session(shop_id=None) as session:
        handoff = make_targeted_fetch_bronze_handoff(
            session,
            shop_id=mine.shop_id,
            job_token=f"test-{uuid.uuid4()}",
            tracker=tracker,
        )
        await handoff("tiktok.orders.raw", "shop-key", _order_payload(str(uuid.uuid4())))

    assert tracker.order_row_ids

    async with juli_app_session(shop_id=theirs.shop_id) as other:
        visible = (
            await other.execute(
                text(
                    "SELECT count(*) FROM bronze.order_raw_payloads WHERE id = ANY(:ids)"
                ).bindparams(ids=tracker.order_row_ids)
            )
        ).scalar()

    assert visible == 0, "the other tenant can see rows written under this shop's scope"
