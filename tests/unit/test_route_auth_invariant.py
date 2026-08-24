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
for #900 for the full reasoning. The one deliberate allowlist exception it
carried — ``/debug/tiktok/verify-connection`` — has since been closed by #903:
that route now depends on ``get_active_shop`` and is not mounted in production
at all, so it needs no exception and the entry is gone.
"""

from __future__ import annotations

from typing import Any

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.main import app
from juli_backend.core.security.dependencies import get_current_user

try:
    # FastAPI's own OpenAPI generator (fastapi/openapi/utils.py) walks routes
    # through this exact function to resolve the *effective* (fully-prefixed,
    # fully-dependency-merged) route table — the same problem this test has.
    # Newer FastAPI (the `_IncludedRouter` route-registration redesign) stops
    # flattening `app.include_router(...)` targets into `app.routes` eagerly;
    # a route added that way is wrapped opaquely and only resolves to its real
    # path/methods/dependant lazily, on demand, through `iter_route_contexts`.
    # Reading `app.routes` directly under that FastAPI silently sees only the
    # handful of routes registered directly on `app` (e.g. `/health`) and
    # nothing added via `include_router` — this is what actually broke this
    # test in CI (fastapi 0.141.1 / starlette 1.6.0) while passing locally
    # against an older, eagerly-flattening FastAPI (0.128.0 / starlette
    # 0.50.0): every route added via `include_router` (all of `/v1/*`, the
    # webhook receiver, and the debug route) vanished from the walk, both
    # tests below silently degraded to iterating zero/near-zero routes, and
    # the "no matching registered route" failure was a symptom of an empty
    # route table, not allowlist staleness. Older FastAPI has no such
    # function; the `except ImportError` branch below covers it by reading
    # `app.routes` directly, which is already flat there.
    from fastapi.routing import iter_route_contexts as _iter_route_contexts
except ImportError:  # pragma: no cover - exercised by whichever FastAPI is installed
    _iter_route_contexts = None

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
        "(rejected as a query param, never read as a header). Out of scope for #1283 — "
        "ADR-075 decision 3 left this read-only route as a deliberate exception; only the "
        "two Demo Decisions routes below (#718, B-6) were reconsidered."
    ),
    # GET /v1/demo/decisions and GET /v1/demo/decisions/{action_card_id} (#718, B-6)
    # used to be here too — unauthenticated, server-bound DEMO_REFERENCE_SHOP_ID, same
    # ADR-037 pattern as GET /v1/demo/analytics above. #1283: on the deployed host that
    # reference shop was a real merchant's production shop, so both routes served a live
    # seller's recommendations to any caller with no credentials at all. ADR-075 decision
    # 3 had deliberately left these two read-only routes as "P-UI's call"; #1283 is that
    # call — both now resolve get_active_shop (X-Shop-Id, ownership-checked) exactly like
    # POST /v1/demo/decisions/{action_card_id}/approve below, closing the exposure and the
    # listing/approving split (a caller could see a card via these routes it could not
    # approve) in one move. Removed from this allowlist entirely, not just re-justified.
    #
    # POST /v1/demo/decisions/{action_card_id}/approve was ALSO here until #1283 —
    # justified as "Public Demo approve->execute (#717, B-5) ... writes only a local
    # dry-run execution record against the server-bound reference shop". That was
    # already false by the time #1283 found it: #1222 had rewritten this route to
    # resolve get_active_shop + get_current_user and create a real workflow_run, not a
    # dry-run record. Because an allowlisted entry is *skipped* by
    # test_every_product_route_resolves_a_session_dependency above, this masked the
    # route from the very invariant #900 exists to enforce — if a future change had
    # dropped get_active_shop again, that test would have stayed green throughout,
    # having never once looked at the route. Removed entirely (not just re-justified);
    # test_allowlisted_routes_are_genuinely_unauthenticated below now fails loudly if
    # any allowlisted route is ever found to resolve a session dependency again.
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
}

_SESSION_DEPENDENCIES = frozenset({get_current_user, get_active_shop})

# Sanity floor for the live route walk. The app currently exposes 25 APIRoutes
# (verified locally against both fastapi 0.128.0/starlette 0.50.0 and, via a
# throwaway repro venv, fastapi 0.141.1/starlette 1.6.0 — both give 25 through
# the walk below). This exists so a broken walk fails LOUDLY with its actual
# count instead of silently passing vacuously (zero/near-zero routes to check
# means zero offenders, by construction) — which is exactly how the CI-only
# fastapi/starlette upgrade above broke this invariant the first time: one
# test passed vacuously while the other reported every allowlist entry
# "stale" because the registered set it was walking was nearly empty.
_MINIMUM_EXPECTED_PRODUCT_ROUTES = 20


def _product_api_routes() -> list[Any]:
    """Live route table on the deployed app, flattened and version-robust.

    Returns one entry per registered endpoint, each exposing ``.path``,
    ``.methods``, and ``.dependant`` (either a bare ``APIRoute`` on older
    FastAPI, where ``app.routes`` is already flat, or a ``RouteContext`` on
    newer FastAPI, resolved via ``iter_route_contexts`` — see the import
    comment above for why a flat read of ``app.routes`` alone is not
    version-robust). Filtered by duck-typing (has ``.dependant``, ``.path``,
    and ``.methods``) rather than ``isinstance(route, APIRoute)`` against the
    *container* object, since on newer FastAPI the container is a
    ``RouteContext`` wrapper, not an ``APIRoute`` itself — only its
    ``.original_route`` is. This is what excludes the framework-internal
    ``starlette.routing.Route`` objects for /docs, /redoc, /openapi.json, and
    the Swagger OAuth2 redirect, which carry no ``.dependant``.
    """
    candidates: Any = _iter_route_contexts(app.routes) if _iter_route_contexts else app.routes
    return [
        candidate
        for candidate in candidates
        if hasattr(candidate, "dependant")
        and hasattr(candidate, "path")
        and hasattr(candidate, "methods")
    ]


def _registered_route_summary(routes: list[Any]) -> list[str]:
    """`METHOD path` for every route the walk actually found — for diagnostic
    dumps on failure, so a CI-only discrepancy is readable from the log
    without needing local reproduction."""
    summary: list[str] = []
    for route in routes:
        for method in sorted(route.methods or ()):
            summary.append(f"{method} {route.path}")
    return sorted(summary)


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


def test_route_walk_finds_a_plausible_number_of_routes() -> None:
    """Non-vacuousness guard: both other tests in this file only prove anything
    if the walk actually found the app's routes. An empty (or near-empty)
    result makes "every route is protected" and "no allowlist entry is stale"
    trivially, silently true — which is precisely how this invariant broke in
    CI the first time (see the ``_iter_route_contexts`` import comment)."""
    routes = _product_api_routes()
    assert len(routes) >= _MINIMUM_EXPECTED_PRODUCT_ROUTES, (
        f"Route walk found only {len(routes)} route(s), expected at least "
        f"{_MINIMUM_EXPECTED_PRODUCT_ROUTES}. This almost certainly means the walk itself "
        "is broken (e.g. a FastAPI/Starlette upgrade changed how app.include_router() "
        "targets are exposed on app.routes) rather than that routes were actually removed "
        f"— treat this as a self-diagnosing signal, not a route-count regression. Routes "
        f"actually found: {_registered_route_summary(routes)}"
    )


def test_every_product_route_resolves_a_session_dependency() -> None:
    """Every registered route either resolves get_current_user/get_active_shop
    or is named, with a reason, in ALLOWLISTED_PRODUCT_ROUTES."""
    routes = _product_api_routes()
    offenders: list[str] = []

    for route in routes:
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
        "otherwise wire get_current_user or get_active_shop into it. Routes actually "
        f"registered ({len(routes)}): {_registered_route_summary(routes)}"
    )


def test_allowlisted_routes_are_genuinely_unauthenticated() -> None:
    """Closes the mask this whole allowlist mechanism can hide behind: an
    entry in ``ALLOWLISTED_PRODUCT_ROUTES`` is *skipped*, never checked, by
    ``test_every_product_route_resolves_a_session_dependency`` above --
    so a route that has since **gained** ``get_current_user`` /
    ``get_active_shop`` but is still listed here is invisible to that
    invariant. If a future change ever dropped the dependency again, that
    test would stay green throughout, having never actually looked at the
    route. This test asserts the opposite direction: every allowlisted
    route must resolve *no* session dependency at all, so the allowlist can
    only ever contain routes that are genuinely, currently public. Found
    live by #1283: ``POST /v1/demo/decisions/{action_card_id}/approve`` was
    allowlisted with a justification describing pre-#1222 unauthenticated
    dry-run behaviour, but the route itself was rewritten by #1222 to
    resolve ``get_active_shop`` -- this test failed against that entry
    before it was removed (see the #1283 PR for the failure output)."""
    routes = _product_api_routes()
    route_by_key: dict[tuple[str, str], Any] = {}
    for route in routes:
        for method in route.methods or ():
            route_by_key[(method, route.path)] = route

    masked: list[str] = []
    for key in ALLOWLISTED_PRODUCT_ROUTES:
        route = route_by_key.get(key)
        if route is None:
            # A stale (no-longer-registered) entry is already caught, with
            # its own clearer message, by
            # test_allowlist_entries_all_correspond_to_currently_registered_routes
            # -- nothing further to prove about it here.
            continue
        calls = _dependency_calls(route.dependant)
        if calls & _SESSION_DEPENDENCIES:
            method, path = key
            masked.append(f"{method} {path} (endpoint={route.name})")

    assert not masked, (
        "Allowlisted route(s) actually resolve a session/ownership dependency "
        "(get_current_user / get_active_shop) -- the allowlist entry is masking "
        "them from test_every_product_route_resolves_a_session_dependency, which "
        "skips anything allowlisted without ever checking it. This route is no "
        f"longer public: remove its ALLOWLISTED_PRODUCT_ROUTES entry. Masked: {masked}"
    )


def test_allowlist_entries_all_correspond_to_currently_registered_routes() -> None:
    """Guards against a stale allowlist entry masking a route that moved/was removed —
    every allowlisted (method, path) must match a route actually on the live app."""
    routes = _product_api_routes()
    registered: set[tuple[str, str]] = set()
    for route in routes:
        for method in route.methods or ():
            registered.add((method, route.path))

    stale = sorted(set(ALLOWLISTED_PRODUCT_ROUTES) - registered)
    assert not stale, (
        f"Allowlist entries with no matching registered route (stale — remove them): "
        f"{stale}. Routes actually registered ({len(routes)}): "
        f"{_registered_route_summary(routes)}"
    )
