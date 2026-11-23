"""W3 t2 (batch-1123 TikTok): the registry's TikTok source rules (decision #7), the TikTok channel
table (R-1 / R-2 / M-4), the widened gate, the platform-aware refusals. Pure unit: no database.

Synthetic fixture shaped like layer 4 (A-34 blocks): the four sources add up to the total, Tab cửa
hàng overlaps them. No shop ids or client figures.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from juli_backend.api import capability_gate as gate
from juli_backend.api.routes import shopee_analytics_common as common
from juli_backend.services.metrics.registry import (
    DERIVATION_VERSION,
    REASON_ADS_SCOPE_MISSING,
    REASON_SOURCE_NOT_ON_PLATFORM,
    REASON_TAB_REPORTS_NO_ORDERS,
    Platform,
    counts_in_total,
    metric_reason,
    source_available,
    source_reason,
)
from juli_backend.services.shopee_analytics import channel_split, metric_view
from juli_backend.services.shopee_analytics.funnel import FunnelRows, SourceDay, base_from_rows
from juli_backend.services.shopee_analytics.queries import NoShopeeData
from juli_backend.services.shopee_analytics.stored import RowsNotMaterialized
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine.contract import SOURCES

D = Decimal
DAY = date(2026, 10, 1)
W = Window(DAY, DAY)
TIKTOK, SHOPEE = Platform.tiktok, Platform.shopee
#: (views, clicks, orders, gmv) per A-34 block; the first four sum to the shop total
BLOCKS = {
    "the_san_pham_khac": (5000, 400, 30, 3_000_000),
    "video": (3000, 150, 12, 1_200_000),
    "live": (2000, 100, 8, 800_000),
    "lien_ket": (1000, 50, 5, 500_000),
    "trang_shop": (900, 105, 9, 900_000),  # overlaps the four: never in the total
}
TOTAL = (11000, 700, 55, 5_500_000)


def _rows() -> FunnelRows:
    out = []
    for s in SOURCES:
        if s not in BLOCKS:
            continue
        v, c, o, g = BLOCKS[s]
        out.append(SourceDay(DAY, None, s, v, c, o, D(g), D(0)))
    return FunnelRows(W, tuple(out))


def _by_key(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["key"]: r for r in rows}


# -- registry (M-4 registry half, R-2) -------------------------------------------------------


def test_registry_version_is_bumped_for_the_tiktok_source_rules() -> None:
    assert DERIVATION_VERSION == "2026-11-23.1"


@pytest.mark.parametrize("source", ["the_san_pham_khac", "trang_shop", "live", "video", "lien_ket"])
def test_decision_7_sources_are_available_on_tiktok(source: str) -> None:
    assert source_available(TIKTOK, source) and source_available(SHOPEE, source)
    assert source_reason(TIKTOK, source) is None


def test_ads_and_the_residual_are_unavailable_on_tiktok_with_a_reason_code() -> None:
    assert not source_available(TIKTOK, "ads")
    assert source_reason(TIKTOK, "ads") == REASON_ADS_SCOPE_MISSING
    assert source_reason(TIKTOK, "chenh_lech_nguon") == REASON_SOURCE_NOT_ON_PLATFORM
    assert source_reason(SHOPEE, "ads") is None


def test_tab_cua_hang_is_outside_the_total_on_tiktok_only() -> None:
    assert not counts_in_total(TIKTOK, "trang_shop")
    assert counts_in_total(SHOPEE, "trang_shop")
    for source in ("the_san_pham_khac", "video", "live", "lien_ket"):
        assert counts_in_total(TIKTOK, source)


def test_tab_cua_hang_has_no_orders_ctor_or_aov_on_tiktok() -> None:
    for metric in ("orders", "ctor", "aov"):
        assert metric_reason(TIKTOK, "trang_shop", metric) == REASON_TAB_REPORTS_NO_ORDERS
    for metric in ("views", "clicks", "ctr", "gmv"):
        assert metric_reason(TIKTOK, "trang_shop", metric) is None
    assert metric_reason(SHOPEE, "trang_shop", "orders") is None
    assert metric_reason(TIKTOK, "video", "orders") is None


# -- the TikTok channel table (R-1, R-2, M-4) --------------------------------------------------


def test_the_four_sources_add_up_to_the_total_and_the_tab_is_beside_them() -> None:
    base = base_from_rows(_rows(), "shop")
    rows = _by_key(channel_split.split_rows(base, platform="tiktok"))
    assert rows["organic"]["gmv"] + rows["affiliate"]["gmv"] == TOTAL[3]
    assert rows["organic"]["orders"] + rows["affiliate"]["orders"] == TOTAL[2]
    assert rows["organic"]["views"] + rows["affiliate"]["views"] == TOTAL[0]
    assert rows["organic"]["clicks"] + rows["affiliate"]["clicks"] == TOTAL[1]
    assert rows["organic_shop"]["gmv"] == BLOCKS["trang_shop"][3]
    children = sum(rows[k]["gmv"] for k in ("organic_card", "organic_video", "organic_live"))
    assert children == rows["organic"]["gmv"]  # the tab is not a child of the sum
    # shares are of the 4-source total, so the tab's share is of that total, not part of it
    assert rows["organic"]["share"] + rows["affiliate"]["share"] == pytest.approx(1.0, abs=0.001)


def test_tab_orders_ctor_aov_are_none_with_the_reason_never_zero() -> None:
    base = base_from_rows(_rows(), "shop")
    tab = _by_key(channel_split.split_rows(base, platform="tiktok"))["organic_shop"]
    assert tab["orders"] is None and tab["ctor"] is None and tab["aov"] is None
    assert tab["unavailable"] == {
        "orders": REASON_TAB_REPORTS_NO_ORDERS,
        "ctor": REASON_TAB_REPORTS_NO_ORDERS,
        "aov": REASON_TAB_REPORTS_NO_ORDERS,
    }
    assert tab["views"] == BLOCKS["trang_shop"][0] and tab["ctr"] is not None


def test_ads_rows_are_none_with_the_scope_reason() -> None:
    base = base_from_rows(_rows(), "shop")
    rows = _by_key(channel_split.split_rows(base, platform="tiktok"))
    for key in ("ads", "ads_product", "ads_shop"):
        row = rows[key]
        assert all(row[m] is None for m in ("views", "clicks", "gmv", "orders", "ctr", "aov"))
        assert set(row["unavailable"].values()) == {REASON_ADS_SCOPE_MISSING}


def test_rows_with_data_carry_no_reason_field() -> None:
    base = base_from_rows(_rows(), "shop")
    rows = _by_key(channel_split.split_rows(base, platform="tiktok"))
    assert "unavailable" not in rows["organic"] and "unavailable" not in rows["affiliate"]


def test_the_shop_total_base_leaves_the_tab_out_on_tiktok_only() -> None:
    base = base_from_rows(_rows(), "shop")
    assert channel_split.total_base(base, "tiktok").total("gmv") == TOTAL[3]
    assert channel_split.total_base(base, "shopee") is base


def test_shopee_rows_are_untouched_by_the_platform_parameter() -> None:
    base = base_from_rows(_rows(), "shop")
    default = channel_split.split_rows(base)
    assert channel_split.split_rows(base, platform="shopee") == default
    assert all("unavailable" not in r for r in default)


# -- metric-view cells (X-1: the same number per metric on every endpoint) ---------------------


def test_metric_view_cells_equal_the_channel_split_cells_on_tiktok() -> None:
    base = base_from_rows(_rows(), "shop")
    split = _by_key(channel_split.split_rows(base, platform="tiktok"))
    keys = {
        "the_san_pham": "organic_card",
        "video": "organic_video",
        "live": "organic_live",
        "trang_shop": "organic_shop",
        "lien_ket": "affiliate",
    }
    for channel, key in keys.items():
        cell = metric_view.channel_cell(base, channel, platform="tiktok")
        assert cell is not None
        assert cell.gmv == split[key]["gmv"], channel
        assert cell.clicks == split[key]["clicks"], channel
    whole = metric_view.channel_cell(base, "all", platform="tiktok")
    assert whole is not None and whole.gmv == TOTAL[3] and whole.orders == TOTAL[2]
    assert whole.gmv == split["organic"]["gmv"] + split["affiliate"]["gmv"]
    assert metric_view.channel_cell(base, "ads", platform="tiktok") is None


def test_metric_view_names_the_unavailable_luong_by_reason() -> None:
    got = metric_view.unavailable_channels("tiktok", "orders")
    assert got == {
        "trang_shop": REASON_TAB_REPORTS_NO_ORDERS,
        "ads_product": REASON_ADS_SCOPE_MISSING,
        "ads_shop": REASON_ADS_SCOPE_MISSING,
    }
    assert "trang_shop" not in metric_view.unavailable_channels("tiktok", "gmv")


# -- the gate and the refusals (R-1) -------------------------------------------------------------


def _open(platform: str, **kw: Any) -> HTTPException | None:
    try:
        gate.check_open(platform, "read_shop_totals", **kw)
    except HTTPException as exc:
        return exc
    return None


def test_analytics_platforms_open_the_routes_to_tiktok_and_the_default_stays_shopee() -> None:
    assert _open("tiktok", requires_data_on=gate.ANALYTICS_DATA_PLATFORMS) is None
    assert _open("shopee", requires_data_on=gate.ANALYTICS_DATA_PLATFORMS) is None
    refused = _open("tiktok")
    assert refused is not None and refused.status_code == 409


def test_the_analytics_routes_use_the_widened_gate_and_the_exports_do_not() -> None:
    from juli_backend.api.routes import demo_shopee_analytics as mod

    widened = {
        r.path
        for r in mod.router.routes
        if "exports" not in r.path and getattr(r, "dependant", None) is not None
    }
    assert len(widened) == 12
    closure = mod._gate_r.__closure__ or ()
    assert gate.ANALYTICS_DATA_PLATFORMS in [c.cell_contents for c in closure]
    closure_x = mod._gate_x.__closure__ or ()
    assert gate.DEFAULT_DATA_PLATFORMS in [c.cell_contents for c in closure_x]


def test_no_data_refusal_names_the_platform_and_shopee_is_unchanged() -> None:
    shopee = common.refusal(NoShopeeData("x"))
    assert shopee.status_code == 409
    assert shopee.detail == {"code": "no_shopee_data", "message": "Shop chưa có dữ liệu Shopee."}
    assert common.refusal(NoShopeeData("x"), "shopee").detail == shopee.detail
    tiktok = common.refusal(NoShopeeData("x"), "tiktok")
    assert tiktok.status_code == 409 and tiktok.detail["code"] == "no_tiktok_data"


def test_rows_not_materialized_is_the_same_409_for_both_platforms() -> None:
    exc = RowsNotMaterialized(W, [DAY])
    assert common.refusal(exc, "tiktok").detail == common.refusal(exc, "shopee").detail
    assert common.refusal(exc, "tiktok").detail["code"] == "rows_not_materialized"


async def test_a_dependency_opens_a_tiktok_shop_on_the_widened_gate() -> None:
    async def resolved(shop: Any) -> Any:
        return shop

    dep = gate.require_capability(
        "read_shop_totals",
        requires_data_on=gate.ANALYTICS_DATA_PLATFORMS,
        shop_dependency=resolved,
    )
    tiktok = SimpleNamespace(platform="tiktok", id=uuid.uuid4())
    assert await dep(tiktok) is tiktok


def test_stamped_renames_the_platform_for_tiktok_only() -> None:
    body = {
        "platform": "shopee",
        "label": "GMV shop (Shopee)",
        "rows": [{"note": "Doanh số của Shopee"}],
        "ads": {"spend": 0, "gmv_placed": 0, "basis": {"key": "placed"}},
    }
    assert common.stamped(body, "shopee") is body and body["label"] == "GMV shop (Shopee)"
    got = common.stamped(body, "tiktok")
    assert got["platform"] == "tiktok" and got["label"] == "GMV shop (TikTok Shop)"
    assert got["rows"][0]["note"] == "Doanh số của TikTok Shop"
    assert got["ads"]["spend"] is None and got["ads"]["gmv_placed"] is None
    assert got["ads"]["basis"] == {"key": "placed"}
    assert got["unavailable"] == {"ads": REASON_ADS_SCOPE_MISSING}
