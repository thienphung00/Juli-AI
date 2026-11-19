"""W1/W2: the capability gate keeps every Shopee-only route Shopee-only (TikTok unchanged).

Pure unit: the real app, no database. Every handler that carries the gate must answer a TikTok
shop with the 409 ``not_a_shopee_shop`` body the inline guards always gave, and the number of
gated handlers is pinned so a handler cannot lose its gate unnoticed.
"""

from __future__ import annotations

import importlib
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from juli_backend.api import capability_gate as gate
from juli_backend.api.app import create_app
from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.routes.ops import get_ops_context
from juli_backend.core.security import get_current_user
from juli_backend.database import get_session
from juli_backend.services.capabilities import CAPABILITIES, Route, can

BODY = {"code": "not_a_shopee_shop", "message": "this shop is not on Shopee"}
# batch-1118g F3.1: +1 each for the revert-fill routes: seller
# POST /demo/shopee/recommendations/{id}/revert-fill (`_gate_w`) and ops
# POST /ops/shops/{shop_id}/shopee/recommendations/{card_id}/revert-fill (`require_ops_capability`)
SELLER_GATED = 90  # +1 F6 (board import status / revoke-inactive seller route)
OPS_GATED = 94


def _refusal(platform: str, capability: str | None, **kw: Any) -> HTTPException | None:
    try:
        gate.check_open(platform, capability, **kw)
    except HTTPException as exc:
        return exc
    return None


def test_shopee_passes_and_tiktok_is_refused_with_the_inline_guard_body() -> None:
    assert _refusal("shopee", None) is None
    refused = _refusal("tiktok", None)
    assert refused is not None
    assert (refused.status_code, refused.detail) == (409, BODY)


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_tiktok_is_refused_for_every_capability_even_where_can_says_api(capability: str) -> None:
    refused = _refusal("tiktok", capability)
    assert refused is not None
    assert (refused.status_code, refused.detail) == (409, BODY)


@pytest.mark.parametrize("capability", ["read_orders", "read_shop_totals", "read_ads"])
def test_the_reads_the_routes_use_are_open_on_shopee(capability: str) -> None:
    assert can("shopee", capability).route is not Route.none
    assert _refusal("shopee", capability) is None


def test_a_capability_the_platform_lacks_is_refused_even_on_a_data_platform() -> None:
    assert can("shopee", "shop_tab").route is Route.none
    refused = _refusal("shopee", "shop_tab")
    assert refused is not None and refused.status_code == 409


def test_widening_requires_data_on_is_what_opens_a_route() -> None:
    assert _refusal("tiktok", "read_orders", requires_data_on=("shopee", "tiktok")) is None
    refused = _refusal("tiktok", "live_schedule", requires_data_on=("shopee", "tiktok"))
    assert refused is not None  # data there, but the capability is not declared as a route


async def test_the_seller_dependency_returns_the_shop_or_refuses() -> None:
    async def resolved(shop: Any) -> Any:
        return shop

    dep = gate.require_capability("read_shop_totals", shop_dependency=resolved)
    shopee = SimpleNamespace(platform="shopee", id=uuid.uuid4())
    assert await dep(shopee) is shopee
    with pytest.raises(HTTPException) as refused:
        await dep(SimpleNamespace(platform="tiktok", id=uuid.uuid4()))
    assert (refused.value.status_code, refused.value.detail) == (409, BODY)


GATED_MODULES = (
    "demo_planned_changes",
    "demo_shopee_analytics",
    "demo_shopee_board",
    "demo_shopee_builder",
    "demo_shopee_builder_p98",
    "demo_shopee_market",
    "demo_shopee_pages",
    "demo_shopee_reco_execution",
    "demo_shopee_reco_manual",
    "demo_shopee_reco_plan",
    "demo_shopee_recommendations",
    "demo_stock_alert",
    "ingest_fill",
    "ops_planned_changes",
    "ops_shopee_analytics",
    "ops_shopee_backtest",
    "ops_shopee_builder",
    "ops_shopee_dashboards",
    "ops_shopee_funnel",
    "ops_shopee_keywords",
    "ops_shopee_market",
    "ops_shopee_orders",
    "ops_shopee_reco_execution",
    "ops_shopee_reco_manual",
    "ops_shopee_reco_plan",
    "ops_shopee_recommendations",
)


def _all_routes(_app: Any) -> list[APIRoute]:
    """The routes of the 26 route files, from their own routers (paths carry the router prefix)."""
    found: list[APIRoute] = []
    for name in GATED_MODULES:
        module = importlib.import_module(f"juli_backend.api.routes.{name}")
        for attr in ("router", "seller_router"):
            router = getattr(module, attr, None)
            if router is not None:
                found.extend(r for r in router.routes if isinstance(r, APIRoute))
    return found


def _dependants(dependant: Any) -> list[Any]:
    out = [dependant]
    for sub in dependant.dependencies:
        out.extend(_dependants(sub))
    return out


def _gate_kind(route: APIRoute) -> str | None:
    for dep in _dependants(route.dependant):
        name = getattr(dep.call, "__qualname__", "")
        if name.startswith("require_capability.<locals>"):
            return "seller"
        if name.startswith("require_ops_capability.<locals>"):
            return "ops"
    return None


def _routes_by_kind(app: Any) -> dict[str, list[APIRoute]]:
    kinds: dict[str, list[APIRoute]] = {"seller": [], "ops": []}
    for route in _all_routes(app):
        kind = _gate_kind(route)
        if kind is not None:
            kinds[kind].append(route)
    return kinds


def test_the_number_of_gated_handlers_is_pinned() -> None:
    kinds = _routes_by_kind(create_app())
    assert (len(kinds["seller"]), len(kinds["ops"])) == (SELLER_GATED, OPS_GATED)


async def test_every_gated_handler_still_refuses_a_tiktok_shop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    tiktok = SimpleNamespace(platform="tiktok", id=uuid.uuid4(), name="x")

    class _Session:
        async def commit(self) -> None:
            return None

    async def session() -> Any:
        yield _Session()

    async def listing(_session: Any, shop_id: uuid.UUID) -> Any:
        return SimpleNamespace(platform="tiktok", shop_name="x", shop_id=shop_id)

    ctx = SimpleNamespace(staff=SimpleNamespace(at_least=lambda _role: True))
    monkeypatch.setattr(gate, "_shop", listing)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_active_shop] = lambda: tiktok
    app.dependency_overrides[require_writable_shop] = lambda: tiktok
    app.dependency_overrides[get_ops_context] = lambda: ctx
    app.dependency_overrides[get_session] = session

    wrong: list[tuple[str, int, Any]] = []
    checked = 0
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for kind, routes in _routes_by_kind(app).items():
            for route in routes:
                path = "/v1" + route.path_format
                for name in route.dependant.path_params:
                    path = path.replace("{" + name.name + "}", str(uuid.uuid4()))
                method = sorted(route.methods or {"GET"})[0]
                response = await client.request(
                    method, path, headers={"X-Shop-Id": str(uuid.uuid4())}, json={}
                )
                checked += 1
                detail = response.json().get("detail") if response.content else None
                if response.status_code != 409 or detail != BODY:
                    wrong.append((f"{kind} {method} {route.path}", response.status_code, detail))
    app.dependency_overrides.clear()
    assert checked == SELLER_GATED + OPS_GATED
    assert wrong == []
