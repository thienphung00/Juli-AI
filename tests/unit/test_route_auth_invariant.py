"""CI invariant (#900, ADR-061 decision 2): every product route must resolve a
session/ownership dependency.

This test inspects the *live* route table on the deployed ASGI app object
(``juli_backend.api.main:app`` — the same app uvicorn serves, including the
``/health`` route only registered there) rather than parsing route source
text, so it cannot be fooled by formatting or by a docstring that merely
*claims* a route is protected.

Only two dependencies count as "session/ownership resolved":

- ``get_current_user`` (core/security/dependencies.py) — verifies the
  Supabase JWT and returns the authenticated ``User``.
- ``get_active_shop`` (api/dependencies.py) — additionally resolves the
  ``X-Shop-Id`` header to a ``Shop`` the authenticated user actually owns.

Every other product route must depend on one of these, directly or
transitively (``get_active_shop`` itself depends on ``get_current_user``, so
routes using either are covered).

Intentionally public surfaces are listed in ``ALLOWLISTED_PRODUCT_ROUTES``
below, keyed by the *exact* ``(method, path)`` pair — never a prefix or
pattern — so a new route can never accidentally inherit an allowlist entry;
widening the allowlist is always a visible, reviewable line-level diff. Each
entry carries an inline comment stating why it is public. See the PR body
for #900 for the full reasoning, including the deliberate choice to
allowlist ``/debug/tiktok/verify-connection`` (tracked separately as #903)
rather than fail this build.
"""

from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.main import app
from juli_backend.core.security.dependencies import get_current_user

# Exact (HTTP method, path) pairs only — no prefixes, no regexes, no
# wildcards. Adding an entry here is the reviewable action; anything not
# listed here must resolve get_current_user or get_active_shop or this test
# fails and names it.
ALLOWLISTED_PRODUCT_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/health"): (
        "Infra liveness/readiness probe (api/main.py) — no product data, no auth concept."
    ),
    ("POST", "/webhooks/tiktok"): (
        "TikTok webhook receiver (services/webhook) — HMAC-signature authenticated via "
        "hmac.compare_digest against the TikTok app secret, not session-authenticated. "
        "The caller is TikTok's Partner Center, which cannot hold a Juli session."
    ),
    ("GET", "/v1/demo/analytics"): (
        "Public Demo Analytics read (#531, ADR-037) — unauthenticated by design. Serves a "
        "server-bound DEMO_REFERENCE_SHOP_ID; no client-controllable shop_id anywhere "
        "(rejected as a query param, never read as a header)."
    ),
    ("GET", "/v1/demo/decisions"): (
        "Public Demo Decisions list (#718, B-6) — same ADR-037 unauthenticated-by-design "
        "pattern as GET /v1/demo/analytics; server-bound reference shop only."
    ),
    ("GET", "/v1/demo/decisions/{action_card_id}"): (
        "Public Demo Decisions detail (#718, B-6) — same ADR-037 pattern as the list route; "
        "a suppressed/foreign-shop card is indistinguishable from a nonexistent id (404)."
    ),
    ("POST", "/v1/demo/decisions/{action_card_id}/approve"): (
        "Public Demo approve->execute (#717, B-5) — same ADR-037 pattern. Writes only a "
        "local dry-run execution record against the server-bound reference shop; no real "
        "shop, TikTok credential, or user data is ever touched."
    ),
    ("GET", "/v1/auth/tiktok/callback"): (
        "TikTok Shop OAuth redirect callback — authenticated by a signed OAuth `state` "
        "token (TikTokOAuthInfrastructureService.verify_state), which binds the callback "
        "to a user_id. This route *establishes* the session by exchanging the code, so it "
        "cannot itself require one — the state token is the credential."
    ),
    ("GET", "/v1/auth/tiktok/business/callback"): (
        "TikTok Business Advertiser OAuth callback — same signed-state-token pattern as "
        "GET /v1/auth/tiktok/callback (TikTokBusinessAdvertiserOAuthService.handle_callback)."
    ),
    ("GET", "/v1/auth/tiktok/business/account-holder/callback"): (
        "TikTok Business account-holder OAuth callback — same signed-state-token pattern, "
        "verified via HMAC in `_verify_state()`; persists no tokens (infra-only)."
    ),
    ("GET", "/debug/tiktok/verify-connection"): (
        "TODO(#903): has NO auth today beyond the ENABLE_TIKTOK_DEBUG env flag — a known "
        "cross-tenant IDOR (client-supplied shop_id, no ownership check), documented in "
        "ADR-061 decision 2 step 7 as #903's job to close. Allowlisted here deliberately: "
        "#900 is an assertion over the current route set, not a fix, and the exit gate "
        "requires this test to pass against that current (imperfect) state. Remove this "
        "entry when #903 adds real auth to the route, not before."
    ),
}

_SESSION_DEPENDENCIES = frozenset({get_current_user, get_active_shop})


def _product_api_routes() -> list[APIRoute]:
    """Live route table on the deployed app — APIRoute only.

    Filters out the plain ``starlette.routing.Route`` objects FastAPI wires
    up itself for /docs, /redoc, /openapi.json, and the Swagger OAuth2
    redirect: those are framework-internal, not product routes, and (unlike
    APIRoute) carry no ``.dependant`` to inspect.
    """
    return [route for route in app.routes if isinstance(route, APIRoute)]


def _dependency_calls(dependant: Any) -> set[Any]:
    """Flatten a FastAPI Dependant tree into the set of underlying callables.

    Walks sub-dependencies recursively so a route depending on
    ``get_active_shop`` (which itself depends on ``get_current_user``) is
    correctly credited for both.
    """
    calls: set[Any] = set()
    stack = [dependant]
    seen_ids: set[int] = set()
    while stack:
        node = stack.pop()
        if id(node) in seen_ids:
            continue
        seen_ids.add(id(node))
        if node.call is not None:
            calls.add(node.call)
        stack.extend(node.dependencies)
    return calls


def test_every_product_route_resolves_a_session_dependency() -> None:
    """Every registered route either resolves get_current_user/get_active_shop
    or is named, with a reason, in ALLOWLISTED_PRODUCT_ROUTES."""
    offenders: list[str] = []

    for route in _product_api_routes():
        methods = sorted(route.methods or ())
        for method in methods:
            allowlist_reason = ALLOWLISTED_PRODUCT_ROUTES.get((method, route.path))
            if allowlist_reason is not None:
                continue

            calls = _dependency_calls(route.dependant)
            if not calls & _SESSION_DEPENDENCIES:
                offenders.append(f"{method} {route.path} (endpoint={route.name})")

    assert not offenders, (
        "Route(s) resolve no session/ownership dependency (get_current_user / "
        "get_active_shop) and are not in the explicit ALLOWLISTED_PRODUCT_ROUTES: "
        f"{offenders}. If this route is genuinely public, add it to the allowlist "
        "in tests/unit/test_route_auth_invariant.py with an inline justification; "
        "otherwise wire get_current_user or get_active_shop into it."
    )


def test_allowlist_entries_all_correspond_to_currently_registered_routes() -> None:
    """Guards against a stale allowlist entry masking a route that moved/was removed —
    every allowlisted (method, path) must match a route actually on the live app."""
    registered: set[tuple[str, str]] = set()
    for route in _product_api_routes():
        for method in route.methods or ():
            registered.add((method, route.path))

    stale = sorted(set(ALLOWLISTED_PRODUCT_ROUTES) - registered)
    assert not stale, (
        f"Allowlist entries with no matching registered route (stale — remove them): {stale}"
    )
