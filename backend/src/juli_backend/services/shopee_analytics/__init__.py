"""Shopee analytics read APIs (P90 step 7): the stored data wired to ``services/shopee_profit``.

Loaders read the stored Shopee data per shop and window through repositories; builders are pure
over the loaded views and return JSON-ready payloads for Tổng quan, Phân tích, Sản phẩm and
Xếp hạng. See ``MODULE.md``.
"""

from __future__ import annotations

from juli_backend.services.shopee_analytics.compute import PeriodView, compute_view
from juli_backend.services.shopee_analytics.critical import build_critical
from juli_backend.services.shopee_analytics.matrix import build_matrix
from juli_backend.services.shopee_analytics.overview import build_overview
from juli_backend.services.shopee_analytics.product import build_product_page
from juli_backend.services.shopee_analytics.queries import NoShopeeData, ProductNotFound
from juli_backend.services.shopee_analytics.rankings import build_ranking
from juli_backend.services.shopee_analytics.service import load_period_data, load_view, resolve
from juli_backend.services.shopee_analytics.stored import RowsNotMaterialized
from juli_backend.services.shopee_analytics.windows import (
    PERIOD_KINDS,
    InvalidWindow,
    Window,
    resolve_window,
)

__all__ = [
    "PERIOD_KINDS",
    "InvalidWindow",
    "RowsNotMaterialized",
    "NoShopeeData",
    "PeriodView",
    "ProductNotFound",
    "Window",
    "build_critical",
    "build_matrix",
    "build_overview",
    "build_product_page",
    "build_ranking",
    "compute_view",
    "load_period_data",
    "load_view",
    "resolve",
    "resolve_window",
]
