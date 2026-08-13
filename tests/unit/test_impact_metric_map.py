"""Funnel-first target-metric map — ADR-077 decision 1 (#1041).

Acceptance criterion: the metric map is data, not branching logic, and
covers all four mutation kinds with both primary and secondary metrics.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from juli_backend.services.impact.metric_map import (
    ALL_METRICS,
    CONVERSION_RATE,
    CTR,
    GMV,
    GMV_PER_ORDER,
    IMPRESSIONS,
    ITEMS_SOLD,
    METRIC_MAP,
    SKU_ORDERS,
    MutationKind,
    RawDailyRecord,
    resolve_metric,
)


class TestMetricMapCoverage:
    def test_all_four_mutation_kinds_present(self):
        assert set(METRIC_MAP) == {
            MutationKind.SEO_KEYWORDS_TITLE,
            MutationKind.DESCRIPTION,
            MutationKind.IMAGE,
            MutationKind.PRICE,
        }

    def test_every_mutation_has_a_primary_and_at_least_one_secondary(self):
        for mutation, mapping in METRIC_MAP.items():
            assert mapping.primary is not None, mutation
            assert len(mapping.secondary) >= 1, mutation

    def test_seo_keywords_title_maps_to_impressions_primary_ctr_secondary(self):
        mapping = METRIC_MAP[MutationKind.SEO_KEYWORDS_TITLE]
        assert mapping.primary is IMPRESSIONS
        assert mapping.secondary == (CTR,)

    def test_description_maps_to_conversion_rate_primary_items_sold_secondary(self):
        mapping = METRIC_MAP[MutationKind.DESCRIPTION]
        assert mapping.primary is CONVERSION_RATE
        assert mapping.secondary == (ITEMS_SOLD,)

    def test_image_maps_to_ctr_primary_conversion_rate_secondary(self):
        mapping = METRIC_MAP[MutationKind.IMAGE]
        assert mapping.primary is CTR
        assert mapping.secondary == (CONVERSION_RATE,)

    def test_price_maps_to_gmv_primary_sku_orders_and_gmv_per_order_secondary(self):
        mapping = METRIC_MAP[MutationKind.PRICE]
        assert mapping.primary is GMV
        assert mapping.secondary == (SKU_ORDERS, GMV_PER_ORDER)

    def test_metric_map_is_a_plain_dict_not_a_function(self):
        # "Data, not branching logic" — enforced structurally: METRIC_MAP is
        # a dict literal, not a function that would need per-kind branches.
        assert isinstance(METRIC_MAP, dict)


class TestAllMetricsRegistry:
    def test_all_seven_metrics_registered(self):
        assert set(ALL_METRICS) == {
            "impressions",
            "ctr",
            "conversion_rate",
            "items_sold",
            "gmv",
            "sku_orders",
            "gmv_per_order",
        }

    def test_resolve_metric_returns_registered_spec(self):
        assert resolve_metric("gmv") is GMV

    def test_resolve_metric_raises_key_error_naming_unknown_key(self):
        with pytest.raises(KeyError, match="unknown_metric_xyz"):
            resolve_metric("unknown_metric_xyz")


class TestRateMetricFlag:
    def test_rate_metrics_flagged_is_rate_true(self):
        for spec in (CTR, CONVERSION_RATE, GMV_PER_ORDER):
            assert spec.is_rate is True

    def test_count_and_currency_metrics_flagged_is_rate_false(self):
        for spec in (IMPRESSIONS, ITEMS_SOLD, GMV, SKU_ORDERS):
            assert spec.is_rate is False


class TestGmvPerOrderDerivedMetric:
    def test_gmv_divided_by_sku_orders(self):
        day = RawDailyRecord(gmv=Decimal("500.00"), sku_orders=Decimal(20))
        assert GMV_PER_ORDER.extractor(day) == Decimal("25.00")

    def test_zero_orders_is_none_not_zero(self):
        day = RawDailyRecord(gmv=Decimal("100.00"), sku_orders=Decimal(0))
        assert GMV_PER_ORDER.extractor(day) is None

    def test_missing_gmv_is_none(self):
        day = RawDailyRecord(gmv=None, sku_orders=Decimal(5))
        assert GMV_PER_ORDER.extractor(day) is None

    def test_missing_sku_orders_is_none(self):
        day = RawDailyRecord(gmv=Decimal("100.00"), sku_orders=None)
        assert GMV_PER_ORDER.extractor(day) is None


class TestPlainMetricExtractors:
    def test_impressions_extractor_reads_impressions_field(self):
        day = RawDailyRecord(impressions=Decimal(500))
        assert IMPRESSIONS.extractor(day) == Decimal(500)

    def test_ctr_extractor_reads_ctr_field(self):
        day = RawDailyRecord(ctr=Decimal("0.045"))
        assert CTR.extractor(day) == Decimal("0.045")

    def test_conversion_rate_extractor_reads_conversion_rate_field(self):
        day = RawDailyRecord(conversion_rate=Decimal("0.02"))
        assert CONVERSION_RATE.extractor(day) == Decimal("0.02")

    def test_items_sold_extractor_reads_items_sold_field(self):
        day = RawDailyRecord(items_sold=Decimal(12))
        assert ITEMS_SOLD.extractor(day) == Decimal(12)

    def test_sku_orders_extractor_reads_sku_orders_field(self):
        day = RawDailyRecord(sku_orders=Decimal(7))
        assert SKU_ORDERS.extractor(day) == Decimal(7)
