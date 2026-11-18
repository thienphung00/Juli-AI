"""The composed precedence rule (``rank_guard.ranked_set`` / ``ranked_where``) on real Postgres,
as ``juli_app`` under RLS, through the gateway: owner 2026-11-18 (API > Connector > file; a lower
rank only fills NULLs; a NULL never clears) composed with R7 (at an equal rank the newer capture
wins). ``platform_daily_metrics`` compares its own ``captured_at``; ``order_lines`` compares the
raw payloads' (the stored row referenced by its T5 name inside ``ON CONFLICT``). Synthetic
tenants and values only; the SQLite twin is ``tests/unit/test_ingest_composed_precedence.py``.

Isolation: ``shopee_tenants`` is module-scoped and every post commits, so each test writes its
OWN key -- a day of ``platform_daily_metrics``, an ``order_ref`` of ``order_lines`` -- and first
asserts that key is empty. (Sharing one key let a test start from the previous test's row.)
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from tests.integration.test_shopee_orders_db import _body as _lines_body
from tests.integration.test_shopee_orders_db import _line, _scalar
from tests.integration.test_shopee_orders_db import _post as _post_lines
from tests.integration.test_shopee_precedence_db import _body, _post, _query
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

CARD = "psd_label_product_card"
EARLY = "2026-11-03T09:20:00+07:00"
LATE = "2026-11-03T09:40:00+07:00"
ROW = (
    "SELECT gmv::int, orders::int, source, source_rank, source_version, "
    "extract(minute FROM captured_at)::int AS minute FROM public.platform_daily_metrics "
    "WHERE dataset = 'traffic_overview' AND day = :day AND segment = 'all'"
)


class _Day:
    """One test's own day (the metric key), and the posts on it."""

    def __init__(self, day: str) -> None:
        self.day = day

    def post(self, source: str, captured_at: str, **kpis) -> dict:
        rows = [{"date": self.day, "source": CARD, **kpis}]
        return _body(
            rows,
            source=source,
            day=self.day,
            source_version=f"{source}-{captured_at[14:16]}",
            captured_at=captured_at,
            order_type="confirmed",
        )

    async def send(self, shop_id, *posts) -> tuple:
        assert (
            await _query(shop_id, ROW, day=date.fromisoformat(self.day)) == []
        )  # the key starts empty
        for post in posts:
            await _post(shop_id, "traffic_overview", post)
        (row,) = await _query(shop_id, ROW, day=date.fromisoformat(self.day))
        return tuple(row)


async def test_equal_rank_a_newer_value_replaces_and_a_newer_null_keeps(shopee_tenants):
    a, _b = shopee_tenants
    on = _Day("2026-10-21")
    row = await on.send(
        a.shop_id,
        on.post("extension", EARLY, sales=900, orders=4),
        on.post("extension", LATE, sales=950),
    )
    assert row == (950, 4, "extension", 3, "extension-40", 40)


async def test_equal_rank_an_older_capture_is_ignored(shopee_tenants):
    a, _b = shopee_tenants
    on = _Day("2026-10-22")
    row = await on.send(
        a.shop_id,
        on.post("extension", LATE, sales=950),
        on.post("extension", EARLY, sales=900, orders=7),
    )
    assert row == (950, None, "extension", 3, "extension-40", 40)


async def test_a_lower_rank_fills_a_null_and_the_provenance_stays(shopee_tenants):
    a, _b = shopee_tenants
    on = _Day("2026-10-23")
    row = await on.send(
        a.shop_id,
        on.post("extension", EARLY, sales=900),
        on.post("file", LATE, sales=1000, orders=4),
    )
    assert row == (900, 4, "extension", 3, "extension-20", 20)


async def test_a_higher_rank_replaces_even_when_older(shopee_tenants):
    a, b = shopee_tenants
    on = _Day("2026-10-24")
    row = await on.send(
        a.shop_id,
        on.post("file", LATE, sales=1000, orders=4),
        on.post("extension", EARLY, sales=900),
    )
    assert row == (900, 4, "extension", 3, "extension-20", 20)
    assert await _query(b.shop_id, ROW, day=date.fromisoformat(on.day)) == []


LINE = (
    "SELECT deal_price::int, fee_fixed::int, source, source_rank, source_version "
    "FROM public.order_lines WHERE order_ref = :ref"
)


async def _stored(shop_id, ref: str) -> list[tuple]:
    return [tuple(r) for r in await _scalar(shop_id, text(LINE).bindparams(ref=ref))]


def _order(ref: str, source: str, captured_at: str, **over) -> dict:
    line = _line(ref, **over)
    for name, value in over.items():
        if value is None:
            del line[name]
    return _lines_body(
        [line],
        source=source,
        source_version=f"{source}-{captured_at[14:16]}",
        captured_at=captured_at,
    )


async def test_order_lines_compare_the_payload_captures(shopee_tenants):
    a, _b = shopee_tenants
    ref = "e" * 32
    assert await _stored(a.shop_id, ref) == []
    # equal rank (file): a newer read replaces, its missing fee keeps the stored one
    await _post_lines(a.shop_id, "order_lines", _order(ref, "file", EARLY, fee_fixed=4000))
    await _post_lines(
        a.shop_id, "order_lines", _order(ref, "file", LATE, deal_price=80000, fee_fixed=None)
    )
    assert await _stored(a.shop_id, ref) == [(80000, 4000, "file", 2, "file-40")]
    # equal rank, an older read uploaded late: ignored
    await _post_lines(a.shop_id, "order_lines", _order(ref, "file", EARLY, deal_price=70000))
    assert await _stored(a.shop_id, ref) == [(80000, 4000, "file", 2, "file-40")]
    # a higher rank (the Connector) replaces even when older
    await _post_lines(
        a.shop_id,
        "order_lines",
        _order(ref, "extension", EARLY, deal_price=85000, fee_fixed=None),
    )
    assert await _stored(a.shop_id, ref) == [(85000, 4000, "extension", 3, "extension-20")]


async def test_order_lines_a_lower_rank_only_fills_nulls(shopee_tenants):
    a, _b = shopee_tenants
    ref = "f" * 32
    assert await _stored(a.shop_id, ref) == []
    await _post_lines(a.shop_id, "order_lines", _order(ref, "extension", EARLY, fee_fixed=None))
    await _post_lines(
        a.shop_id, "order_lines", _order(ref, "file", LATE, deal_price=70000, fee_fixed=3000)
    )
    assert await _stored(a.shop_id, ref) == [(90000, 3000, "extension", 3, "extension-20")]
