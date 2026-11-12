"""Juli Ops Shopee dashboards (ADR-117 step 4): rules and routes.

The SQL aggregation runs on Postgres (``tests/integration/test_ops_shopee_dashboards_db.py``:
``date_trunc`` / ``jsonb_typeof``); here the pure rules (flow grouping, the ROAS alert,
date ranges) and the routes' access checks, with the service stubbed. Synthetic rows only.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.ops import shopee_dashboards as dash
from tests.support.builders import make_shop, make_user


def _flow_row(stream, segment, gmv, orders=1):
    return (stream, segment, Decimal(gmv), Decimal(orders), Decimal(100), Decimal(10), Decimal(1))


def test_a_child_flow_is_never_added_to_the_total():
    body = dash.build_flows(
        [
            _flow_row("product_card", "all", 1000),
            _flow_row("product_card", "shop_page", 300),
            _flow_row("product_card", "search", 500),
            _flow_row("seller_video", "all", 200),
            _flow_row("ads", "ads_shop", 90),
        ]
    )
    assert body["total_gmv"] == 1200  # card + video only: children and the ads overlay excluded
    card = body["flows"][0]
    assert card["stream"] == "product_card" and card["gmv"] == 1000
    assert [c["label"] for c in card["children"]] == ["Tìm kiếm", "Trang shop"]
    assert body["ads_overlay"]["gmv"] == 90 and body["ads_overlay"]["in_total"] is False


def test_flows_without_a_level_one_row_do_not_invent_a_total():
    body = dash.build_flows([_flow_row("product_card", "shop_page", 300)])
    assert body["total_gmv"] == 0
    assert body["flows"][0]["has_total_row"] is False


def _days(start, values):
    return [
        (start + timedelta(days=i), "ads_auto_bid", Decimal(gmv), Decimal(cost))
        for i, (gmv, cost) in enumerate(values)
    ]


def test_roas_alert_needs_the_floor_for_enough_consecutive_days():
    low = [(120, 100)] * dash.ROAS_ALERT_MIN_DAYS  # 1.2 < 1.5
    alerts = dash.roas_alerts(_days(date(2026, 10, 1), low))
    assert len(alerts) == 1
    assert alerts[0]["ad_type"] == "ads_auto_bid" and alerts[0]["roas"] == 1.2
    assert alerts[0]["days"] == dash.ROAS_ALERT_MIN_DAYS and alerts[0]["floor"] == 1.5


def test_roas_alert_is_off_when_the_latest_day_recovers_or_the_run_is_short():
    recovered = [(120, 100)] * 6 + [(200, 100)]
    assert dash.roas_alerts(_days(date(2026, 10, 1), recovered)) == []
    assert dash.roas_alerts(_days(date(2026, 10, 1), [(120, 100)] * 4)) == []


def test_a_missing_day_ends_the_run_and_a_zero_spend_day_is_ignored():
    rows = _days(date(2026, 10, 1), [(120, 100)] * 3) + _days(date(2026, 10, 5), [(120, 100)] * 3)
    assert dash.roas_alerts(rows) == []  # 3 + gap + 3
    with_zero = _days(date(2026, 10, 1), [(120, 100)] * 4)
    with_zero.append((date(2026, 10, 5), "ads_auto_bid", Decimal(0), Decimal(0)))
    with_zero.append((date(2026, 10, 6), "ads_auto_bid", Decimal(120), Decimal(100)))
    # day 5 has no spend (ignored) but day 5 is then a gap for the consecutive rule
    assert dash.roas_alerts(with_zero) == []


def test_roas_alert_is_per_ad_type():
    rows = _days(date(2026, 10, 1), [(120, 100)] * 5) + [
        (date(2026, 10, 1) + timedelta(days=i), "ads_shop", Decimal(900), Decimal(100))
        for i in range(5)
    ]
    assert [a["ad_type"] for a in dash.roas_alerts(rows)] == ["ads_auto_bid"]


def test_range_defaults_to_the_30_days_ending_on_the_newest_day_and_is_validated():
    window = dash.resolve_range(None, None, date(2026, 10, 28))
    assert (window.start, window.end) == (date(2026, 9, 29), date(2026, 10, 28))
    with pytest.raises(dash.InvalidRange):
        dash.resolve_range(date(2026, 10, 2), date(2026, 10, 1), None)
    with pytest.raises(dash.InvalidRange):
        dash.resolve_range(date(2025, 1, 1), date(2026, 10, 1), None)


def test_months_back_and_calendar_month_detection():
    assert dash._months_back(date(2026, 10, 28), 12) == date(2025, 11, 1)
    assert dash._months_back(date(2026, 2, 3), 12) == date(2025, 3, 1)
    assert dash._is_calendar_month(date(2026, 10, 1), date(2026, 10, 28))
    assert not dash._is_calendar_month(date(2026, 9, 29), date(2026, 10, 28))
    assert not dash._is_calendar_month(date(2026, 9, 1), date(2026, 10, 1))


def test_months_prefer_daily_rows_and_period_rows_fill_missing_months():
    daily = [(date(2026, 10, 1), "product_card", "all", Decimal(5), Decimal(1))]
    period = [
        (date(2026, 10, 1), date(2026, 10, 31), "product_card", "all", Decimal(99), Decimal(9)),
        (date(2026, 9, 1), date(2026, 9, 30), "product_card", "all", Decimal(7), Decimal(2)),
        (date(2026, 9, 1), date(2026, 9, 10), "product_card", "all", Decimal(1), Decimal(1)),
        (date(2026, 8, 29), date(2026, 9, 27), "product_card", "all", Decimal(50), Decimal(5)),
    ]
    merged = dash._merge_months(daily, period, 2)
    assert merged[date(2026, 10, 1)][("product_card", "all")] == [5.0, 1.0]
    assert merged[date(2026, 9, 1)][("product_card", "all")] == [7.0, 2.0]  # longest month period
    assert date(2026, 8, 1) not in merged  # a rolling window is not a month


# -- routes ----------------------------------------------------------------------------


async def _ops_client(session, monkeypatch, role):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


async def _shop(session, platform):
    seller = await make_user(session, email=f"seller-{uuid.uuid4().hex[:6]}@example.com")
    shop = await make_shop(session, seller, platform=platform)
    await session.commit()
    return shop.id


def _stub(monkeypatch):
    calls = []

    async def products(session, shop_id, **kwargs):
        calls.append(("products", kwargs))
        return {"has_data": False}

    async def flows(session, shop_id, window, order_type):
        calls.append(("flows", window, order_type))
        return {"has_data": False}

    async def ads(session, shop_id, window, order_type):
        calls.append(("ads", window, order_type))
        return {"has_data": False}

    async def promotions(session, shop_id, window, order_type):
        calls.append(("promotions", window, order_type))
        return {"has_data": False}

    async def latest_day(session, shop_id, dataset):
        return date(2026, 10, 28)

    for fn in (products, flows, ads, promotions, latest_day):
        monkeypatch.setattr(dash, fn.__name__, fn)
    return calls


async def test_a_viewer_reads_the_four_dashboards_of_a_shopee_shop(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop(session, "shopee")
    calls = _stub(monkeypatch)
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        for name in ("products", "flows", "ads", "promotions"):
            response = await client.get(f"/v1/ops/shops/{shop_id}/shopee/{name}")
            assert response.status_code == 200, (name, response.text)
        ranged = await client.get(
            f"/v1/ops/shops/{shop_id}/shopee/ads",
            params={"from": "2026-10-01", "to": "2026-10-10", "order_type": "confirmed"},
        )
    app.dependency_overrides.clear()
    assert ranged.status_code == 200
    kinds = [c[0] for c in calls]
    assert kinds == ["products", "flows", "ads", "promotions", "ads"]
    # ads default to placed orders, flows to confirmed; the default window ends on the newest day
    assert calls[2][2] == "placed" and calls[1][2] == "confirmed"
    assert calls[1][1].end == date(2026, 10, 28)
    assert calls[4][1].start == date(2026, 10, 1) and calls[4][2] == "confirmed"


async def test_a_tiktok_shop_is_refused_with_409(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop(session, "tiktok")
    _stub(monkeypatch)
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        responses = [
            await client.get(f"/v1/ops/shops/{shop_id}/shopee/{name}")
            for name in ("products", "flows", "ads", "promotions")
        ]
        unknown = await client.get(f"/v1/ops/shops/{uuid.uuid4()}/shopee/flows")
    app.dependency_overrides.clear()
    assert [r.status_code for r in responses] == [409] * 4
    assert responses[0].json()["detail"]["code"] == "not_a_shopee_shop"
    assert unknown.status_code == 404


async def test_bad_ranges_and_order_types_are_422(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop(session, "shopee")
    _stub(monkeypatch)
    app = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{shop_id}/shopee"
    async with client_for(app) as client:
        reversed_ = await client.get(
            f"{base}/flows", params={"from": "2026-10-10", "to": "2026-10-01"}
        )
        too_long = await client.get(
            f"{base}/ads", params={"from": "2024-01-01", "to": "2026-01-01"}
        )
        bad_type = await client.get(f"{base}/ads", params={"order_type": "refunded"})
        half_period = await client.get(f"{base}/products", params={"period_from": "2026-10-01"})
        bad_limit = await client.get(f"{base}/products", params={"limit": 0})
    app.dependency_overrides.clear()
    assert [r.status_code for r in (reversed_, too_long, bad_type, half_period, bad_limit)] == [
        422
    ] * 5


async def test_a_user_without_an_ops_role_is_refused(session, monkeypatch):
    from juli_backend.core.security import get_current_user
    from tests.support.api import build_app, client_for

    shop_id = await _shop(session, "shopee")
    _stub(monkeypatch)
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    stranger = await make_user(session, email="stranger@example.com")
    app = build_app(session)

    async def current():
        return stranger

    app.dependency_overrides[get_current_user] = current
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shop_id}/shopee/flows")
    app.dependency_overrides.clear()
    assert response.status_code in (401, 403)


def test_connector_campaign_types_have_a_vietnamese_label():
    """P100: days the Connector read carry its campaign_type; ORY's DVHT table showed the raw
    keys ``product_manual`` / ``product_mpd`` beside the daily report's labelled types."""
    for key in ("product_manual", "product_mpd"):
        label = dash.AD_TYPE_LABELS[key]
        assert label != key and label.startswith("Sản phẩm · ")
