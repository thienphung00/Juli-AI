"""P1-A mapper fixes: A-33/A-34 product analytics and product price/category.

Fixtures are the sanitized samples in docs/integrations/tiktok_api/contract-collection.md
and docs/integrations/tiktok_api/samples/.
"""

import json
from pathlib import Path

from juli_backend.integrations.tiktok.mapping import (
    expand_analytics_product_detail,
    expand_analytics_product_list_item,
    merge_product_analytics_rows,
    normalize_product,
)
from juli_backend.services.etl.transform import transform_for_channel

SAMPLES = Path(__file__).resolve().parents[2] / "docs/integrations/tiktok_api/samples"

A33 = {
    "latest_available_date": "2026-07-15",
    "performance": {
        "intervals": [
            {
                "start_date": "2026-07-13",
                "end_date": "2026-07-14",
                "sales": {
                    "gmv": {"amount": "1881780.00", "currency": "VND"},
                    "items_sold": 11,
                    "orders": 10,
                    "breakdowns": [
                        {
                            "content_type": "VIDEO",
                            "sales": {
                                "gmv": {"amount": "1292003.00", "currency": "VND"},
                                "items_sold": 8,
                            },
                        },
                        {
                            "content_type": "PRODUCT_CARD",
                            "sales": {
                                "gmv": {"amount": "589777.00", "currency": "VND"},
                                "items_sold": 3,
                            },
                        },
                    ],
                },
                "traffic": {
                    "breakdowns": [
                        {
                            "content_type": "VIDEO",
                            "traffic": {"impressions": 4060, "ctr": "0.05"},
                        }
                    ]
                },
            }
        ]
    },
}

A34_ITEM = {
    "id": "p1",
    "total_performance": {
        "gmv": {"amount": "2430217.00", "currency": "VND"},
        "orders": 9,
        "sku_orders": 10,
        "items_sold": 10,
        "estimated_customers": 6,
        "ctr": "0.0759",
        "click_order_rate": "0.1064",
    },
}


def _load(name):
    return json.loads((SAMPLES / name).read_text())["response"]["data"]


class TestProductDetailA33:
    def test_impressions_breakdown_clicks_ctr(self):
        (row,) = expand_analytics_product_detail(A33, synced_at=1, product_id="p1")
        assert row["impressions"] == 4060
        assert row["traffic_breakdown"] == {
            "VIDEO": {"impressions": 4060, "ctr": 0.05, "clicks": 203}
        }
        assert row["clicks"] == 203
        assert row["ctr"] == "0.050000"
        assert row["sales_breakdown"] == {
            "VIDEO": {"gmv": "1292003.00", "items_sold": 8},
            "PRODUCT_CARD": {"gmv": "589777.00", "items_sold": 3},
        }
        assert row["gmv"] == "1881780.00"

    def test_multiple_content_types_sum_and_weighted_ctr(self):
        data = json.loads(json.dumps(A33))
        data["performance"]["intervals"][0]["traffic"]["breakdowns"] = [
            {"content_type": "VIDEO", "traffic": {"impressions": 1000, "ctr": "0.10"}},
            {"content_type": "LIVE", "traffic": {"impressions": 3000, "ctr": 0.02}},
        ]
        (row,) = expand_analytics_product_detail(data, synced_at=1, product_id="p1")
        assert row["impressions"] == 4000
        assert row["clicks"] == 160  # 100 + 60
        assert row["ctr"] == "0.040000"

    def test_zero_impressions_falls_back_to_first_ctr(self):
        data = json.loads(json.dumps(A33))
        data["performance"]["intervals"][0]["traffic"]["breakdowns"] = [
            {"content_type": "VIDEO", "traffic": {"impressions": 0, "ctr": "0.05"}}
        ]
        (row,) = expand_analytics_product_detail(data, synced_at=1, product_id="p1")
        assert row["impressions"] == 0
        assert row["ctr"] == "0.05"
        assert "clicks" not in row

    def test_no_traffic_leaves_new_fields_absent(self):
        data = json.loads(json.dumps(A33))
        del data["performance"]["intervals"][0]["traffic"]
        (row,) = expand_analytics_product_detail(data, synced_at=1, product_id="p1")
        assert "impressions" not in row and "clicks" not in row
        assert "traffic_breakdown" not in row

    def test_transform_persists_new_columns(self):
        (row,) = expand_analytics_product_detail(A33, synced_at=1, product_id="p1")
        kind, kwargs = transform_for_channel("tiktok.analytics.product.raw", row)
        assert kind == "analytics_performance"
        assert kwargs["impressions"] == 4060
        assert kwargs["clicks"] == 203
        assert kwargs["traffic_breakdown"]["VIDEO"]["clicks"] == 203
        assert kwargs["sales_breakdown"]["PRODUCT_CARD"]["items_sold"] == 3


