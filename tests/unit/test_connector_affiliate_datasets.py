"""Connector 0.3.6 affiliate datasets land in ``platform_period_metrics`` like the file lane's.

``affiliate_shop_period`` (Dữ liệu phân tích chính), ``affiliate_shop_campaigns`` (Chiến dịch mở
rộng), ``affiliate_commission_period`` (Phân tích chiến dịch) and ``affiliate_content_period``
(Phân tích Nội dung) are new; stream ``affiliate``, order type ``none``, numbers only in ``extra``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from juli_backend.models.platform_data import PlatformPeriodMetric
from juli_backend.services.privacy.payload_allowlist import allowlist_payload, ingest_endpoint
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop


def _body(rows, start="2026-10-28", end="2026-10-28"):
    return {
        "source": "extension",
        "source_version": "0.3.6",
        "captured_at": "2026-10-29T09:00:00+07:00",
        "period": {"start": start, "end": end, "granularity": "period"},
        "order_type": None,
        "rows": rows,
    }


async def test_the_shop_affiliate_day_is_one_shop_level_row(session):
    shop = await _shop(session)
    row = {
        "sales": 1250000,
        "orders": 9,
        "units": 11,
        "clicks": 340,
        "buyers": 8,
        "new_buyers": 5,
        "est_commission": 62500,
        "actual_commission": 60000,
        "roi": 20,
    }
    await _ingest(session, shop, "affiliate_shop_period", _body([row]))
    stored = [m for m in await _rows(session, PlatformPeriodMetric, shop)]
    assert len(stored) == 1
    m = stored[0]
    assert (m.dataset, m.stream, m.platform_source, m.order_type) == (
        "affiliate_shop_period",
        "affiliate",
        "affiliate_shop",
        "none",
    )
    assert (m.gmv, m.orders, m.units, m.clicks, m.buyers) == (
        Decimal("1250000"),
        Decimal("9"),
        Decimal("11"),
        Decimal("340"),
        Decimal("8"),
    )
    assert m.extra["actual_commission"] == 60000 and m.extra["est_commission"] == 62500
    assert (m.period_start, m.period_end) == (date(2026, 10, 28), date(2026, 10, 28))


async def test_shop_campaigns_commission_and_content_rows(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "affiliate_shop_campaigns",
        _body(
            [
                {
                    "campaign_id": "5001",
                    "campaign_name": "Chiến dịch mở rộng",
                    "commission_rate": 0.08,
                    "status": "Đang diễn ra",
                    "starts_on": "2026-01-03",
                    "budget": 2000000,
                }
            ],
            "2026-10-29",
            "2026-10-29",
        ),
    )
    await _ingest(
        session,
        shop,
        "affiliate_commission_period",
        _body(
            [
                {
                    "campaign_id": "5001",
                    "item_id": "24334416779",
                    "kols": 3,
                    "units": 4,
                    "sales": 480000,
                    "est_commission": 38400,
                }
            ],  # fmt: skip
            "2026-09-29",
            "2026-10-28",
        ),
    )
    await _ingest(
        session,
        shop,
        "affiliate_content_period",
        _body(
            [
                {
                    "sales": 300000,
                    "units": 3,
                    "orders": 2,
                    "contents": 4,
                    "views": 1200,
                    "likes": 40,
                    "comments": 6,
                    "gpm": 250,
                }
            ],  # fmt: skip
            "2026-09-29",
            "2026-10-28",
        ),
    )
    stored = {m.dataset: m for m in await _rows(session, PlatformPeriodMetric, shop)}
    camp = stored["affiliate_shop_campaigns"]
    assert camp.platform_source == "Chiến dịch mở rộng"
    assert camp.extra["campaign_id"] == 5001 and camp.extra["starts_ymd"] == 20260103
    assert camp.extra["commission_rate"] == 0.08 and camp.extra["budget"] == 2000000
    assert "status" not in camp.extra  # D16: strings are never stored in extra
    comm = stored["affiliate_commission_period"]
    assert comm.item_id == "24334416779" and comm.gmv == Decimal("480000")
    assert comm.extra["kols"] == 3 and comm.extra["est_commission"] == 38400
    content = stored["affiliate_content_period"]
    assert (content.gmv, content.orders) == (Decimal("300000"), Decimal("2"))
    assert content.extra["views"] == 1200 and content.extra["contents"] == 4


def test_the_raw_copy_keeps_no_field_outside_the_row_model():
    payload = _body([{"sales": 1, "display_name": "Nguyen Van A", "avatar": "x"}])
    kept = allowlist_payload("shopee", ingest_endpoint("affiliate_shop_period"), payload)
    assert kept["rows"] == [{"sales": 1}]
