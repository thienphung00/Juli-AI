"""apiwatch (infra/apiwatch, D31.10): normalization of the platforms' public doc JSON."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "infra" / "apiwatch"))

juli_usage = importlib.import_module("apiwatch.juli_usage")
shopee = importlib.import_module("apiwatch.shopee")
snapshot = importlib.import_module("apiwatch.snapshot")
tiktok = importlib.import_module("apiwatch.tiktok")
_norm = importlib.import_module("apiwatch.normalize")
api_path_mentions = _norm.api_path_mentions
flatten_caret_list = _norm.flatten_caret_list
flatten_tree = _norm.flatten_tree
json_field_paths = _norm.json_field_paths
looks_deprecated = _norm.looks_deprecated
markdown_table_fields = _norm.markdown_table_fields
path_template = _norm.path_template
versionless = _norm.versionless

FIXTURES = _ROOT / "tests" / "fixtures" / "apiwatch"


def _raw(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_caret_list_rebuilds_nested_paths_and_arrays():
    params = [
        {"name": "data", "type": "object", "required": "N"},
        {"name": "^skus", "type": "[]object", "required": "N"},
        {"name": "^^price", "type": "object", "required": "N"},
        {"name": "^^^sale_price", "type": "string", "required": "Y"},
        {"name": "^id", "type": "string", "required": "Y"},
        {"name": "code", "type": "int", "required": "N"},
    ]
    out = flatten_caret_list(params)
    assert list(out) == [
        "data",
        "data.skus",
        "data.skus[].price",
        "data.skus[].price.sale_price",
        "data.id",
        "code",
    ]
    assert out["data.skus[].price.sale_price"] == {"type": "string", "required": True}
    assert flatten_caret_list(params, with_required=False)["data.id"] == {"type": "string"}


def test_tree_params_use_array_marker_from_type():
    params = [
        {
            "name": "response",
            "type": "object",
            "children": [
                {
                    "name": "item_list",
                    "type": "object[]",
                    "children": [{"name": "item_id", "type": "int64", "required": "True"}],
                }
            ],
        }
    ]
    out = flatten_tree(params)
    assert out["response.item_list[].item_id"] == {"type": "int64", "required": True}
    assert out["response.item_list"]["required"] is False


def test_example_payload_and_markdown_table_paths():
    sample = {"type": 4, "data": {"package_list": [{"package_id": "1", "order_id_list": ["a"]}]}}
    paths = json_field_paths(sample)
    assert paths["data.package_list"] == {"type": "[]object"}
    assert paths["data.package_list[].order_id_list"] == {"type": "[]string"}
    table = (
        "| **Parameter name** | **Sample** | **Description** |\n"
        "| --- | --- | --- |\n"
        "| package_list | []object | list |\n"
        '| └ package_id | "1" | id |\n'
        "| update_time | 1 | t |\n"
    )
    assert list(markdown_table_fields(table)) == [
        "package_list",
        "package_list[].package_id",
        "update_time",
    ]


def test_path_helpers():
    assert path_template("/product/202309/products/{product_id}/") == "/product/202309/products/{}"
    assert versionless("/product/202502/products/search") == "/product/{v}/products/search"
    assert api_path_mentions("use `/order/202507/orders` and /product/202309/products/{id}.") == [
        "/order/202507/orders",
        "/product/202309/products/{}",
    ]
    assert looks_deprecated("(coming offline soon) v2.ads.create_auto_product_ads")
    assert looks_deprecated("The previous API will be retired within three months")
    assert not looks_deprecated("Retrieve product details by product ID")


def test_tiktok_normalize_fixture():
    out = tiktok.normalize(_raw("tiktok_raw.json"))
    endpoint = out["endpoints"]["GET /product/202309/products/{product_id}"]
    assert endpoint["title"] == "Get Product"
    assert endpoint["module"] == "Products"
    assert endpoint["version"] == "202309"
    assert endpoint["request"]["path.product_id"] == {"type": "string", "required": True}
    assert endpoint["response"]["data.skus[].price.sale_price"] == {"type": "string"}
    assert "data.id.status" not in endpoint["response"]
    webhook = out["webhooks"]["4"]
    assert webhook["name"] == "Package update"
    assert webhook["category"] == "Logistics"
    assert "data.package_list[].package_id" in webhook["fields"]
    (entry,) = out["changelog"].values()
    assert entry["date"] == "2026-09-28"  # the page's own "Release date", not update_time
    assert entry["category"] == "Analytics"
    assert entry["deprecation"] is True  # "will be retired"
    assert out["_failed"] == []


def test_tiktok_failed_api_meta_is_recorded_for_carry_over():
    raw = _raw("tiktok_raw.json")
    raw["meta"]["6509d85b4a0bb702c057fdda"] = {"__error__": "HTTP 500"}
    out = tiktok.normalize(raw)
    assert out["endpoints"] == {}
    assert {
        "section": "endpoints",
        "url": "https://partner.tiktokshop.com/docv2/page/get-product-202309",
    } in out["_failed"]


def test_shopee_normalize_fixture():
    out = shopee.normalize(_raw("shopee_raw.json"))
    endpoint = out["endpoints"]["GET /api/v2/product/get_item_base_info"]
    assert endpoint["module"] == "Product"
    assert endpoint["request"]["item_id_list"] == {"type": "int64[]", "required": True}
    assert endpoint["response"]["response.item_list[].price_info[].current_price"] == {
        "type": "float"
    }
    assert out["webhooks"]["3"]["name"] == "order_status_push"
    assert "data.ordersn" in out["webhooks"]["3"]["fields"]
    keys = sorted(out["changelog"])
    assert any(k.startswith("api:v2.product.get_item_base_info:2026-04-03:") for k in keys)
    assert "guide:4" in keys
    assert any(k.startswith("push:order_status_push:") for k in keys)


def test_snapshot_is_deterministic_and_carries_over_failures():
    first = shopee.normalize(_raw("shopee_raw.json"))
    snap, kept = snapshot.build("shopee", first, {}, None)
    assert kept == 0
    again, _ = snapshot.build("shopee", shopee.normalize(_raw("shopee_raw.json")), {}, None)
    assert snapshot.dumps(snap) == snapshot.dumps(again)

    raw = _raw("shopee_raw.json")
    raw["apis"]["v2.product.get_item_base_info"] = {"__error__": "HTTP 502"}
    broken = shopee.normalize(raw)
    assert broken["endpoints"] == {}
    rebuilt, kept = snapshot.build("shopee", broken, {}, snap)
    assert "GET /api/v2/product/get_item_base_info" in rebuilt["endpoints"]
    assert kept >= 3  # the endpoint and its two update-log entries


def test_snapshot_compacts_to_field_paths_over_the_size_limit():
    snap, _ = snapshot.build("shopee", shopee.normalize(_raw("shopee_raw.json")), {}, None)
    small, text = snapshot.fit(snap, max_bytes=100)
    assert small["compact"] is True
    record = small["endpoints"]["GET /api/v2/product/get_item_base_info"]
    assert record["request"] == ["item_id_list", "need_tax_info"]
    assert json.loads(text) == small


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            'A_API_VERSION = "202309"\nB_API_VERSION = "202510"\n'
            'P = f"/order/{A_API_VERSION}/orders/search"\n'
            "def f(x):\n    return (\n"
            '        f"/analytics/{B_API_VERSION}/shop/performance/"\n'
            '        f"{x}/performance_per_hour"\n    )\n'
            'T = f"/order/{A_API_VERSION}/orders/{{order_id}}/price_detail"\n',
            {
                "/order/202309/orders/search",
                "/analytics/202510/shop/performance/{}/performance_per_hour",
                "/order/202309/orders/{}/price_detail",
            },
        )
    ],
)
def test_juli_usage_parses_constants(source, expected):
    assert juli_usage.tiktok_endpoints_from_constants(source) == expected


def test_juli_usage_from_this_repo():
    usage = juli_usage.load(_ROOT)
    tiktok_usage = usage["tiktok"]
    assert "/product/202309/products/{}" in tiktok_usage["endpoints"]
    assert "/order/202309/orders/search" in tiktok_usage["endpoints"]
    assert {"1", "4", "5"} <= tiktok_usage["webhooks"]
    assert "/api/v2/order/get_order_list" in usage["shopee"]["planned_endpoints"]