class TestProductListA34:
    def test_conversion_rate_from_click_order_rate(self):
        row = expand_analytics_product_list_item(
            A34_ITEM, start_date="2026-07-13", end_date="2026-07-14", synced_at=1
        )
        assert row["click_order_rate"] == "0.1064"
        assert row["conversion_rate"] == "0.1064"

    def test_merge_fills_gaps_without_overwriting(self):
        list_row = expand_analytics_product_list_item(
            A34_ITEM, start_date="2026-07-13", end_date="2026-07-14", synced_at=1
        )
        (detail,) = expand_analytics_product_detail(A33, synced_at=1, product_id="p1")
        (merged,) = merge_product_analytics_rows([detail], list_row)
        assert merged["conversion_rate"] == "0.1064"
        assert merged["ctr"] == "0.050000"  # detail wins
        assert merged["impressions"] == 4060

    def test_merge_skips_other_windows_and_none(self):
        list_row = expand_analytics_product_list_item(
            A34_ITEM, start_date="2026-07-01", end_date="2026-07-02", synced_at=1
        )
        (detail,) = expand_analytics_product_detail(A33, synced_at=1, product_id="p1")
        (merged,) = merge_product_analytics_rows([detail], list_row)
        assert "conversion_rate" not in merged
        assert merge_product_analytics_rows([detail], None) == [detail]

    def test_transform_drops_nulls_so_later_row_cannot_null_values(self):
        row = {
            "grain": "product",
            "start_date": "2026-07-13",
            "end_date": "2026-07-14",
            "product_id": "p1",
            "impressions": None,
            "conversion_rate": None,
            "ctr": None,
            "traffic_breakdown": None,
            "update_time": 1,
        }
        _, kwargs = transform_for_channel("tiktok.analytics.product.raw", row)
        for key in ("impressions", "conversion_rate", "ctr", "traffic_breakdown"):
            assert key not in kwargs


class TestProductPriceAndCategory:
    def test_search_sample_price_from_tax_exclusive(self):
        product = _load("products-search-response.json")["products"][0]
        mapped = normalize_product(product)
        assert mapped["price"] == "72000"
        assert mapped["price_currency"] == "VND"
        assert "category_id" not in mapped

    def test_detail_sample_price_and_category_leaf(self):
        mapped = normalize_product(_load("products-detail-response.json"))
        assert mapped["price"] == "72000"
        assert mapped["category_id"] == "601693"
        assert mapped["category"] == "Xịt miệng"
        _, kwargs = transform_for_channel("tiktok.products.raw", mapped)
        assert str(kwargs["price"]) == "72000"
        assert kwargs["category_id"] == "601693"
        assert kwargs["category"] == "Xịt miệng"

    def test_tax_exclusive_wins_over_sale_price(self):
        mapped = normalize_product(
            {
                "id": "x",
                "skus": [
                    {"price": {"sale_price": "90", "tax_exclusive_price": "80", "currency": "USD"}}
                ],
            }
        )
        assert mapped["price"] == "80"
        assert mapped["price_currency"] == "USD"

    def test_fallback_price_still_works(self):
        mapped = normalize_product({"id": "x", "skus": [{"price": {"sale_price": "90"}}]})
        assert mapped["price"] == "90"

    def test_leaf_falls_back_to_last_element(self):
        mapped = normalize_product(
            {
                "id": "x",
                "category_chains": [
                    {"id": "1", "local_name": "Root"},
                    {"id": "2", "local_name": "Child"},
                ],
            }
        )
        assert mapped["category_id"] == "2"
        assert mapped["category"] == "Child"

    def test_explicit_category_not_overridden(self):
        mapped = normalize_product(
            {
                "id": "x",
                "category": "Keep",
                "category_id": "9",
                "category_chains": [{"id": "1", "is_leaf": True, "local_name": "Leaf"}],
            }
        )
        assert (mapped["category"], mapped["category_id"]) == ("Keep", "9")
