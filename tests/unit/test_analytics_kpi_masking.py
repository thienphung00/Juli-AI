"""P2.10-A6 (#530) — identity masking for public Analytics envelopes."""

from __future__ import annotations

import copy
import json
import uuid

REAL_SHOP_DISPLAY_NAME = "Fujiwa Official Store"
REAL_MERCHANT_ID = "7658073774813611784"
REAL_PRODUCT_TITLE_A = "Organic Matcha Powder 100g Premium Grade"
REAL_PRODUCT_TITLE_B = "Ceramic Tea Set — Limited Edition"
REAL_PRODUCT_ID_A = "7136011254174631686"
REAL_PRODUCT_ID_B = "7136382541418366725"
REAL_ORDER_ID = "5768901234567890123"
REAL_SKU_ID = "7136382541418366725"


def _raw_envelope_fixture(*, shop_id: uuid.UUID | None = None) -> dict:
    sid = shop_id or uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    return {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(sid),
        "computed_at": "2026-07-27T06:00:00+00:00",
        "currency": "VND",
        "identity": {
            "shop_display_name": REAL_SHOP_DISPLAY_NAME,
            "merchant_id": REAL_MERCHANT_ID,
            "products": [
                {
                    "id": REAL_PRODUCT_ID_A,
                    "title": REAL_PRODUCT_TITLE_A,
                    "sku_id": REAL_SKU_ID,
                },
                {
                    "id": REAL_PRODUCT_ID_B,
                    "title": REAL_PRODUCT_TITLE_B,
                },
            ],
            "orders": [
                {
                    "id": REAL_ORDER_ID,
                    "product_title": REAL_PRODUCT_TITLE_A,
                }
            ],
        },
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "label": "GMV (TikTok)",
                "series": [
                    {"t": "2026-07-13", "v": 6408074.0},
                    {"t": "2026-07-14", "v": 1200000.0},
                ],
            },
            "product_funnel": {
                "availability": "available",
                "label": "Product funnel (GMV)",
                "series": [{"t": "2026-07-13", "v": 800000.0}],
            },
            "live_performance": {
                "availability": "unavailable",
                "label": "LIVE performance (GMV)",
            },
            "roas": {
                "availability": "unavailable",
                "label": "ROAS",
            },
        },
        "meta": {"source_partitions": ["A-36", "A-34"], "notes": []},
        "overlays": {
            "t1_forecast": {"availability": "unavailable"},
        },
    }


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_masks_shop_name_and_product_titles_to_demo_aliases() -> None:
    from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope

    raw = _raw_envelope_fixture()
    masked = mask_public_analytics_envelope(raw)

    identity = masked["identity"]
    assert identity["shop_display_name"] != REAL_SHOP_DISPLAY_NAME
    assert identity["shop_display_name"].startswith("Demo Shop")

    product_titles = {p["title"] for p in identity["products"]}
    assert REAL_PRODUCT_TITLE_A not in product_titles
    assert REAL_PRODUCT_TITLE_B not in product_titles
    assert all(title.startswith("Demo Product") for title in product_titles)


def test_numeric_gmv_series_magnitudes_unchanged_by_masking() -> None:
    from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope

    raw = _raw_envelope_fixture()
    masked = mask_public_analytics_envelope(raw)

    assert masked["kpis"]["gmv_tiktok"]["series"] == raw["kpis"]["gmv_tiktok"]["series"]
    assert masked["kpis"]["product_funnel"]["series"] == raw["kpis"]["product_funnel"]["series"]
    assert masked["kpis"]["live_performance"] == raw["kpis"]["live_performance"]
    assert masked["kpis"]["roas"] == raw["kpis"]["roas"]
    assert masked["overlays"] == raw["overlays"]
    assert masked["currency"] == raw["currency"]


def test_raw_merchant_id_and_real_titles_absent_from_masked_payload() -> None:
    from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope

    raw = _raw_envelope_fixture()
    masked = mask_public_analytics_envelope(raw)
    serialized = _dump(masked)

    assert REAL_MERCHANT_ID not in serialized
    assert REAL_SHOP_DISPLAY_NAME not in serialized
    assert REAL_PRODUCT_TITLE_A not in serialized
    assert REAL_PRODUCT_TITLE_B not in serialized
    assert REAL_PRODUCT_ID_A not in serialized
    assert REAL_PRODUCT_ID_B not in serialized
    assert REAL_ORDER_ID not in serialized
    assert REAL_SKU_ID not in serialized

    identity = masked["identity"]
    assert "merchant_id" not in identity
    for product in identity["products"]:
        assert product["id"].startswith("demo-product-")
        assert "sku_id" not in product or product["sku_id"].startswith("demo-sku-")
    for order in identity["orders"]:
        assert order["id"].startswith("demo-order-")
        assert order["product_title"].startswith("Demo Product")


def test_alias_stability_across_repeated_calls() -> None:
    from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope

    raw = _raw_envelope_fixture()
    first = mask_public_analytics_envelope(copy.deepcopy(raw))
    second = mask_public_analytics_envelope(copy.deepcopy(raw))

    assert first == second
    assert first["identity"]["shop_display_name"] == second["identity"]["shop_display_name"]
    assert first["identity"]["products"][0]["title"] == second["identity"]["products"][0]["title"]
    assert first["identity"]["products"][0]["id"] == second["identity"]["products"][0]["id"]


def test_masking_does_not_mutate_input_envelope() -> None:
    from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope

    raw = _raw_envelope_fixture()
    snapshot = copy.deepcopy(raw)
    mask_public_analytics_envelope(raw)
    assert raw == snapshot


def test_buyer_pii_keys_stripped_from_masked_payload() -> None:
    from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope

    raw = _raw_envelope_fixture()
    raw["identity"]["buyer_email"] = "buyer@example.com"
    raw["identity"]["buyer_phone"] = "+84901234567"
    masked = mask_public_analytics_envelope(raw)
    serialized = _dump(masked)

    assert "buyer@example.com" not in serialized
    assert "+84901234567" not in serialized
    assert "buyer_email" not in masked.get("identity", {})
    assert "buyer_phone" not in masked.get("identity", {})
