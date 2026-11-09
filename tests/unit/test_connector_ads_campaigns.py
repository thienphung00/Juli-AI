"""Connector 0.3.7: each ad campaign's settings and its edit-page limits land as snapshots.

``ads_campaign_settings`` (the Quảng cáo list: type, state, run dates, budget, ROAS target,
bidding, placement, what Shopee lets you edit) and ``ads_campaign_detail`` (an ongoing
campaign's edit page: products, ROAS estimate and bounds, budget limits, spend so far) go to
``platform_period_metrics`` (stream ``ads``, one row per campaign per capture day, no migration).
``ads_campaign_settings`` (the read) merges the newest of both per campaign for the builder.
"""

from __future__ import annotations

from datetime import date

from juli_backend.models.platform_data import PlatformPeriodMetric
from juli_backend.services.ingest.mapping import campaign_segment
from juli_backend.services.privacy.payload_allowlist import allowlist_payload, ingest_endpoint
from juli_backend.services.shopee_builder.ads_campaigns import ads_campaign_settings
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop


def _body(rows, day="2026-10-28"):
    return {
        "source": "extension",
        "source_version": "0.3.7",
        "captured_at": f"{day}T09:00:00+07:00",
        "period": {"start": day, "end": day, "granularity": "period"},
        "order_type": None,
        "rows": rows,
    }


SETTING = {
    "campaign_id": "7001",
    "campaign_name": "Túi Bio · ROAS",
    "campaign_type": "product_manual",
    "state": "ongoing",
    "starts_at": "2026-10-01T00:00:00",
    "daily_budget": 186090,
    "total_budget": 0,
    "roi_two_target": 5.3,
    "item_id": "27933768174",
    "product_placement": "all",
    "bidding_strategy": "roi_two",
    "editable": ["status", "budget", "time", "roi_two_target"],
    "is_group": False,
}

DETAIL = {
    "campaign_id": "7001",
    "product_selection": "manual",
    "rapid_boost": True,
    "item_ids": ["27933768174"],
    "item_count": 1,
    "out_of_stock_count": 0,
    "roas_estimate_low": 5.32,
    "roas_estimate_high": 8.44,
    "roas_recommended": 5.3,
    "roas_exact": 7.0,
    "roas_exact_percentile": 50,
    "roas_low": 5.3,
    "roas_low_percentile": 20,
    "roas_high": 8.4,
    "roas_high_percentile": 80,
    "roas_min": 1.5,
    "roas_max": 30,
    "roas_daily_edits": 0,
    "budget_min": 100000,
    "budget_max": 100000000,
    "budget_recommended": 186090,
    "budget_low_threshold": 111654,
    "budget_multiple": 1000,
    "budget_allow_decrease": True,
    "total_expense": 1520000,
    "today_expense": 32162,
    "max_7d_expense": 210000,
    "avg_7d_expense": 98000,
}


async def test_settings_and_detail_are_one_row_per_campaign_per_capture_day(session):
    shop = await _shop(session)
    await _ingest(session, shop, "ads_campaign_settings", _body([SETTING]))
    await _ingest(session, shop, "ads_campaign_detail", _body([DETAIL]))
    stored = {m.dataset: m for m in await _rows(session, PlatformPeriodMetric, shop)}
    s = stored["ads_campaign_settings"]
    assert (s.stream, s.segment, s.order_type) == ("ads", campaign_segment("7001"), "none")
    assert s.platform_source == "Túi Bio · ROAS"
    assert (s.period_start, s.period_end) == (date(2026, 10, 28), date(2026, 10, 28))
    assert s.extra["campaign_id"] == "7001" and s.extra["state"] == "ongoing"
    assert s.extra["starts_at"] == "2026-10-01T00:00:00" and s.extra.get("ends_at") is None
    assert s.extra["daily_budget"] == 186090 and s.extra["roi_two_target"] == 5.3
    assert s.extra["editable"] == ["status", "budget", "time", "roi_two_target"]
    d = stored["ads_campaign_detail"]
    assert d.segment == campaign_segment("7001") and d.extra["budget_min"] == 100000
    assert d.extra["roas_low"] == 5.3 and d.extra["roas_high"] == 8.4
    assert d.extra["item_ids"] == ["27933768174"]


async def test_the_read_merges_the_newest_settings_and_detail_per_campaign(session):
    shop = await _shop(session)
    await _ingest(session, shop, "ads_campaign_settings", _body([SETTING], "2026-10-27"))
    newer = {**SETTING, "daily_budget": 200000, "state": "paused"}
    other = {**SETTING, "campaign_id": "7002", "campaign_name": "Combo", "state": "ended"}
    await _ingest(session, shop, "ads_campaign_settings", _body([newer, other], "2026-10-28"))
    await _ingest(session, shop, "ads_campaign_detail", _body([DETAIL], "2026-10-28"))
    got = await ads_campaign_settings(session, shop.id)
    by_id = {c["campaign_id"]: c for c in got}
    assert set(by_id) == {"7001", "7002"}
    first = by_id["7001"]
    assert first["daily_budget"] == 200000 and first["state"] == "paused"
    assert first["captured_on"] == "2026-10-28"
    assert first["detail"]["budget_recommended"] == 186090
    assert first["detail"]["roas_estimate_low"] == 5.32
    assert by_id["7002"]["detail"] is None
    assert by_id["7002"]["campaign_name"] == "Combo"


def test_the_raw_copy_keeps_only_the_row_model_fields():
    row = {**SETTING, "image": "https://cf.shopee.vn/file/x", "shopee_username": "someone"}
    kept = allowlist_payload("shopee", ingest_endpoint("ads_campaign_settings"), _body([row]))
    assert "image" not in kept["rows"][0] and "shopee_username" not in kept["rows"][0]
    assert kept["rows"][0]["campaign_id"] == "7001"
