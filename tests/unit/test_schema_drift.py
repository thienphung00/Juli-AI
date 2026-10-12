"""Runtime schema drift helper (D31.10): missing/unexpected fields, one log per drift."""

from __future__ import annotations

import logging

import pytest

from juli_backend.integrations import schema_drift
from juli_backend.integrations.schema_drift import find_drift, report_schema_drift


@pytest.fixture(autouse=True)
def _fresh():
    schema_drift.reset_seen()
    yield
    schema_drift.reset_seen()


EXPECTED = {"id", "title", "skus[].id", "skus[].price.sale_price"}
DOCUMENTED = {"description", "skus[].seller_sku", "skus[].price.currency"}


def _payload(**overrides):
    payload = {
        "id": "1",
        "title": "Áo",
        "description": "x",
        "skus": [
            {"id": "a", "seller_sku": "S", "price": {"sale_price": "10", "currency": "VND"}},
            {"id": "b", "price": {"currency": "VND"}},  # one row without sale_price is fine
        ],
    }
    payload.update(overrides)
    return payload


def test_matching_payload_has_no_drift():
    assert find_drift(_payload(), EXPECTED, DOCUMENTED) == ((), ())


def test_missing_and_unexpected_fields():
    payload = _payload(video={"id": "v"})
    del payload["title"]
    for sku in payload["skus"]:
        sku["price"].pop("sale_price", None)
        sku["price"]["sale_price_v2"] = "10"
    missing, unexpected = find_drift(payload, EXPECTED, DOCUMENTED)
    assert missing == ("skus[].price.sale_price", "title")
    assert unexpected == ("skus[].price.sale_price_v2", "video")


def test_empty_or_absent_list_proves_nothing_about_its_children():
    assert find_drift(_payload(skus=[]), EXPECTED, DOCUMENTED) == ((), ())
    payload = _payload()
    del payload["skus"]
    assert find_drift(payload, EXPECTED, DOCUMENTED) == ((), ())
    # ...but an expected list itself is reported when absent.
    assert find_drift(payload, EXPECTED | {"skus"}, DOCUMENTED)[0] == ("skus",)


def test_logs_once_per_endpoint_and_drift(caplog):
    caplog.set_level(logging.WARNING, logger="juli_backend.integrations.schema_drift")
    payload = _payload()
    del payload["title"]
    for _ in range(3):
        drift = report_schema_drift("tiktok", "GET /x", payload, EXPECTED, documented=DOCUMENTED)
        assert drift is not None and drift.missing == ("title",)
    records = [r for r in caplog.records if r.getMessage() == "api_schema_drift"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert record.event == "api_schema_drift"
    assert record.platform == "tiktok"
    assert record.endpoint == "GET /x"
    assert record.missing_fields == ["title"]
    assert record.unexpected_fields == []

    # A different drift on the same endpoint, or the same drift elsewhere, logs again.
    del payload["id"]
    report_schema_drift("tiktok", "GET /x", payload, EXPECTED, documented=DOCUMENTED)
    report_schema_drift("shopee", "GET /x", payload, EXPECTED, documented=DOCUMENTED)
    assert len([r for r in caplog.records if r.getMessage() == "api_schema_drift"]) == 3


def test_no_drift_returns_none_and_logs_nothing(caplog):
    caplog.set_level(logging.WARNING, logger="juli_backend.integrations.schema_drift")
    assert (
        report_schema_drift("tiktok", "GET /x", _payload(), EXPECTED, documented=DOCUMENTED) is None
    )
    assert not caplog.records


def test_never_raises_and_never_mutates(caplog):
    payload = _payload()
    snapshot = repr(payload)
    assert report_schema_drift("tiktok", "GET /x", payload, EXPECTED, documented=DOCUMENTED) is None
    assert repr(payload) == snapshot
    assert report_schema_drift("tiktok", "GET /x", None, EXPECTED) is None
    assert report_schema_drift("tiktok", "GET /x", ["not", "a", "dict"], EXPECTED) is None
    assert report_schema_drift("tiktok", "GET /x", {"skus": "oops"}, EXPECTED) is not None
