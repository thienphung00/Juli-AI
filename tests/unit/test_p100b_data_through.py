"""P100 B.5: "Số liệu đến dd/mm" -- each Tổng quan / Phân tích section names the last complete day
of the data it uses: the oldest of those datasets' newest days, never past the window end.
Pure helper + the two payloads (SQLite); synthetic data."""

from __future__ import annotations

from datetime import date

from juli_backend.services.shopee_analytics.data_through import SECTION_DATASETS, data_through
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

END = date(2026, 11, 13)


def _latest(**days: date) -> dict:
    return {k: {"kind": "daily", "latest_day": v} for k, v in days.items()}


def test_each_section_is_the_oldest_of_its_datasets_capped_at_the_window_end():
    latest = _latest(
        shop_overview=date(2026, 11, 14),
        traffic_overview=date(2026, 11, 9),
        order_lines=date(2026, 11, 13),
    )
    out = data_through(latest, END, ads_last=date(2026, 11, 12))
    # GMV / đơn: the shop totals only (capped at the window end); profit / costs: the ads trail
    assert out["kpis"] == "2026-11-13"
    assert out["profit"] == "2026-11-12"  # the ads cost stops at 12/11
    assert out["channels"] == "2026-11-09"  # traffic_overview trails
    assert out["plan"] == "2026-11-13"  # capped at the window end
    assert set(out) == set(SECTION_DATASETS)


def test_a_section_without_any_of_its_datasets_is_none():
    out = data_through({}, END, ads_last=None)
    assert all(v is None for v in out.values())


async def test_the_payloads_carry_data_through(session):
    from juli_backend.services.shopee_analytics import channel_split, metric_view

    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    body = await channel_split.channel_split(session, seeded.shop.id, period="7d", as_of=CUR_END)
    assert body["data_through"]["kpis"] == CUR_END.isoformat()
    assert body["data_through"]["channels"] == CUR_END.isoformat()
    view = await metric_view.metric_view(session, seeded.shop.id, period="7d", as_of=CUR_END)
    assert view["data_through"]["channels"] == CUR_END.isoformat()
    assert view["data_through"]["products"] == CUR_END.isoformat()


def test_a_stale_order_line_read_does_not_date_the_gmv_back():
    """ORY 2026-11-15: shop totals to 14/11, order lines only to 04/11. GMV / đơn read
    "đến 14/11"; Lợi nhuận / Tổng chi phí read "đến 04/11"."""
    latest = _latest(shop_overview=date(2026, 11, 14), order_lines=date(2026, 11, 4))
    out = data_through(latest, date(2026, 11, 14), ads_last=date(2026, 11, 13))
    assert out["kpis"] == "2026-11-14" and out["profit"] == "2026-11-04"
