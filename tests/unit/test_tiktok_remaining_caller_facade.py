"""Remaining TikTok callers must use package facade, not leaf modules (MMU-5 packet 3)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend/src"

FACADE_MODULE = "juli_backend.integrations.tiktok"

# External callers still on leaf imports after OAuth/API packet 2.
REMAINING_CALLER_FILES = (
    "juli_backend/api/routes/debug_tiktok.py",
    "juli_backend/core/security/credential_resolver.py",
    "juli_backend/core/security/tiktok_oauth.py",
    "juli_backend/repositories/repos.py",
    "juli_backend/services/action_cards/refresh.py",
    "juli_backend/services/analytics_backfill/live_partition.py",
    "juli_backend/services/analytics_backfill/product_partition.py",
    "juli_backend/services/analytics_backfill/revenue_partition.py",
    "juli_backend/services/etl/transform.py",
    "juli_backend/services/execution/inventory_leakage.py",
    "juli_backend/services/execution/listing.py",
    "juli_backend/services/execution/promotion_leakage.py",
    "juli_backend/services/execution/sandbox_guard.py",
    "juli_backend/services/tiktok/app_review_store.py",
    "juli_backend/services/webhook/material_worker.py",
    "juli_backend/workers/services/polling/orchestrate.py",
    "juli_backend/workers/services/polling/sync.py",
)


def _collect_imports(source: str) -> list[tuple[str, frozenset[str]]]:
    tree = ast.parse(source)
    imports: list[tuple[str, frozenset[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, frozenset()))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = frozenset(alias.name for alias in node.names)
            imports.append((module, names))
    return imports


def _is_forbidden_tiktok_leaf(module: str) -> bool:
    if not module.startswith(f"{FACADE_MODULE}."):
        return False
    return module != FACADE_MODULE


@pytest.mark.parametrize("relative_path", REMAINING_CALLER_FILES)
def test_remaining_caller_does_not_deep_import_tiktok_leaf_modules(
    relative_path: str,
) -> None:
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imports = _collect_imports(source)

    deep_leaf_hits = [
        (module, names) for module, names in imports if _is_forbidden_tiktok_leaf(module)
    ]
    assert deep_leaf_hits == [], (
        f"{relative_path} still deep-imports TikTok leaf modules: {deep_leaf_hits}"
    )


@pytest.mark.parametrize("relative_path", REMAINING_CALLER_FILES)
def test_remaining_caller_imports_tiktok_from_package_facade_when_needed(
    relative_path: str,
) -> None:
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imports = _collect_imports(source)

    tiktok_modules = [module for module, _ in imports if module.startswith(FACADE_MODULE)]
    if not tiktok_modules:
        pytest.skip(f"{relative_path} has no TikTok imports")

    assert all(module == FACADE_MODULE for module in tiktok_modules), (
        f"{relative_path} must import TikTok symbols only from {FACADE_MODULE}, "
        f"got modules {tiktok_modules}"
    )
