"""W3 t1 (owner W3-Q4 = D): the A-34 channel blocks kept per product per day, and the one
automatic 90-day re-read that fills the days stored before. Synthetic data only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pytest

from juli_backend.integrations.tiktok.mapping import (
    A34_BLOCKS_KEY,
    expand_analytics_product_detail,
    expand_analytics_product_list_item,
    merge_product_analytics_rows,
)
from juli_backend.workers.services.polling.analytics_range import (
    BLOCKS_REREAD_DAYS,
    BLOCKS_REREAD_STATE_KEY,
    reread_product_blocks,
)
from tests.support.shop_ingestion_fakes import FakeRateLimiter
from tests.support.tiktok_a34 import a34_row

DAY = date(2026, 11, 10)
BLOCKS = (
    "seller_product_card_performance",
    "shop_tab_performance",
    "seller_video_performance",
    "seller_live_performance",
    "affiliate_total_performance",
    "affiliate_video_performance",
    "affiliate_live_performance",
    "total_performance",
)


def _list_row(product: str = "p1", day: date = DAY) -> dict[str, Any] | None:
    return expand_analytics_product_list_item(
        a34_row(product),
        start_date=day.isoformat(),
        end_date=(day + timedelta(days=1)).isoformat(),
        synced_at=1_700_000_000,
    )


# -------------------------------------------------------------------------------- mapping


def test_the_list_row_keeps_every_channel_block():
    row = _list_row()
    assert row is not None
    blocks = row["traffic_breakdown"][A34_BLOCKS_KEY]
    assert set(blocks) == set(BLOCKS)
    card = blocks["seller_product_card_performance"]
    assert card["product_impressions"] == 1000 and card["attributed_sku_orders"] == 2
    assert card["attributed_gmv"] == "200000", "money is kept as its amount"
    assert blocks["shop_tab_performance"]["shop_tab_gmv"] == "120000"


def test_no_unique_field_is_stored():
    blocks = _list_row()["traffic_breakdown"][A34_BLOCKS_KEY]
    assert not [k for b in blocks.values() for k in b if k.startswith("unique_")]


def test_the_existing_list_row_fields_are_unchanged():
    row = _list_row()
    assert row["gmv"] == "450000" and row["orders_count"] == 4 and row["sku_orders"] == 4
    assert row["traffic_breakdown"]["A34_TOTAL"] == {
        "add_cart_count": 3,
        "clicks": 100,
        "impressions": 2000,
    }


def test_a_row_without_blocks_stores_none():
    item = {"id": "p9", "total_performance": {"gmv": {"amount": "0", "currency": "VND"}}}
    row = expand_analytics_product_list_item(
        item, start_date="2026-11-10", end_date="2026-11-11", synced_at=1
    )
    assert row is not None
    blocks = (row.get("traffic_breakdown") or {}).get(A34_BLOCKS_KEY)
    assert blocks == {"total_performance": {"gmv": "0"}}


def test_the_merge_keeps_the_detail_content_types_and_adds_the_blocks():
    detail = expand_analytics_product_detail(
        {
            "performance": {
                "intervals": [
                    {
                        "start_date": DAY.isoformat(),
                        "end_date": (DAY + timedelta(days=1)).isoformat(),
                        "sales": {"gmv": {"amount": "450000", "currency": "VND"}, "orders": 4},
                        "traffic": {
                            "breakdowns": [
                                {
                                    "content_type": "VIDEO",
                                    "traffic": {"impressions": 400, "ctr": "0.05"},
                                }
                            ]
                        },
                    }
                ]
            }
        },
        synced_at=1_700_000_000,
        product_id="p1",
    )
    merged = merge_product_analytics_rows(detail, _list_row())
    keys = set(merged[0]["traffic_breakdown"])
    assert {"VIDEO", "A34_TOTAL", A34_BLOCKS_KEY} <= keys


# -------------------------------------------------------------------------------- re-read


@dataclass
class _Analytics:
    """A-34 per day (the synthetic rows) and A-33 daily intervals for the asked range."""

    products: tuple[str, ...] = ("p1", "p2")
    calls: dict[str, list[tuple[str, str]]] = field(
        default_factory=lambda: {"list": [], "detail": []}
    )
    fail_detail: bool = False

    def list_product_performance_all(self, *, start_date_ge: str, end_date_lt: str) -> list[dict]:
        self.calls["list"].append((start_date_ge, end_date_lt))
        return [a34_row(p) for p in self.products]

    def get_product_performance(self, *, product_id: str, start_date_ge: str, end_date_lt: str):
        self.calls["detail"].append((product_id, start_date_ge))
        if self.fail_detail:
            from juli_backend.integrations.tiktok import TikTokAPIError

            raise TikTokAPIError(36009003, "busy")
        start, end = date.fromisoformat(start_date_ge), date.fromisoformat(end_date_lt)
        days = [start + timedelta(days=i) for i in range((end - start).days)]
        return {
            "performance": {
                "intervals": [
                    {
                        "start_date": d.isoformat(),
                        "end_date": (d + timedelta(days=1)).isoformat(),
                        "sales": {"gmv": {"amount": "450000", "currency": "VND"}, "orders": 4},
                        "traffic": {
                            "breakdowns": [
                                {
                                    "content_type": "PRODUCT_CARD",
                                    "traffic": {"impressions": 1000, "ctr": "0.05"},
                                }
                            ]
                        },
                    }
                    for d in days
                ]
            }
        }


class _Handoff:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def __call__(self, channel: str, shop_key: str, payload: bytes) -> None:
        import json

        self.rows.append(json.loads(payload))


async def _no_sleep(_s: float) -> None:
    return None


async def _reread(analytics, state, *, today, limiter=None, handoff=None):
    return await reread_product_blocks(
        resource=analytics,
        rate_limiter=limiter or FakeRateLimiter(),
        handoff_fn=handoff or _Handoff(),
        app_id="app",
        shop_id="tt-shop",
        sync_state=state,
        today=today,
        sleep=_no_sleep,
        window_days=3,
    )


async def test_the_reread_merges_each_day_list_into_the_detail_rows_and_moves_the_marker():
    analytics, handoff, state = _Analytics(), _Handoff(), {}
    today = date(2026, 11, 23)
    result = await _reread(analytics, state, today=today, handoff=handoff)
    assert result is not None and result.complete
    assert len(analytics.calls["list"]) == 3, "one A-34 list call per day"
    assert len(analytics.calls["detail"]) == 2, "one A-33 detail call per product per window"
    assert len(handoff.rows) == 2 * 3
    for row in handoff.rows:
        keys = set(row["traffic_breakdown"])
        assert {"PRODUCT_CARD", "A34_TOTAL", A34_BLOCKS_KEY} <= keys
    assert state[BLOCKS_REREAD_STATE_KEY] == (today - timedelta(days=3)).toordinal()
    assert result.days == [today - timedelta(days=d) for d in (3, 2, 1)]


async def test_the_reread_walks_back_window_by_window_and_stops_at_ninety_days():
    analytics, state = _Analytics(), {}
    today = date(2026, 11, 23)
    runs = 0
    while await _reread(analytics, state, today=today) is not None:
        runs += 1
        assert runs <= 40
    assert runs == BLOCKS_REREAD_DAYS // 3
    assert (
        state[BLOCKS_REREAD_STATE_KEY] == (today - timedelta(days=BLOCKS_REREAD_DAYS)).toordinal()
    )
    first_listed = min(date.fromisoformat(s) for s, _ in analytics.calls["list"])
    assert first_listed == today - timedelta(days=BLOCKS_REREAD_DAYS)


async def test_a_failed_detail_hands_off_nothing_and_keeps_the_marker():
    analytics, handoff, state = _Analytics(fail_detail=True), _Handoff(), {}
    result = await _reread(analytics, state, today=date(2026, 11, 23), handoff=handoff)
    assert result is not None and not result.complete
    assert handoff.rows == [], "a list row alone would wipe the stored A-33 content types"
    assert BLOCKS_REREAD_STATE_KEY not in state


async def test_a_rate_limited_list_keeps_the_marker():
    limiter = FakeRateLimiter()
    limiter.refuse.add("/analytics/202605/shop_products/performance")
    state: dict[str, Any] = {}
    result = await _reread(_Analytics(), state, today=date(2026, 11, 23), limiter=limiter)
    assert result is not None and not result.complete
    assert BLOCKS_REREAD_STATE_KEY not in state


# ----------------------------------------------------------------------------- sync state


@pytest.mark.parametrize("value", [739_000])
async def test_the_marker_round_trips_through_the_sync_state_table(session, value):
    from juli_backend.repositories.tiktok_credentials import TikTokSyncStateRepo
    from tests.support.builders import make_shop, make_user

    shop = await make_shop(session, await make_user(session), platform="tiktok")
    repo = TikTokSyncStateRepo(session)
    await repo.save(shop.id, {BLOCKS_REREAD_STATE_KEY: value})
    assert (await repo.load(shop.id))[BLOCKS_REREAD_STATE_KEY] == value
