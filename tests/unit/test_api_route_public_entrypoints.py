"""MMU-8: critical API routes must call owning service public entrypoints only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend/src"

THIN_ADAPTER_ROUTES: dict[str, dict[str, frozenset[str]]] = {
    "juli_backend/api/routes/webhook_tiktok.py": {
        "required_modules": frozenset({"juli_backend.services.webhook"}),
        "forbidden_modules": frozenset(
            {
                "juli_backend.services.etl.consumer",
                "juli_backend.services.ingestion.handoff",
                "juli_backend.services.tiktok.webhook_handlers",
                "juli_backend.services.tiktok.webhook_raw_log",
                "juli_backend.services.webhook.app",
            }
        ),
    },
    "juli_backend/api/routes/auth_tiktok.py": {
        "required_modules": frozenset({"juli_backend.services.tiktok.oauth"}),
        "forbidden_modules": frozenset(
            {
                "juli_backend.integrations.tiktok",
                "juli_backend.services.tiktok.app_review_store",
            }
        ),
    },
}


def _collect_import_modules(source: str) -> frozenset[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return frozenset(modules)


@pytest.mark.parametrize("relative_path", THIN_ADAPTER_ROUTES.keys())
def test_thin_adapter_route_avoids_internal_wiring_imports(relative_path: str) -> None:
    spec = THIN_ADAPTER_ROUTES[relative_path]
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imported = _collect_import_modules(source)

    forbidden_hits = sorted(spec["forbidden_modules"] & imported)
    assert forbidden_hits == [], (
        f"{relative_path} must not import internal wiring modules: {forbidden_hits}"
    )


@pytest.mark.parametrize("relative_path", THIN_ADAPTER_ROUTES.keys())
def test_thin_adapter_route_imports_owning_service_public_api(relative_path: str) -> None:
    spec = THIN_ADAPTER_ROUTES[relative_path]
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imported = _collect_import_modules(source)

    missing = sorted(spec["required_modules"] - imported)
    assert not missing, f"{relative_path} must import owning service public API from {missing}"


@pytest.mark.parametrize("relative_path", THIN_ADAPTER_ROUTES.keys())
def test_auth_tiktok_routes_use_oauth_facade_not_integrations_tiktok(relative_path: str) -> None:
    """Auth callback routes must use OAuth facade; forbidden leaf imports blocked."""
    if relative_path != "juli_backend/api/routes/auth_tiktok.py":
        pytest.skip("auth facade rule applies to Shop OAuth route only")
    spec = THIN_ADAPTER_ROUTES[relative_path]
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imported = _collect_import_modules(source)
    forbidden_hits = sorted(spec["forbidden_modules"] & imported)
    assert forbidden_hits == [], (
        f"{relative_path} must not import internal wiring modules: {forbidden_hits}"
    )


@pytest.mark.parametrize("relative_path", THIN_ADAPTER_ROUTES.keys())
def test_webhook_route_avoids_etl_consumer_internals(relative_path: str) -> None:
    """Webhook route must not import services.etl.consumer internals."""
    if relative_path != "juli_backend/api/routes/webhook_tiktok.py":
        pytest.skip("ETL consumer rule applies to webhook route only")
    spec = THIN_ADAPTER_ROUTES[relative_path]
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imported = _collect_import_modules(source)
    forbidden_hits = sorted(spec["forbidden_modules"] & imported)
    assert forbidden_hits == [], (
        f"{relative_path} must not import internal wiring modules: {forbidden_hits}"
    )


def test_path_disjoint_from_demo_frontend_work() -> None:
    """AC5: path-disjoint from Demo 2.10 / frontend work."""
    routing = (ROOT / "agent-runtime/config/slice-routing.yml").read_text(encoding="utf-8")
    mmu8 = routing.split("MMU-8:")[1].split("\nMMU-")[0]
    for forbidden in ("apps/demo/", "apps/landing/", "apps/dashboard/", "web/", "ios/"):
        assert forbidden in mmu8
