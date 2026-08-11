"""Exit gate for #903 — what the API must not expose in production.

Two surfaces were open on every environment (ADR-061 decision 2):

1. ``/docs``, ``/redoc`` and ``/openapi.json`` handed anyone who could reach the host a
   complete map of every route, its parameters and its models.
2. ``/debug/tiktok/verify-connection`` was mounted unconditionally and gated only by its
   own ``ENABLE_TIKTOK_DEBUG`` flag — no session, no ownership check. An unauthenticated
   caller could supply an arbitrary ``shop_id`` and learn whether that shop had stored
   credentials, plus its identity. Its "off in production" status was a comment in an
   env template, not something the code enforced.

These tests assert the enforcement, in both directions: absent under production, present
otherwise. The both-directions part matters — a gate that also breaks local development
gets reverted, so "still works in development" is part of the contract, not a nicety.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from juli_backend.api.app import create_app

try:
    # Newer FastAPI (0.141.1 / starlette 1.6.0, which is what CI resolves) stopped
    # eagerly flattening `include_router` targets into `app.routes`; each is wrapped in
    # an opaque `_IncludedRouter` and only resolves lazily through this function. Reading
    # `app.routes` directly there sees ONLY the routes registered on the app itself —
    # which for this app means the docs routes and nothing else.
    #
    # This is not hypothetical: the first CI run of this file failed exactly that way
    # while passing locally on fastapi 0.128.0, which is #921's drift in miniature. Older
    # FastAPI has no such function and `app.routes` is already flat, hence the fallback.
    from fastapi.routing import iter_route_contexts as _iter_route_contexts
except ImportError:  # pragma: no cover - depends on the installed FastAPI
    _iter_route_contexts = None

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
DIAGNOSTIC_PATH = "/debug/tiktok/verify-connection"


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")


@pytest.fixture
def development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")


def _paths(app) -> set[str]:
    """Paths registered directly on the app — docs, redoc, schema.

    Safe to read flat: FastAPI registers these on the app itself, so they appear in
    ``app.routes`` under every version. Included routers do not — use `_api_routes`.
    """
    return {getattr(r, "path", None) for r in app.routes}


def _api_routes(app) -> list:
    """Every endpoint including those added via include_router, version-robustly."""
    candidates = _iter_route_contexts(app.routes) if _iter_route_contexts else app.routes
    return [
        c
        for c in candidates
        if hasattr(c, "dependant") and hasattr(c, "path") and hasattr(c, "methods")
    ]


def _api_paths(app) -> set[str]:
    return {r.path for r in _api_routes(app)}


@pytest.mark.parametrize("path", DOC_PATHS)
def test_documentation_surfaces_are_absent_in_production(production, path):
    app = create_app()
    assert path not in _paths(app), (
        f"{path} is registered in production. Passing None to FastAPI should prevent the "
        "route existing at all, not merely hide it from a nav bar."
    )
    assert TestClient(app).get(path).status_code == 404


@pytest.mark.parametrize("path", DOC_PATHS)
def test_documentation_surfaces_are_present_outside_production(development, path):
    """Local development must be unaffected — this is an AC, not a nice-to-have."""
    assert path in _paths(create_app())


def test_diagnostic_route_is_not_mounted_in_production(production, monkeypatch):
    """The environment check takes precedence over the route's own flag.

    Set ENABLE_TIKTOK_DEBUG=1 deliberately: an operator leaving the flag on must not be
    able to expose this. That precedence is the whole point of the AC.
    """
    monkeypatch.setenv("ENABLE_TIKTOK_DEBUG", "1")
    app = create_app()
    assert DIAGNOSTIC_PATH not in _api_paths(app)
    assert TestClient(app).get(DIAGNOSTIC_PATH).status_code == 404


def test_diagnostic_route_is_mounted_outside_production(development, monkeypatch):
    monkeypatch.setenv("ENABLE_TIKTOK_DEBUG", "1")
    assert DIAGNOSTIC_PATH in _api_paths(create_app())


def test_diagnostic_route_resolves_an_ownership_dependency(development, monkeypatch):
    """It must depend on get_active_shop, not merely 404 for anonymous callers.

    Checked structurally rather than by response code: a route that happens to return
    403 today could start leaking tomorrow if the dependency were dropped, and this is
    the invariant #911's route-auth test used to allowlist away.
    """
    monkeypatch.setenv("ENABLE_TIKTOK_DEBUG", "1")
    from juli_backend.api.dependencies import get_active_shop

    app = create_app()
    route = next(r for r in _api_routes(app) if r.path == DIAGNOSTIC_PATH)
    calls = {d.call for d in route.dependant.dependencies}
    assert get_active_shop in calls, (
        "diagnostic route no longer depends on get_active_shop — it was a cross-tenant "
        "IDOR before that dependency was added (#903)."
    )


def test_diagnostic_route_accepts_no_client_supplied_shop_identifier(development, monkeypatch):
    """The parameters that made it a cross-tenant probe must stay gone."""
    monkeypatch.setenv("ENABLE_TIKTOK_DEBUG", "1")
    app = create_app()
    route = next(r for r in _api_routes(app) if r.path == DIAGNOSTIC_PATH)
    query_names = {p.name for p in route.dependant.query_params}
    for banned in ("shop_id", "merchant_authorization_id", "capability"):
        assert banned not in query_names, (
            f"{banned!r} is back as a query parameter; the caller must not be able to "
            "name a shop other than the one they own."
        )


def test_the_route_walk_is_not_vacuous(development):
    """A walk that finds nothing would make every assertion above pass silently.

    This is the failure mode that actually bit: on newer FastAPI a flat read of
    app.routes returned only the docs routes, so "the diagnostic route is absent"
    was trivially true for the wrong reason.
    """
    routes = _api_routes(create_app())
    assert len(routes) >= 20, (
        f"route walk found only {len(routes)} endpoints — it is not resolving "
        "include_router targets, so the assertions in this file prove nothing"
    )
