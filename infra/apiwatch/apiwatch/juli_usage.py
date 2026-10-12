"""What Juli calls, derived from the backend source (no import of juli_backend, so
this runs with a bare python3).

* TikTok endpoints: every path built in ``integrations/tiktok/constants.py``.
* TikTok webhooks: the type codes in ``services/tiktok/webhook_catalog.py``.
* Shopee: any ``/api/v2/<module>/<name>`` path or ``v2.<module>.<name>`` API name in
  the backend source (none yet), plus the endpoints D31 plans to call first,
  reported as "planned".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from apiwatch.normalize import path_template

TIKTOK_CONSTANTS = "backend/src/juli_backend/integrations/tiktok/constants.py"
TIKTOK_WEBHOOK_CATALOG = "backend/src/juli_backend/services/tiktok/webhook_catalog.py"
BACKEND_SRC = "backend/src/juli_backend"

# D31.2: the thin Shopee client starts with the reads the 4-stream frame needs.
SHOPEE_PLANNED_ENDPOINTS = (
    "/api/v2/product/get_item_list",
    "/api/v2/product/get_item_base_info",
    "/api/v2/product/get_item_extra_info",
    "/api/v2/product/get_model_list",
    "/api/v2/order/get_order_list",
    "/api/v2/order/get_order_detail",
    "/api/v2/returns/get_return_list",
    "/api/v2/payment/get_escrow_detail",
    "/api/v2/shop/get_shop_info",
    "/api/v2/account_health/get_shop_performance",
    "/api/v2/ads/get_all_cpc_ads_daily_performance",
    "/api/v2/ads/get_product_campaign_daily_performance",
    "/api/v2/ams/get_shop_performance",
    "/api/v2/ams/get_product_performance",
    "/api/v2/ams/get_content_performance",
    "/api/v2/discount/get_discount_list",
    "/api/v2/voucher/get_voucher_list",
)
# order_status_push and shopee_updates (D31.10 logs the latter as a platform notice).
SHOPEE_PLANNED_PUSH_NAMES = ("order_status_push", "shopee_updates")

_VERSION_CONST = re.compile(r'^([A-Z][A-Z0-9_]*_VERSION)\s*=\s*"(\d{6})"', re.MULTILINE)
_FSTRING_JOIN = re.compile(r'"\s*\n\s*f"')
_FSTRING_PATH = re.compile(r'f"(/[a-z_]+/[^"]*)"')
_CATALOG_KEY = re.compile(r"^\s{4}(\d+):\s*CatalogEntry\(", re.MULTILINE)
_SHOPEE_PATH = re.compile(r"/api/v2/[a-z_]+/[a-z0-9_]+")
_SHOPEE_NAME = re.compile(r"\bv2\.([a-z_]+)\.([a-z0-9_]+)\b")


def tiktok_endpoints_from_constants(source: str) -> set[str]:
    versions = dict(_VERSION_CONST.findall(source))
    joined = _FSTRING_JOIN.sub("", source)
    out = set()
    for raw in _FSTRING_PATH.findall(joined):
        text = raw.replace("{{", "{").replace("}}", "}")
        text = re.sub(
            r"\{([A-Z][A-Z0-9_]*_VERSION)\}", lambda m: versions.get(m.group(1), m.group(0)), text
        )
        if "_VERSION}" in text:
            continue
        out.add(path_template(text))
    return out


def tiktok_webhooks_from_catalog(source: str) -> set[str]:
    return set(_CATALOG_KEY.findall(source))


def shopee_paths_from_source(sources: list[str]) -> set[str]:
    out: set[str] = set()
    for text in sources:
        out.update(_SHOPEE_PATH.findall(text))
        out.update(f"/api/v2/{m}/{n}" for m, n in _SHOPEE_NAME.findall(text))
    return out


def _read(root: Path, rel: str) -> str:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load(root: Path) -> dict[str, Any]:
    sources = [
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted((root / BACKEND_SRC).rglob("*.py"))
        if "shopee" in p.as_posix().lower()
    ]
    return {
        "tiktok": {
            "endpoints": tiktok_endpoints_from_constants(_read(root, TIKTOK_CONSTANTS)),
            "webhooks": tiktok_webhooks_from_catalog(_read(root, TIKTOK_WEBHOOK_CATALOG)),
            "planned_endpoints": set(),
            "planned_webhook_names": set(),
        },
        "shopee": {
            "endpoints": shopee_paths_from_source(sources),
            "webhooks": set(),
            "planned_endpoints": set(SHOPEE_PLANNED_ENDPOINTS),
            "planned_webhook_names": set(SHOPEE_PLANNED_PUSH_NAMES),
        },
    }
