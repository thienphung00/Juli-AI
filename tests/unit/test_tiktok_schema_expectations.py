"""TikTok client drift wiring (D31.10): expectations match the docs, client reports drift."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from juli_backend.integrations import schema_drift
from juli_backend.integrations.tiktok import constants
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.schema_expectations import (
    EXPECTATIONS,
    expectation_for,
)

SNAPSHOT = Path(__file__).resolve().parents[2] / "infra" / "apiwatch" / "snapshots" / "tiktok.json"


@pytest.fixture(autouse=True)
def _fresh():
    schema_drift.reset_seen()
    yield
    schema_drift.reset_seen()


def _documented_response_fields(endpoint: str) -> set[str]:
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    response = snap["endpoints"][endpoint]["response"]
    paths = response if isinstance(response, list) else list(response)
    return {p[len("data.") :] for p in paths if p.startswith("data.")}


@pytest.mark.parametrize("expectation", EXPECTATIONS, ids=lambda e: e.label)
def test_expected_fields_are_documented(expectation):
    documented = _documented_response_fields(expectation.endpoint)
    assert expectation.expected <= documented, sorted(expectation.expected - documented)
    assert not expectation.expected & expectation.documented


@pytest.mark.parametrize(
    ("method", "path", "label"),
    [
        ("GET", constants.product_detail_path("1729592969712207008"), "product detail"),
        ("POST", constants.PRODUCT_SEARCH_PATH, "search products"),
        ("POST", constants.ORDER_SEARCH_PATH, "search orders"),
        ("GET", constants.ORDER_DETAIL_PATH, "order detail"),
        ("GET", constants.ANALYTICS_SHOP_PERFORMANCE_PATH, "shop performance"),
        ("GET", constants.ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH, "product performance list"),
        (
            "GET",
            constants.analytics_shop_product_performance_path("1729592969712207008"),
            "product performance detail",
        ),
        ("GET", constants.ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH, "sku performance list"),
        ("POST", constants.PROMOTION_ACTIVITIES_SEARCH_PATH, "search promotion activities"),
        (
            "GET",
            constants.promotion_activity_path("7300000000000000001"),
            "promotion activity detail",
        ),
    ],
)
def test_client_paths_resolve_to_their_expectation(method, path, label):
    expectation = expectation_for(method, path)
    assert expectation is not None and expectation.label == label


def test_unwatched_paths_have_no_expectation():
    assert expectation_for("GET", constants.PRODUCT_CATEGORIES_PATH) is None
    assert expectation_for("PUT", constants.product_edit_path("1729592969712207008")) is None


def _client(payload: dict) -> TikTokClient:
    client = TikTokClient(app_key="k", app_secret="s", access_token="t", shop_cipher="c")
    client._session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"code": 0, "message": "Success", "data": payload}
    client._session.get.return_value = resp
    client._session.post.return_value = resp
    return client


def _drift_records(caplog):
    return [r for r in caplog.records if r.getMessage() == "api_schema_drift"]


def test_client_get_reports_missing_field_once_and_returns_data_unchanged(caplog):
    caplog.set_level(logging.WARNING, logger="juli_backend.integrations.schema_drift")
    payload = {
        "id": "1",
        "status": "ACTIVATE",
        "create_time": 1,
        "update_time": 2,
        "category_chains": [{"id": "9", "is_leaf": True, "local_name": "Áo"}],
        "skus": [
            {
                "id": "s",
                "price": {"currency": "VND", "sale_price": "10"},
                "inventory": [{"quantity": 3}],
            }
        ],
        "brand_new_field": True,
    }  # "title" missing
    client = _client(payload)
    path = constants.product_detail_path("1729592969712207008")
    for _ in range(2):
        assert client.get(path) == payload
    (record,) = _drift_records(caplog)
    assert record.endpoint == "GET /product/202309/products/{product_id}"
    assert record.missing_fields == ["title"]
    assert record.unexpected_fields == ["brand_new_field"]


def test_client_post_page_without_drift_logs_nothing(caplog):
    caplog.set_level(logging.WARNING, logger="juli_backend.integrations.schema_drift")
    payload = {
        "orders": [
            {
                "id": "o",
                "user_id": "u",
                "status": "COMPLETED",
                "update_time": 1,
                "payment": {"currency": "VND", "sub_total": "1", "total_amount": "1"},
                "line_items": [
                    {
                        "sku_id": "s",
                        "product_id": "p",
                        "sale_price": "1",
                        "platform_discount": "0",
                        "seller_discount": "0",
                    }
                ],
            }
        ],
        "next_page_token": "",
        "total_count": 1,
    }
    client = _client(payload)
    assert client.post(constants.ORDER_SEARCH_PATH, body={}) == payload
    assert _drift_records(caplog) == []


def test_drift_check_failure_never_breaks_the_call(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bug in drift check")

    monkeypatch.setattr(schema_drift, "find_drift", boom)
    client = _client({"id": "1"})
    assert client.get(constants.product_detail_path("1729592969712207008")) == {"id": "1"}
