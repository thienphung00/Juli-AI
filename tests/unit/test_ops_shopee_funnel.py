"""Juli Ops Shopee funnel checks (P98 / ADR-122 d.11.3, d.11.4): the two Ops reads.

Routes: auth (no Ops role is refused), shop scope (TikTok shop 409, unknown shop 404, another
shop's calibration rows never leak), response shape. ``funnel_check`` itself is covered where it
lives; here it is stubbed. Synthetic rows only.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from juli_backend.models.shopee_recommendations import ShopeeRecoCalibration
from juli_backend.services.ops import shopee_funnel_ops as svc
from juli_backend.services.shopee_analytics import funnel_check
from tests.support.builders import make_shop, make_user


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


async def _shop(session, platform="shopee"):
    seller = await make_user(session, email=f"seller-{uuid.uuid4().hex[:6]}@example.com")
    shop = await make_shop(session, seller, platform=platform)
    await session.commit()
    return shop.id


def _mismatch(shop_id, day, kind, metric, stored, expected, item_id=None):
    return funnel_check.Mismatch(
        shop_id, day, kind, metric, Decimal(stored), Decimal(expected), item_id=item_id
    )


def test_a_mismatch_row_names_kind_day_scope_expected_actual_and_gap():
    shop_id = uuid.uuid4()
    row = svc.mismatch_json(_mismatch(shop_id, date(2026, 11, 1), "shop_totals", "gmv", 90, 100))
    assert row == {
        "kind": "shop_totals", "day": "2026-11-01", "scope": "shop", "item_id": None,
        "source": None, "metric": "gmv", "expected": "100", "actual": "90", "gap_pct": 10.0,
    }  # fmt: skip
    product = svc.mismatch_json(
        _mismatch(shop_id, date(2026, 11, 1), "sources_sum", "orders", 3, 4, "1001")
    )
    assert product["scope"] == "product" and product["item_id"] == "1001"
    unknown = svc.mismatch_json(
        funnel_check.Mismatch(shop_id, date(2026, 11, 1), "missing_rows", "rows", Decimal(0), None)
    )
    assert unknown["gap_pct"] is None and unknown["expected"] is None


async def test_a_viewer_reads_the_funnel_check_of_the_last_n_days(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop(session)
    seen = {}

    async def fake_check_days(sess, sid, days):
        seen["shop"], seen["days"] = sid, sorted(days)
        return [_mismatch(sid, date(2026, 11, 8), "traffic", "views", 90, 100)]

    monkeypatch.setattr(funnel_check, "check_days", fake_check_days)
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        response = await client.get(
            f"/v1/ops/shops/{shop_id}/shopee/funnel-check",
            params={"days": 3, "as_of": "2026-11-09"},
        )
        too_many = await client.get(
            f"/v1/ops/shops/{shop_id}/shopee/funnel-check", params={"days": 61}
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"days", "from", "to", "tolerance_pct", "mismatches"}
    assert (body["days"], body["from"], body["to"], body["tolerance_pct"]) == (
        3,
        "2026-11-07",
        "2026-11-09",
        1.0,
    )
    assert body["mismatches"][0]["kind"] == "traffic" and body["mismatches"][0]["gap_pct"] == 10.0
    assert seen["shop"] == shop_id and seen["days"] == [date(2026, 11, d) for d in (7, 8, 9)]
    assert too_many.status_code == 422


async def test_prediction_coverage_is_per_family_and_only_this_shops(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop(session)
    other = await _shop(session)

    def row(sid, kind, metric, n, hits):
        return ShopeeRecoCalibration(
            shop_id=sid, change_kind=kind, metric=metric, n_results=n,
            coverage_n=n, coverage_hits=hits, range_scale=Decimal("1.25"),
        )  # fmt: skip

    session.add_all(
        [
            row(shop_id, "voucher", "orders", 10, 8),
            row(shop_id, "voucher", "gmv", 10, 6),
            row(shop_id, "price", "orders", 0, 0),
            row(other, "voucher", "orders", 99, 1),
        ]
    )
    await session.commit()
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shop_id}/shopee/prediction-coverage")
    app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target"] == 0.8 and body["source"] == "shopee_reco_calibrations"
    fams = {f["family"]: f for f in body["families"]}
    assert (fams["voucher"]["scored"], fams["voucher"]["inside"], fams["voucher"]["coverage"]) == (
        20,
        14,
        0.7,
    )
    assert fams["price"]["coverage"] is None  # nothing scored: no share, never 0 %
    assert {m["metric"] for m in fams["voucher"]["metrics"]} == {"orders", "gmv"}
    assert fams["voucher"]["metrics"][0]["range_scale"] == 1.25


async def test_a_tiktok_shop_is_refused_and_an_unknown_shop_is_404(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop(session, "tiktok")
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        refused = [
            await client.get(f"/v1/ops/shops/{shop_id}/shopee/{name}")
            for name in ("funnel-check", "prediction-coverage")
        ]
        unknown = await client.get(f"/v1/ops/shops/{uuid.uuid4()}/shopee/funnel-check")
    app.dependency_overrides.clear()
    assert [r.status_code for r in refused] == [409, 409]
    assert refused[0].json()["detail"]["code"] == "not_a_shopee_shop"
    assert unknown.status_code == 404


async def test_a_user_without_an_ops_role_is_refused(session, monkeypatch):
    from juli_backend.core.security import get_current_user
    from tests.support.api import build_app, client_for

    shop_id = await _shop(session)
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    stranger = await make_user(session, email="stranger@example.com")
    app = build_app(session)

    async def current():
        return stranger

    app.dependency_overrides[get_current_user] = current
    async with client_for(app) as client:
        responses = [
            await client.get(f"/v1/ops/shops/{shop_id}/shopee/{name}")
            for name in ("funnel-check", "prediction-coverage")
        ]
    app.dependency_overrides.clear()
    assert all(r.status_code in (401, 403) for r in responses)
