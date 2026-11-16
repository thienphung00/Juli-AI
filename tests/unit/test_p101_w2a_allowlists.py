"""P101 W2a: the transport allowlist entries from the W0 probe gaps (p101-w0-probe-docs.md §F),
and nothing broader. Product detail stays on 202309 (202509 returned 36009004 in the probe)."""

from __future__ import annotations

import pytest

from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_WRITE_ALLOWED_REQUESTS,
    is_production_read_allowed,
    is_production_write_allowed,
    is_sandbox_write_allowed,
    path_contains_write_marker,
)
from juli_backend.integrations.tiktok.constants import (
    PRODUCT_API_VERSION,
    product_detail_path,
    product_edit_path,
)

READS = [
    ("POST", "/product/202502/products/search"),
    ("GET", "/finance/202507/orders/unsettled"),
    ("GET", "/finance/202501/statements/7300000000000000001/statement_transactions"),
    ("POST", "/affiliate_seller/202410/orders/search"),
    ("GET", "/event/202309/webhooks"),
]


@pytest.mark.parametrize(("method", "path"), READS)
def test_the_probe_reads_are_allowed_on_production_read(method, path):
    assert is_production_read_allowed(method, path)
    assert not path_contains_write_marker(path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/product/202502/products/search"),  # wrong method
        ("POST", "/finance/202507/orders/unsettled"),
        ("GET", "/finance/202501/statements/abc/statement_transactions"),  # non-numeric id
        ("GET", "/finance/202309/statements/1/statement_transactions"),  # other version
        ("POST", "/affiliate_seller/202410/orders/1"),
        ("POST", "/event/202309/webhooks"),  # registering a webhook is a write
        ("PUT", "/event/202309/webhooks"),
        ("DELETE", "/event/202309/webhooks"),
        ("POST", "/product/202509/products/1/partial_edit"),
        ("POST", "/promotion/202607/activities/1/republish"),
    ],
)
def test_nothing_broader_slipped_into_production_read(method, path):
    assert not is_production_read_allowed(method, path)


@pytest.mark.parametrize(
    "path",
    ["/product/202509/products/123/partial_edit", "/promotion/202607/activities/456/republish"],
)
def test_the_probe_writes_are_sandbox_allowed_and_marked_as_writes(path):
    assert is_sandbox_write_allowed("POST", path)
    assert not is_sandbox_write_allowed("PUT", path)
    assert path_contains_write_marker(path)


@pytest.mark.parametrize(
    "path",
    [
        "/product/202309/products/123/partial_edit",  # only the probed version
        "/product/202509/products/abc/partial_edit",
        "/promotion/202309/activities/456/republish",
    ],
)
def test_other_versions_of_the_probe_writes_stay_refused(path):
    assert not is_sandbox_write_allowed("POST", path)
    assert not is_production_write_allowed("POST", path)


def test_production_write_gains_the_partial_edit_but_not_the_republish():
    assert is_production_write_allowed("POST", "/product/202509/products/123/partial_edit")
    assert not is_production_write_allowed("POST", "/promotion/202607/activities/456/republish")
    patterns = [pattern.pattern for _method, pattern in PRODUCTION_WRITE_ALLOWED_REQUESTS]
    assert not any("promotion" in p or "prices" in p or "inventory" in p for p in patterns)
    assert len(PRODUCTION_WRITE_ALLOWED_REQUESTS) == 6


def test_product_detail_stays_on_202309():
    assert PRODUCT_API_VERSION == "202309"
    assert product_detail_path("123") == "/product/202309/products/123"
    assert product_edit_path("123") == "/product/202309/products/123"
