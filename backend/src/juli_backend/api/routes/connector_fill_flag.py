"""``GET /v1/demo/connector-fill`` and ``GET /v1/ops/connector-fill``: whether the screens show
"Điền bằng Connector" (p91 D-13). The flag is the server's ``CONNECTOR_FILL_LISTING``; the
Connector adds its own gate (flag ``fill_listing`` in the extension and the pilot shop list), so
the button may show for a shop whose Connector will do nothing -- it then opens the page only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes.ops import MaskedRoute, OpsContext, viewer
from juli_backend.database import Shop
from juli_backend.services.shopee_recommendations import fill

demo_router = APIRouter(prefix="/demo", tags=["demo"])
ops_router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)


@demo_router.get("/connector-fill")
async def demo_connector_fill(shop: Shop = Depends(get_active_shop)) -> dict[str, Any]:
    return {"data": {"enabled": fill.enabled(), "hash_prefix": "juli-fill"}}


@ops_router.get("/connector-fill")
async def ops_connector_fill(ctx: OpsContext = Depends(viewer)) -> dict[str, Any]:
    return {"data": {"enabled": fill.enabled(), "hash_prefix": "juli-fill"}}
