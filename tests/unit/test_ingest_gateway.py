"""Fast track P24 (D31.3 / D31.4): the ingest gateway and Juli Connector pairing, SQLite.

- mapping: Shopee L1 sources → Juli streams, fields → KPI columns, ``extra`` kept
- strict validation: unknown keys, percentages as rates, order type, period,
  dates, duplicate keys, clock skew, size
- idempotent re-posts (content hash), source precedence (vendor < extension)
- drift: a reported dataset is refused for the same extension version
- pairing: code → token, single use, expiry, platform / shop mismatch,
  rotation with grace, revocation (and of the rotated chain), token scope
- routes end to end, the per-shop rate limit, ``POST /v1/shops/shopee``
- migration 088 shape and the deferred tail

Values are synthetic; only Seller Centre field NAMES come from the recon notes.
The RLS proof is ``tests/integration/test_ingest_two_tenant.py``.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from juli_backend.models.ingest import (
    IngestPairingCode,
    IngestRawPayload,
    IngestToken,
    PlatformDailyMetric,
)
from juli_backend.services import ingest as svc
from juli_backend.services.ingest import gateway, mapping, pairing
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.support.api import authenticate, build_app, client_for
from tests.support.builders import make_tenant

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / "backend/src/juli_backend/database/migrations/versions"
MIGRATION = VERSIONS / "088_ingest_gateway.py"
DEFERRED = VERSIONS.parent / "deferred" / "074_users_placeholder_phone_cleanup.py"

NOW = datetime(2026, 10, 12, 3, 0)  # naive UTC = 10:00 GMT+7
DAY = date(2026, 10, 11)


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _source_row(source: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": DAY.isoformat(),
        "source": source,
        "sales": 1250000,
        "orders": 4.5,
        "units": 6,
        "buyers": 4,
        "product_impressions": 3000,
        "unique_product_impressions": 2100,
        "product_clicks": 120,
        "unique_product_clicks": 95,
        "ctr": 0.04,
        "product_clicks_to_orders_rate": 0.0375,
        "sales_per_order": 277777.78,
    }
    row.update(over)
    return row


def _body(rows: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "extension",
        "source_version": "0.1.0",
        "captured_at": "2026-10-12T09:30:00+07:00",
        "period": {"start": DAY.isoformat(), "end": DAY.isoformat(), "granularity": "day"},
        "order_type": "confirmed",
        "rows": rows,
    }
    body.update(over)
    return body


async def _shopee_tenant(session, **over: Any):
    return await make_tenant(session, platform="shopee", tiktok_shop_id=None, **over)


async def _metrics(session, shop_id) -> list[PlatformDailyMetric]:
    return list(
        (
            await session.execute(
                select(PlatformDailyMetric)
                .where(PlatformDailyMetric.shop_id == shop_id)
                .order_by(PlatformDailyMetric.stream, PlatformDailyMetric.item_id)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )


async def _count(session, model, shop_id) -> int:
    stmt = select(func.count()).select_from(model).where(model.shop_id == shop_id)
    return int((await session.execute(stmt)).scalar_one())


async def _ingest(session, shop, dataset: str, body: dict[str, Any], *, now=NOW):
    return await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset=dataset,
        body=svc.IngestBody.model_validate(body),
        token_id=None,
        now=now,
    )


# -- mapping ----------------------------------------------------------------------------


def test_every_shopee_l1_source_maps_to_a_juli_stream():
    assert mapping.SHOPEE_L1_TO_STREAM == {
        "psd_label_product_card": "product_card",
        "psd_label_seller_video": "seller_video",
        "psd_label_seller_live": "seller_live",
        "psd_label_affiliate": "affiliate",
        "psd_label_shopee_ads": "ads",
    }
    assert mapping.STREAM_LABELS["product_card"] == "Thẻ sản phẩm"
    assert mapping.STREAM_LABELS["affiliate"] == "Tiếp thị liên kết"
    assert mapping.STREAM_LABELS["ads"] == "Dịch vụ Hiển thị"
    assert mapping.OVERLAY_STREAMS == {"ads"}


def test_source_row_maps_kpis_and_keeps_every_other_field_in_extra():
    spec = mapping.dataset_spec("shopee", "traffic_overview")
    row = spec.row_model.model_validate(
        _source_row("psd_label_seller_video", video_views=900, extra={"l2_hint": "x"})
    )
    (normalized,) = mapping.normalize_rows(spec, [row])
    assert normalized.stream == "seller_video"
    assert normalized.platform_source == "psd_label_seller_video"
    assert normalized.item_id == ""
    assert normalized.kpis == {
        "impressions": Decimal("3000"),
        "clicks": Decimal("120"),
        "ctr": Decimal("0.04"),
        "orders": Decimal("4.5"),
        "gmv": Decimal("1250000"),
        "buyers": Decimal("4"),
        "units": Decimal("6"),
    }
    assert normalized.extra["video_views"] == 900
    assert normalized.extra["unique_product_clicks"] == 95
    assert normalized.extra["sales_per_order"] == pytest.approx(277777.78)
    assert normalized.extra["l2_hint"] == "x"


def test_item_performance_maps_visitors_and_add_to_cart():
    spec = mapping.dataset_spec("shopee", "item_performance")
    row = spec.row_model.model_validate(
        {
            "date": DAY.isoformat(),
            "item_id": "123456789",
            "item_name": "Sản phẩm A",
            "sales": 500000,
            "uv": 80,
            "atc_uv": 12,
            "atc_rate": 0.15,
        }
    )
    (normalized,) = mapping.normalize_rows(spec, [row])
    assert normalized.stream == "total"
    assert normalized.kpis["visitors"] == Decimal("80")
    assert normalized.kpis["add_to_cart"] == Decimal("12")
    assert normalized.extra == {"atc_rate": 0.15, "item_name": "Sản phẩm A"}


def test_shop_traffic_keeps_the_device_split_as_segment():
    spec = mapping.dataset_spec("shopee", "shop_traffic")
    row = spec.row_model.model_validate(
        {
            "date": DAY.isoformat(),
            "device": "app",
            "visitors": 40,
            "page_views": 90,
            "bounce_rate": 0.3,
        }
    )
    (normalized,) = mapping.normalize_rows(spec, [row])
    assert (normalized.stream, normalized.segment) == ("total", "app")
    assert normalized.kpis == {
        "visitors": Decimal("40"),
        "page_views": Decimal("90"),
        "bounce_rate": Decimal("0.3"),
    }


# -- validation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"rows": [_source_row("psd_label_product_card", ctr=4.0)]}, "invalid_rows"),
        ({"rows": [_source_row("psd_label_product_card", surprise=1)]}, "invalid_rows"),
        ({"rows": [_source_row("psd_label_unknown")]}, "invalid_rows"),
        ({"rows": [_source_row("psd_label_product_card", orders=-1)]}, "invalid_rows"),
        ({"rows": [_source_row("psd_label_product_card", date="2026-10-01")]}, "invalid_rows"),
        (
            {
                "rows": [
                    _source_row("psd_label_product_card"),
                    _source_row("psd_label_product_card"),
                ]
            },
            "invalid_rows",
        ),
        ({"order_type": None}, "order_type_required"),
        ({"captured_at": "2026-10-13T09:30:00+07:00"}, "captured_at_in_future"),
        (
            {"period": {"start": "2026-10-12", "end": "2026-10-13", "granularity": "day"}},
            "period_in_future",
        ),
    ],
)
async def test_invalid_posts_are_refused_and_store_nothing(session, change, code):
    _, shop = await _shopee_tenant(session)
    body = _body([_source_row("psd_label_product_card")])
    body.update(change)
    with pytest.raises(gateway.IngestRejected) as refused:
        await _ingest(session, shop, "traffic_overview", body)
    assert refused.value.code == code
    assert await _count(session, IngestRawPayload, shop.id) == 0
    assert await _count(session, PlatformDailyMetric, shop.id) == 0


def test_body_model_refuses_unknown_keys_long_periods_and_bad_versions():
    with pytest.raises(ValueError):
        svc.IngestBody.model_validate(_body([], extra_key=1))
    with pytest.raises(ValueError):
        svc.IngestBody.model_validate(
            _body([], period={"start": "2026-08-01", "end": "2026-10-11", "granularity": "day"})
        )
    with pytest.raises(ValueError):
        svc.IngestBody.model_validate(_body([], source_version="0.1 beta"))
    with pytest.raises(ValueError):
        svc.IngestBody.model_validate(_body([], captured_at="2026-10-12T09:30:00"))


async def test_shop_traffic_refuses_an_order_type(session):
    _, shop = await _shopee_tenant(session)
    body = _body([{"date": DAY.isoformat(), "device": "all", "visitors": 3}])
    with pytest.raises(gateway.IngestRejected) as refused:
        await _ingest(session, shop, "shop_traffic", body)
    assert refused.value.code == "order_type_not_allowed"
    body["order_type"] = None
    result = await _ingest(session, shop, "shop_traffic", body)
    assert result.rows == 1
    (row,) = await _metrics(session, shop.id)
    assert (row.order_type, row.segment, row.visitors) == ("none", "all", Decimal("3"))


# -- ingest -----------------------------------------------------------------------------


async def test_ingest_stores_raw_and_upserts_one_normalized_row_per_source(session):
    _, shop = await _shopee_tenant(session)
    rows = [_source_row(source) for source in mapping.SHOPEE_L1_TO_STREAM]
    result = await _ingest(session, shop, "traffic_overview", _body(rows))
    assert (result.duplicate, result.rows) == (False, 5)
    metrics = await _metrics(session, shop.id)
    assert sorted(m.stream for m in metrics) == sorted(mapping.SHOPEE_L1_TO_STREAM.values())
    card = next(m for m in metrics if m.stream == "product_card")
    assert card.gmv == Decimal("1250000")
    assert card.orders == Decimal("4.5")
    assert (card.source, card.confidence, card.order_type) == ("extension", "high", "confirmed")
    assert card.raw_payload_id == result.raw_payload_id
    raw = await session.get(IngestRawPayload, result.raw_payload_id)
    assert raw.payload["rows"][0]["source"] == "psd_label_product_card"
    assert raw.row_count == 5


async def test_a_repost_is_a_noop_whatever_its_captured_at(session):
    _, shop = await _shopee_tenant(session)
    rows = [_source_row("psd_label_product_card")]
    first = await _ingest(session, shop, "traffic_overview", _body(rows))
    again = await _ingest(
        session, shop, "traffic_overview", _body(rows, captured_at="2026-10-12T09:45:00+07:00")
    )
    assert again.duplicate is True
    assert again.raw_payload_id == first.raw_payload_id
    assert await _count(session, IngestRawPayload, shop.id) == 1
    assert await _count(session, PlatformDailyMetric, shop.id) == 1


async def test_new_numbers_for_the_same_day_replace_the_row(session):
    _, shop = await _shopee_tenant(session)
    await _ingest(session, shop, "traffic_overview", _body([_source_row("psd_label_product_card")]))
    await _ingest(
        session, shop, "traffic_overview", _body([_source_row("psd_label_product_card", sales=99)])
    )
    (row,) = await _metrics(session, shop.id)
    assert row.gmv == Decimal("99")
    assert await _count(session, IngestRawPayload, shop.id) == 2


async def test_order_types_are_kept_apart(session):
    _, shop = await _shopee_tenant(session)
    await _ingest(session, shop, "traffic_overview", _body([_source_row("psd_label_product_card")]))
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _body([_source_row("psd_label_product_card", sales=7)], order_type="placed"),
    )
    assert {(m.order_type, m.gmv) for m in await _metrics(session, shop.id)} == {
        ("confirmed", Decimal("1250000")),
        ("placed", Decimal("7")),
    }


async def test_a_vendor_estimate_never_replaces_the_sellers_own_numbers(session):
    _, shop = await _shopee_tenant(session)
    await _ingest(session, shop, "traffic_overview", _body([_source_row("psd_label_product_card")]))
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _body([_source_row("psd_label_product_card", sales=1)], source="vendor"),
    )
    (row,) = await _metrics(session, shop.id)
    assert (row.source, row.gmv, row.confidence) == ("extension", Decimal("1250000"), "high")

    _, other = await _shopee_tenant(session)
    await _ingest(
        session,
        other,
        "traffic_overview",
        _body([_source_row("psd_label_product_card", sales=1)], source="vendor"),
    )
    (estimated,) = await _metrics(session, other.id)
    assert estimated.confidence == "estimated"
    await _ingest(
        session, other, "traffic_overview", _body([_source_row("psd_label_product_card")])
    )
    (replaced,) = await _metrics(session, other.id)
    assert (replaced.source, replaced.confidence) == ("extension", "high")


async def test_item_rows_are_keyed_by_item_and_source(session):
    _, shop = await _shopee_tenant(session)
    rows = [
        {**_source_row("psd_label_product_card"), "item_id": "111"},
        {**_source_row("psd_label_seller_live"), "item_id": "111"},
        {**_source_row("psd_label_product_card"), "item_id": "222"},
    ]
    await _ingest(session, shop, "item_by_source", _body(rows))
    keys = {(m.item_id, m.stream) for m in await _metrics(session, shop.id)}
    assert keys == {("111", "product_card"), ("111", "seller_live"), ("222", "product_card")}


async def test_drift_stops_the_same_version_until_a_new_one_or_an_ok(session):
    _, shop = await _shopee_tenant(session)
    report = svc.DriftReport(
        platform="shopee",
        dataset="traffic_overview",
        state="drift",
        source_version="0.1.0",
        endpoint="/api/mydata/v1/product/traffic/overview/",
        unexpected=["product_card.new_metric"],
        missing=["product_card.ctr"],
    )
    await svc.report_drift(session, shop_id=shop.id, report=report, now=NOW)
    status = await svc.dataset_status(session, shop_id=shop.id, platform="shopee")
    entry = next(s for s in status if s["dataset"] == "traffic_overview")
    assert entry["drift"] == "drift"
    assert entry["drift_detail"]["missing"] == ["product_card.ctr"]
    with pytest.raises(gateway.IngestRejected) as refused:
        await _ingest(
            session, shop, "traffic_overview", _body([_source_row("psd_label_product_card")])
        )
    assert (refused.value.code, refused.value.status) == ("dataset_in_drift", 409)
    # Another dataset is not affected; a new extension version is accepted.
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _body([_source_row("psd_label_product_card")], source_version="0.1.1"),
    )
    await svc.report_drift(
        session,
        shop_id=shop.id,
        report=report.model_copy(update={"state": "ok", "unexpected": [], "missing": []}),
        now=NOW,
    )
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _body([_source_row("psd_label_product_card", sales=5)]),
    )


async def test_status_lists_every_dataset_with_the_last_ingest(session):
    _, shop = await _shopee_tenant(session)
    await _ingest(session, shop, "traffic_overview", _body([_source_row("psd_label_product_card")]))
    status = await svc.dataset_status(session, shop_id=shop.id, platform="shopee")
    assert [s["dataset"] for s in status] == [
        "item_by_source",
        "item_performance",
        "shop_traffic",
        "traffic_overview",
    ]
    overview = status[-1]
    assert overview["last_row_count"] == 1
    assert overview["last_period_end"] == "2026-10-11"
    assert overview["drift"] == "ok"
    assert status[0]["last_ingest_at"] is None


# -- pairing ----------------------------------------------------------------------------


async def _code(session, shop, now=NOW) -> str:
    return (await svc.create_pairing_code(session, shop=shop, user_id=shop.user_id, now=now)).code


async def test_a_code_is_short_hashed_single_use_and_expires(session):
    _, shop = await _shopee_tenant(session)
    code = await _code(session, shop)
    assert len(code) == 11 and code[5] == "-"
    stored = (await session.execute(select(IngestPairingCode))).scalars().all()
    assert [c.code_hash for c in stored] == [pairing.code_hash(code)]
    assert code.replace("-", "") not in stored[0].code_hash

    issued = await svc.redeem_pairing_code(
        session,
        code=code.lower(),
        platform="shopee",
        platform_shop_id="998877",
        client_label="Chrome · Juli Connector 0.1.0",
        now=NOW + timedelta(minutes=9),
    )
    assert issued.token.startswith(f"jci_{shop.id.hex}_")
    assert issued.expires_at == NOW + timedelta(minutes=9) + timedelta(days=90)
    token_row = await session.get(IngestToken, issued.token_id)
    assert token_row.token_hash == pairing.token_hash(issued.token)
    assert issued.token not in token_row.token_hash
    assert token_row.platform_shop_id == "998877"

    with pytest.raises(svc.PairingError) as reused:
        await svc.redeem_pairing_code(
            session, code=code, platform="shopee", platform_shop_id=None, client_label=None, now=NOW
        )
    assert reused.value.code == "invalid_code"

    late = await _code(session, shop)
    with pytest.raises(svc.PairingError):
        await svc.redeem_pairing_code(
            session,
            code=late,
            platform="shopee",
            platform_shop_id=None,
            client_label=None,
            now=NOW + timedelta(minutes=10),
        )
    with pytest.raises(svc.PairingError):
        await svc.redeem_pairing_code(
            session,
            code="ABCDE-FGHJK",
            platform="shopee",
            platform_shop_id=None,
            client_label=None,
            now=NOW,
        )


async def test_pairing_refuses_another_platform_or_another_shopee_shop(session):
    _, tiktok_shop = await make_tenant(session)
    with pytest.raises(svc.PairingError) as wrong_platform:
        await svc.redeem_pairing_code(
            session,
            code=await _code(session, tiktok_shop),
            platform="shopee",
            platform_shop_id=None,
            client_label=None,
            now=NOW,
        )
    assert wrong_platform.value.code == "platform_mismatch"

    _, shop = await _shopee_tenant(session, shopee_shop_id="111")
    with pytest.raises(svc.PairingError) as wrong_shop:
        await svc.redeem_pairing_code(
            session,
            code=await _code(session, shop),
            platform="shopee",
            platform_shop_id="222",
            client_label=None,
            now=NOW,
        )
    assert wrong_shop.value.code == "shop_mismatch"


async def test_at_most_five_live_codes_per_shop(session):
    _, shop = await _shopee_tenant(session)
    for _ in range(5):
        await _code(session, shop)
    with pytest.raises(svc.PairingError) as refused:
        await _code(session, shop)
    assert refused.value.code == "too_many_codes"
    await _code(session, shop, now=NOW + timedelta(minutes=11))


async def test_tokens_resolve_rotate_with_grace_and_revoke_the_chain(session):
    _, shop = await _shopee_tenant(session)
    issued = await svc.redeem_pairing_code(
        session,
        code=await _code(session, shop),
        platform="shopee",
        platform_shop_id=None,
        client_label=None,
        now=NOW,
    )
    principal = await svc.resolve_token(session, issued.token, NOW)
    assert principal is not None and principal.shop_id == shop.id
    assert await svc.resolve_token(session, issued.token + "x", NOW) is None
    assert await svc.resolve_token(session, "jci_nothex_" + "a" * 40, NOW) is None
    forged = f"jci_{uuid.uuid4().hex}_{issued.token.rsplit('_', 1)[1]}"
    assert await svc.resolve_token(session, forged, NOW) is None
    assert await svc.resolve_token(session, issued.token, NOW + timedelta(days=90)) is None

    rotated = await svc.rotate_token(session, principal, now=NOW)
    with pytest.raises(svc.PairingError) as twice:
        await svc.rotate_token(session, principal, now=NOW)
    assert twice.value.code == "already_rotated"
    assert await svc.resolve_token(session, issued.token, NOW + timedelta(minutes=9)) is not None
    assert await svc.resolve_token(session, issued.token, NOW + timedelta(minutes=10)) is None
    assert await svc.resolve_token(session, rotated.token, NOW + timedelta(minutes=10)) is not None

    assert await svc.revoke_token(
        session, shop_id=shop.id, token_id=issued.token_id, reason="seller", now=NOW
    )
    assert await svc.resolve_token(session, rotated.token, NOW) is None
    _, other = await _shopee_tenant(session)
    assert not await svc.revoke_token(
        session, shop_id=other.id, token_id=rotated.token_id, reason="seller", now=NOW
    )


async def test_an_inactive_shop_token_stops_working(session):
    _, shop = await _shopee_tenant(session)
    issued = await svc.redeem_pairing_code(
        session,
        code=await _code(session, shop),
        platform="shopee",
        platform_shop_id=None,
        client_label=None,
        now=NOW,
    )
    shop.is_active = False
    await session.flush()
    assert await svc.resolve_token(session, issued.token, NOW) is None


# -- routes -----------------------------------------------------------------------------


async def _paired_client(session, shop, user):
    """Seller creates a code over HTTP; the extension pairs with it."""
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as seller:
        made = await seller.post("/v1/ingest/pairing-codes")
    assert made.status_code == 201, made.text
    app.dependency_overrides.clear()
    app = build_app(session)
    return app, made.json()["code"]


async def test_routes_end_to_end_pair_ingest_status_rotate_revoke(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        paired = await ext.post("/v1/ingest/pair", json={"code": code, "platform": "shopee"})
        assert paired.status_code == 200, paired.text
        token = paired.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        assert (await ext.get("/v1/ingest/status")).status_code == 401
        body = _body([_source_row("psd_label_product_card")])
        body["captured_at"] = datetime.now(UTC).isoformat()
        body["period"] = {"start": "2026-10-01", "end": "2026-10-01", "granularity": "day"}
        body["rows"][0]["date"] = "2026-10-01"
        posted = await ext.post("/v1/ingest/shopee/traffic_overview", json=body, headers=auth)
        assert posted.status_code == 200, posted.text
        assert posted.json()["duplicate"] is False
        again = await ext.post("/v1/ingest/shopee/traffic_overview", json=body, headers=auth)
        assert again.json()["duplicate"] is True

        bad = await ext.post(
            "/v1/ingest/shopee/traffic_overview",
            json={**body, "rows": [{**body["rows"][0], "ctr": 7}]},
            headers=auth,
        )
        assert bad.status_code == 422
        assert bad.json()["detail"]["code"] == "invalid_rows"
        assert bad.json()["detail"]["errors"][0]["loc"][:2] == ["rows", 0]
        assert (
            await ext.post("/v1/ingest/shopee/nope", json=body, headers=auth)
        ).status_code == 404
        assert (
            await ext.post("/v1/ingest/tiktok/traffic_overview", json=body, headers=auth)
        ).status_code == 403
        assert (
            await ext.post(
                "/v1/ingest/shopee/traffic_overview",
                content=b"x" * (svc.MAX_BODY_BYTES + 1),
                headers={**auth, "Content-Type": "application/json"},
            )
        ).status_code == 413

        status = await ext.get("/v1/ingest/status", headers=auth)
        assert status.status_code == 200
        datasets = {d["dataset"]: d for d in status.json()["datasets"]}
        assert datasets["traffic_overview"]["last_row_count"] == 1

        drift = await ext.post(
            "/v1/ingest/status",
            json={
                "platform": "shopee",
                "dataset": "item_by_source",
                "state": "drift",
                "source_version": "0.1.0",
                "unexpected": ["items[].new_field"],
            },
            headers=auth,
        )
        assert drift.status_code == 200, drift.text

        rotated = await ext.post("/v1/ingest/token/rotate", headers=auth)
        assert rotated.status_code == 200
        new_auth = {"Authorization": f"Bearer {rotated.json()['token']}"}
        assert (await ext.get("/v1/ingest/status", headers=new_auth)).status_code == 200

    # The seller sees the tokens (never the secret) and revokes the browser. (The
    # shared test session rolled back on the refused posts, expiring both.)
    await session.refresh(user)
    await session.refresh(shop)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as seller:
        listed = await seller.get("/v1/ingest/tokens")
        assert token not in listed.text
        first_id = paired.json()["token_id"]
        assert (await seller.delete(f"/v1/ingest/tokens/{first_id}")).status_code == 204
        assert (await seller.delete(f"/v1/ingest/tokens/{uuid.uuid4()}")).status_code == 404
    app.dependency_overrides.clear()
    async with client_for(build_app(session)) as ext:
        assert (await ext.get("/v1/ingest/status", headers=new_auth)).status_code == 401


async def test_a_token_is_not_a_seller_session_and_lands_only_in_its_shop(session):
    user_a, shop_a = await _shopee_tenant(session)
    _, shop_b = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop_a, user_a)
    async with client_for(app) as ext:
        token = (await ext.post("/v1/ingest/pair", json={"code": code})).json()["token"]
        auth = {"Authorization": f"Bearer {token}", "X-Shop-Id": str(shop_b.id)}
        # Seller routes take a Supabase JWT, not an ingest token.
        assert (await ext.get("/v1/shops/me", headers=auth)).status_code in (401, 403)
        assert (await ext.post("/v1/ingest/pairing-codes", headers=auth)).status_code in (401, 403)
        body = _body([_source_row("psd_label_product_card", date="2026-10-01")])
        body["period"] = {"start": "2026-10-01", "end": "2026-10-01", "granularity": "day"}
        body["captured_at"] = datetime.now(UTC).isoformat()
        assert (
            await ext.post("/v1/ingest/shopee/traffic_overview", json=body, headers=auth)
        ).status_code == 200
    assert await _count(session, PlatformDailyMetric, shop_a.id) == 1
    assert await _count(session, PlatformDailyMetric, shop_b.id) == 0


async def test_platform_shop_mismatch_is_refused(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        token = (
            await ext.post("/v1/ingest/pair", json={"code": code, "platform_shop_id": "5550001"})
        ).json()["token"]
        body = _body([_source_row("psd_label_product_card", date="2026-10-01")])
        body["period"] = {"start": "2026-10-01", "end": "2026-10-01", "granularity": "day"}
        body["captured_at"] = datetime.now(UTC).isoformat()
        body["platform_shop_id"] = "5550002"
        refused = await ext.post(
            "/v1/ingest/shopee/traffic_overview",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "shop_mismatch"


async def test_per_shop_rate_limit_and_pair_limit(session, monkeypatch):
    monkeypatch.setenv("INGEST_RATE_LIMIT_PER_SHOP", "2")
    monkeypatch.setenv("INGEST_PAIR_LIMIT_PER_CLIENT", "2")
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        token = (await ext.post("/v1/ingest/pair", json={"code": code})).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        assert (await ext.get("/v1/ingest/status", headers=auth)).status_code == 200
        assert (await ext.get("/v1/ingest/status", headers=auth)).status_code == 200
        limited = await ext.get("/v1/ingest/status", headers=auth)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0
        assert (await ext.post("/v1/ingest/pair", json={"code": "AAAAA-AAAAA"})).status_code == 400
        assert (await ext.post("/v1/ingest/pair", json={"code": "AAAAA-AAAAA"})).status_code == 429


async def test_seller_connects_a_shopee_shop(session):
    user, _ = await make_tenant(session)
    app = build_app(session)
    authenticate(app, user=user, shop=None)
    async with client_for(app) as seller:
        made = await seller.post(
            "/v1/shops/shopee", json={"shop_name": "Shop Shopee", "shopee_shop_id": "424242"}
        )
        assert made.status_code == 201, made.text
        assert made.json()["platform"] == "shopee"
        taken = await seller.post(
            "/v1/shops/shopee", json={"shop_name": "Again", "shopee_shop_id": "424242"}
        )
        assert taken.status_code == 409
        assert (await seller.post("/v1/shops/shopee", json={"shop_name": ""})).status_code == 422
    app.dependency_overrides.clear()


# -- migration --------------------------------------------------------------------------


def test_migration_088_chain_grants_and_pins():
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "088_ingest_gateway"' in text
    assert len("088_ingest_gateway") <= 32
    assert 'down_revision: str | None = "087_history_and_baselines"' in text
    assert 'down_revision: str | None = "101_write_mode_backfill"' in DEFERRED.read_text("utf-8")
    children = [
        p.name
        for p in VERSIONS.glob("*.py")
        if 'down_revision: str | None = "087_history_and_baselines"' in p.read_text("utf-8")
    ]
    assert children == ["088_ingest_gateway.py"]

    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    loader_spec = importlib.util.spec_from_file_location("migration_088", MIGRATION)
    assert loader_spec is not None and loader_spec.loader is not None
    migration = importlib.util.module_from_spec(loader_spec)
    loader_spec.loader.exec_module(migration)
    assert migration.GRANTS == {
        "ingest_pairing_codes": "SELECT, INSERT, UPDATE",
        "ingest_tokens": "SELECT, INSERT, UPDATE",
        "ingest_raw_payloads": "SELECT, INSERT",
        "platform_daily_metrics": "SELECT, INSERT, UPDATE",
        "ingest_dataset_status": "SELECT, INSERT, UPDATE",
    }
    for table in migration.GRANTS:
        assert TABLE_CLASSIFICATION_MAP[("public", table)] == "tenant_direct"
    assert "app_current_pairing_code_hash()" in migration._PAIRING_SELECT
    assert "app_current_shop_id()" in migration._PAIRING_SELECT
