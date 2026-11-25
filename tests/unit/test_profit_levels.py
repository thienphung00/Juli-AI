"""L1 / L3 / L4 (batch-1124-c-data, owner #42 / #65 / #66 / #67, ``profit-levels.html``).

Tổng quan and Kế hoạch show Ròng; every product-level surface stops at Đóng góp (before ads AND
affiliate), its margin ÷ the covered doanh thu thực; one metric id per label.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from juli_backend.services.metrics.registry import METRICS
from juli_backend.services.shopee_analytics import levels
from juli_backend.services.shopee_builder import picker_table

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/src/juli_backend/services"
D = Decimal

#: the product-level read paths (Track QUERY's files)
PRODUCT_LEVEL_FILES = (
    "shopee_analytics/matrix.py",
    "shopee_analytics/rankings.py",
    "shopee_analytics/metric_view.py",
    "shopee_analytics/critical.py",
    "shopee_analytics/product.py",
    "shopee_analytics/queries.py",
    "shopee_builder/picker_table.py",
)
#: ProductProfit's after-ads margin / profit and its after-AFF contribution
AFTER_ADS = re.compile(r"\bpp\.(margin_pct|profit|contribution)\b|scope_margin_pct\(")


def _pb(revenue: int, commission: int, **kw: Any) -> SimpleNamespace:
    base = {
        "excluded_reason": None,
        "revenue": D(revenue),
        "cogs": D(revenue) * D("0.4"),
        "vat_input_credit": D(0),
        "packaging": D(0),
        "fees_total": D(revenue) * D("0.1"),
        "income_costs_total": D(0),
        "commission": D(commission),
        "promo_discount": D(0),
        "voucher": D(0),
        "bundle": D(0),
        # the line's contribution after the commission (``ProfitBreakdown.contribution``)
        "contribution": D(revenue) * D("0.5") - D(commission),
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _ln(product_id: str) -> SimpleNamespace:
    return SimpleNamespace(product_id=product_id)


@pytest.mark.parametrize(
    ("surface", "expected"),
    [
        ("tong_quan.kpi", ("profit", "margin")),
        ("tong_quan.channel_table", ("profit", "margin")),
        ("ke_hoach", ("profit", "margin")),
        ("tong_quan.product_list", ("contribution", "margin_contribution")),
        ("phan_tich.metric_view", ("contribution", "margin_contribution")),
        ("phan_tich.rankings", ("contribution", "margin_contribution")),
        ("phan_tich.product_page", ("contribution", "margin_contribution")),
        ("phan_tich.matrix", ("contribution", "margin_contribution")),
        ("quyet_dinh.picker", ("contribution", "margin_contribution")),
    ],
)
def test_l1_each_surface_reads_its_rung(surface: str, expected: tuple[str, ...]) -> None:
    assert levels.SURFACE_METRICS[surface] == expected


def test_l1_the_export_shows_all_three_rungs_and_every_id_is_in_the_registry() -> None:
    assert set(levels.SURFACE_METRICS["export.tong_quan"]) == {
        "gross_profit",
        "margin_gross",
        "contribution",
        "margin_contribution",
        "profit",
        "margin",
    }
    for ids in levels.SURFACE_METRICS.values():
        assert all(i in METRICS for i in ids)
    for surface in levels.PRODUCT_LEVEL:
        assert not set(levels.SURFACE_METRICS[surface]) & levels.NET_ONLY, surface


@pytest.mark.parametrize("rel", PRODUCT_LEVEL_FILES)
def test_l1_no_product_level_surface_reads_the_after_ads_product_profit(rel: str) -> None:
    text = (BACKEND / rel).read_text(encoding="utf-8")
    assert AFTER_ADS.findall(text) == []


def test_l1_product_contribution_is_before_ads_and_affiliate_on_the_covered_base() -> None:
    pairs = [
        (_ln("p1"), _pb(1000, 100)),
        (_ln("p1"), _pb(500, 0)),
        # a line without every cost known is outside the base
        (_ln("p1"), _pb(400, 0, contribution=None)),
    ]
    pc = levels.contribution_of(pairs)
    # (1500 - 600 - 150) = 750: the commission is NOT deducted (before AFF)
    assert pc.contribution == D(750)
    assert pc.net_revenue_known == D(1500)
    assert pc.margin_pct == D("50.0")


def test_l1_no_covered_line_is_none_never_zero() -> None:
    pc = levels.contribution_of([(_ln("p1"), _pb(400, 0, contribution=None))])
    assert (pc.contribution, pc.margin_pct, pc.net_revenue_known) == (None, None, None)


def test_l1_the_picker_margin_is_bien_dong_gop_not_the_after_ads_margin() -> None:
    view = SimpleNamespace(
        pairs=[(_ln("p1"), _pb(1000, 100)), (_ln("p2"), _pb(400, 0, contribution=None))],
        # an after-ads margin the picker must not show
        profit=SimpleNamespace(products={"p1": SimpleNamespace(margin_pct=D("2.0"))}),
    )
    got = picker_table._margin_by_item(cast(Any, view))
    assert got == {"p1": 50.0}


def test_l4_one_metric_id_per_label() -> None:
    labels = Counter(m.label_vi for m in METRICS.values())
    assert [label for label, n in labels.items() if n > 1] == []
    assert METRICS["contribution"].label_vi == "Lợi nhuận đóng góp"


#: Track QUERY's screens (Tổng quan, Phân tích, the picker card); Đề xuất / builder are OPP's
QUERY_SCREENS = ("apps/demo/src/components/shopee-analytics",)


def test_l4_no_query_screen_shows_the_after_aff_contribution_label() -> None:
    hits = [
        str(p.relative_to(ROOT))
        for d in QUERY_SCREENS
        for p in (ROOT / d).rglob("*.tsx")
        if "__tests__" not in p.parts
        and "Đóng góp trước quảng cáo" in p.read_text(encoding="utf-8")
    ]
    assert hits == []
