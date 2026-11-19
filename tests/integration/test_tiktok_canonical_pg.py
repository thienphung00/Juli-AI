"""P101 W2 t1 on real Postgres, as the runtime role (``juli_app``) under RLS.

- S-1, poll-only path: the job's ``TikTokCanonicalSync`` under the shop scope writes the
  fetched orders' lines to ``order_lines`` (platform ``tiktok``, source ``api``);
- S-1, webhook path: the targeted fetch's ``scope_each_call=True`` writes with no outer scope;
- S-3: a re-run writes nothing and leaves the same rows; another tenant sees none of them;
- S-4: a late cancel touches its order's VN day only; the reconcile queues a raw order that
  has no canonical line.

Synthetic tenants and payloads only."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ingest import tiktok_canonical as tc
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

CREATED = 1_790_000_000  # 2026-09-21 14:13:20 UTC = 21:13 VN
DAY = date(2026, 9, 21)


def _order(order_id: str, status: str = "COMPLETED", created: int = CREATED) -> dict:
    return {
        "id": order_id,
        "status": status,
        "create_time": created,
        "paid_time": created + 60,
        "payment": {"currency": "VND"},
        "recipient_address": {"name": "PII_MARKER"},
        "line_items": [
            {
                "id": f"{order_id}1",
                "product_id": "p1",
                "sku_id": "s1",
                "original_price": "100000",
                "sale_price": "90000",
                "seller_discount": "10000",
                "platform_discount": "0",
                "currency": "VND",
            },
            {
                "id": f"{order_id}2",
                "product_id": "p2",
                "sku_id": "s2",
                "original_price": "50000",
                "sale_price": "50000",
                "seller_discount": "0",
                "platform_discount": "0",
                "currency": "VND",
            },
        ],
    }


class _Days:
    def __init__(self) -> None:
        self.calls: list[frozenset[date]] = []

    async def __call__(self, session, shop_id, days) -> None:
        self.calls.append(days)


_LINES = (
    "SELECT order_ref, line_no, status, deal_price, day, source, source_rank, platform "
    "FROM public.order_lines WHERE order_ref LIKE :prefix ORDER BY order_ref, line_no"
)


async def _rows(shop_id: uuid.UUID, prefix: str):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return (await session.execute(text(_LINES), {"prefix": f"{prefix}%"})).all()


async def _poll(shop_id: uuid.UUID, orders: list[dict], days=None) -> tc.CanonicalApplyResult:
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            sync = tc.TikTokCanonicalSync(session, shop_id, days_fn=days or _Days())
            result = await sync.on_orders(orders)
            await sync.finish()
        await session.commit()
    return result


async def test_poll_path_writes_the_lines_and_a_rerun_changes_nothing(two_tenants):
    shop, other = two_tenants[0].shop_id, two_tenants[1].shop_id
    prefix = f"9{uuid.uuid4().int % 10**12:012d}"
    orders = [_order(f"{prefix}01"), _order(f"{prefix}02", status="IN_TRANSIT")]

    first = await _poll(shop, orders)
    stored = await _rows(shop, prefix)
    again = await _poll(shop, orders)

    assert (first.lines_written, again.lines_written, again.days) == (4, 0, set())
    assert await _rows(shop, prefix) == stored
    assert [(r.status, r.source, r.source_rank, r.platform, r.day) for r in stored] == [
        ("delivered", "api", 4, "tiktok", DAY),
        ("delivered", "api", 4, "tiktok", DAY),
        ("in_transit", "api", 4, "tiktok", DAY),
        ("in_transit", "api", 4, "tiktok", DAY),
    ]
    assert await _rows(other, prefix) == []


async def test_webhook_path_scopes_each_call_itself(two_tenants):
    shop = two_tenants[0].shop_id
    prefix = f"8{uuid.uuid4().int % 10**12:012d}"

    async with juli_app_session() as session:
        sync = tc.TikTokCanonicalSync(session, shop, days_fn=_Days(), scope_each_call=True)
        result = await sync.on_orders([_order(f"{prefix}01")])
        await session.commit()

    assert (result.lines_written, result.failed) == (2, 0)
    assert len(await _rows(shop, prefix)) == 2


async def test_a_late_cancel_touches_only_its_day(two_tenants):
    shop = two_tenants[0].shop_id
    prefix = f"7{uuid.uuid4().int % 10**12:012d}"
    later = CREATED + 4 * 86_400
    await _poll(shop, [_order(f"{prefix}01"), _order(f"{prefix}02", created=later)])
    days = _Days()

    result = await _poll(
        shop,
        [_order(f"{prefix}01", status="CANCELLED"), _order(f"{prefix}02", created=later)],
        days,
    )

    assert (result.lines_written, days.calls) == (2, [frozenset({DAY})])
    statuses = {(r.order_ref, r.line_no): r.status for r in await _rows(shop, prefix)}
    assert statuses[(f"{prefix}01", 0)] == "cancelled"
    assert statuses[(f"{prefix}02", 0)] == "delivered"


async def test_reconcile_queues_a_raw_order_with_no_canonical_line(two_tenants, owner_engine):
    shop = two_tenants[0].shop_id
    prefix = f"6{uuid.uuid4().int % 10**12:012d}"
    created = datetime.fromtimestamp(CREATED, tz=UTC).replace(tzinfo=None)
    with owner_engine.begin() as conn:
        for n in ("01", "02"):
            conn.execute(
                text(
                    "INSERT INTO silver.orders (id, shop_id, tiktok_order_id, status, "
                    "total_amount, currency, tiktok_created_at, update_time) VALUES "
                    "(:id, :shop, :oid, 'COMPLETED', 1, 'VND', :at, :at)"
                ),
                {"id": str(uuid.uuid4()), "shop": str(shop), "oid": f"{prefix}{n}", "at": created},
            )
    await _poll(shop, [_order(f"{prefix}01")])
    queue = tc.InMemoryRefetchQueue()

    async with juli_app_session() as session:
        async with with_shop_scope(session, shop):
            result = await tc.reconcile_shop(
                session, shop, start=DAY, end=DAY, queue=queue, days_fn=_Days()
            )

    assert f"{prefix}02" in queue.ids[shop] and f"{prefix}01" not in queue.ids[shop]
    assert result.queued >= 1 and DAY in result.gap_days
