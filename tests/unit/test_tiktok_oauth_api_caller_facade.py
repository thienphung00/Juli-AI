"""OAuth/API caller slice must import TikTok symbols from package facade (MMU-5 packet 2)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend/src"

# Bounded OAuth/API caller group for MMU-5 packet 2.
OAUTH_API_CALLER_FILES = (
    "juli_backend/api/routes/auth_tiktok.py",
    "juli_backend/api/routes/auth_tiktok_business_advertiser.py",
    "juli_backend/api/routes/auth_tiktok_business_account_holder.py",
    "juli_backend/services/tiktok/oauth.py",
    "juli_backend/services/tiktok/business_advertiser_oauth.py",
    "juli_backend/services/tiktok/verify_connection.py",
    "juli_backend/services/execution/errors.py",
)

# Leaf modules that must not be imported directly by this caller slice.
FORBIDDEN_TIKTOK_LEAF_MODULES = frozenset(
    {
        "juli_backend.integrations.tiktok.auth",
        "juli_backend.integrations.tiktok.business_advertiser_auth",
        "juli_backend.integrations.tiktok.business_account_holder_auth",
        "juli_backend.integrations.tiktok.client",
        "juli_backend.integrations.tiktok.exceptions",
        "juli_backend.integrations.tiktok.schemas",
        "juli_backend.integrations.tiktok.resources.authorization",
    }
)

FACADE_MODULE = "juli_backend.integrations.tiktok"

# Representative facade symbols each caller is expected to consume via the root.
EXPECTED_FACADE_SYMBOLS_BY_CALLER = {
    "juli_backend/api/routes/auth_tiktok.py": frozenset({"TikTokAuth", "AuthenticationError"}),
    "juli_backend/api/routes/auth_tiktok_business_advertiser.py": frozenset(
        {"TikTokBusinessAdvertiserAuth", "AuthenticationError"}
    ),
    "juli_backend/api/routes/auth_tiktok_business_account_holder.py": frozenset(
        {"TikTokBusinessAccountHolderAuth", "AuthenticationError"}
    ),
    "juli_backend/services/tiktok/oauth.py": frozenset({"TikTokAuth", "AuthenticationError"}),
    "juli_backend/services/tiktok/business_advertiser_oauth.py": frozenset(
        {"TikTokBusinessAdvertiserAuth", "AuthenticationError"}
    ),
    "juli_backend/services/tiktok/verify_connection.py": frozenset(
        {
            "DEFAULT_OPEN_API_BASE_URL",
            "TikTokClient",
            "TikTokAPIError",
            "AuthorizationResource",
            "TikTokSchemaError",
        }
    ),
    "juli_backend/services/execution/errors.py": frozenset(
        {
            "RateLimitError",
            "TikTokAPIError",
            "TikTokSystemError",
            "TransportGuardError",
        }
    ),
}


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


@pytest.mark.parametrize("relative_path", OAUTH_API_CALLER_FILES)
def test_oauth_api_caller_does_not_deep_import_tiktok_leaf_modules(
    relative_path: str,
) -> None:
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imports = _collect_imports(source)

    deep_leaf_hits = [
        (module, names) for module, names in imports if module in FORBIDDEN_TIKTOK_LEAF_MODULES
    ]
    assert deep_leaf_hits == [], (
        f"{relative_path} still deep-imports TikTok leaf modules: {deep_leaf_hits}"
    )


@pytest.mark.parametrize("relative_path", OAUTH_API_CALLER_FILES)
def test_oauth_api_caller_imports_tiktok_symbols_from_package_facade(
    relative_path: str,
) -> None:
    source = (BACKEND_SRC / relative_path).read_text(encoding="utf-8")
    imports = _collect_imports(source)

    facade_imports = {
        name for module, names in imports if module == FACADE_MODULE for name in names
    }
    expected = EXPECTED_FACADE_SYMBOLS_BY_CALLER[relative_path]

    missing = expected - facade_imports
    assert not missing, (
        f"{relative_path} must import {sorted(missing)} from {FACADE_MODULE}, "
        f"got facade symbols {sorted(facade_imports)}"
    )
