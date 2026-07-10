"""Contract fixture tests for docs/integrations/tiktok_api/samples (issue #294)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "docs/integrations/tiktok_api/samples"

LAYER1_FIXTURES = [
    ("authorized-shops-response.json", "shops", "GET /authorization/202309/shops"),
    ("products-search-response.json", "products", "POST /product/202309/products/search"),
    ("products-detail-response.json", None, "GET /product/202309/products/{product_id}"),
    ("orders-search-response.json", "orders", "POST /order/202309/orders/search"),
    ("orders-detail-response.json", "orders", "GET /order/202507/orders"),
    ("returns-search-response.json", "return_orders", "POST /return_refund/202602/returns/search"),
    (
        "cancellations-search-response.json",
        "cancellations",
        "POST /return_refund/202602/cancellations/search",
    ),
    ("inventory-search-response.json", "inventory", "POST /product/202309/inventory/search"),
]

SECRET_MARKERS = ("access_token", "app_secret", "ROW_", "refresh_token", "@scs2.tiktok.com")


def _load_fixture(name: str) -> dict:
    path = SAMPLES_DIR / name
    assert path.exists(), f"missing fixture: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename,data_key,endpoint", LAYER1_FIXTURES)
def test_layer1_fixture_envelope(filename: str, data_key: str | None, endpoint: str):
    fixture = _load_fixture(filename)
    meta = fixture["_meta"]
    response = fixture["response"]

    assert meta["endpoint"] == endpoint
    assert meta["contract_collection"] == "docs/integrations/tiktok_api/contract-collection.md"
    assert meta["shop_cipher_redacted"] is True
    assert response["code"] == 0
    assert response["message"] == "Success"
    assert "data" in response

    if data_key is not None:
        assert data_key in response["data"]
        assert len(response["data"][data_key]) >= 1
    else:
        # Get Product returns a single product object under data
        assert "id" in response["data"]


@pytest.mark.parametrize("filename,_,__", LAYER1_FIXTURES)
def test_sanitized_json_samples_no_secrets(filename: str, _: str, __: str):
    raw = (SAMPLES_DIR / filename).read_text(encoding="utf-8")
    lowered = raw.lower()
    for marker in SECRET_MARKERS:
        assert marker.lower() not in lowered, f"{filename} may contain secret marker {marker}"


def test_endpoints_md_reflects_verified_contracts():
    endpoints = Path(__file__).resolve().parents[2] / "docs/integrations/tiktok_api/endpoints.md"
    text = endpoints.read_text(encoding="utf-8")
    assert "Layer 0 — complete" in text
    assert "products-search-response.json" in text
    assert "POST /product/202309/products/search" in text
    assert "GET /order/202507/orders" in text


def test_samples_readme_cross_links_contract_collection():
    readme = SAMPLES_DIR / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "contract-collection.md" in text
    assert "extract_tiktok_fixtures.py" in text
    assert "§3" in text or "§6" in text


def test_handoff_stop_condition_satisfied_layer1():
    handoff = (
        Path(__file__).resolve().parents[2]
        / "docs/handoffs/phase-2-tiktok-implementation.md"
    )
    text = handoff.read_text(encoding="utf-8")
    assert "Stop condition (cleared for Layer 1 minimum)" in text
    assert "docs/integrations/tiktok_api/samples/" in text
