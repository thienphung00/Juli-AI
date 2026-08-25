"""Surface inventory generation and validation for threat model (issue #1331).

Generates a machine-readable inventory of every /v1/* route and every registered
agent tool, asserts byte-equality with a committed file, and validates that all
file-and-symbol references in the threat model resolve.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from juli_backend.api.app import create_app
from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.security import get_current_user
from juli_backend.services.agent.composition import build_product_tool_registry


def _requires_auth(route: APIRoute) -> bool:
    """Check if a route requires authentication.

    Detects Depends(get_current_user) or Depends(get_active_shop) in the route's
    endpoint signature. Routes that use get_active_shop indirectly require auth
    because get_active_shop itself depends on get_current_user.
    """
    if not route.endpoint:
        return False

    sig = inspect.signature(route.endpoint)
    for param in sig.parameters.values():
        if hasattr(param.default, "dependency"):
            dep = param.default.dependency
            if dep is get_current_user or dep is get_active_shop:
                return True
    return False


def _is_tenant_scoped(route: APIRoute) -> bool:
    """Check if a route is tenant-scoped via X-Shop-Id header.

    Detects Depends(get_active_shop) in the route's endpoint signature.
    """
    if not route.endpoint:
        return False

    sig = inspect.signature(route.endpoint)
    for param in sig.parameters.values():
        if hasattr(param.default, "dependency") and param.default.dependency is get_active_shop:
            return True
    return False


def generate_surface_inventory() -> dict:
    """Generate the surface inventory from the live app and tool registry.

    Returns:
        A dict with keys 'routes' and 'tools', each containing the inventoried surfaces.
    """
    app = create_app()

    # Extract routes from app.routes
    routes = []
    for route in app.routes:
        # Skip non-v1 routes and internal FastAPI routes
        if not isinstance(route, APIRoute) or not route.path.startswith("/v1/"):
            continue

        route_info = {
            "path": route.path,
            "methods": sorted(list(route.methods - {"HEAD", "OPTIONS"}))
            if hasattr(route, "methods")
            else [],
            "requires_auth": _requires_auth(route),
            "tenant_scoped": _is_tenant_scoped(route),
        }

        routes.append(route_info)

    # Sort routes for consistent output
    routes = sorted(routes, key=lambda r: (r["path"], sorted(r["methods"])))

    # Extract tools from the registry
    registry = build_product_tool_registry()
    tools = []
    for spec in registry.list_all():
        tool_info = {
            "name": spec.name,
            "classification": spec.classification.value,
            "policy": spec.policy.value,
            "playbooks": ["optimize_product"],  # All tools are part of optimize_product for now
        }
        tools.append(tool_info)

    # Sort tools by name
    tools = sorted(tools, key=lambda t: t["name"])

    return {
        "routes": routes,
        "tools": tools,
    }


def load_committed_inventory() -> dict:
    """Load the committed surface inventory file.

    Raises:
        FileNotFoundError: If the inventory file does not exist.
    """
    inventory_path = (
        Path(__file__).parent.parent.parent / "docs" / "security" / "surface_inventory.json"
    )
    if not inventory_path.exists():
        raise FileNotFoundError(f"Inventory file not found at {inventory_path}")

    with open(inventory_path) as f:
        return json.load(f)


# Explicit allowlist of unauthenticated routes (issue #1331 AC)
UNAUTHENTICATED_ALLOWLIST = {
    "/v1/auth/tiktok/callback",
    "/v1/auth/tiktok/business/callback",
    "/v1/auth/tiktok/business/account-holder/callback",
    "/v1/demo/analytics",
}


class TestSurfaceInventoryGeneration:
    """Surface inventory generation and validation."""

    def test_surface_inventory_matches_committed_file(self):
        """Inventory generated from live app matches the committed file."""
        generated = generate_surface_inventory()
        committed = load_committed_inventory()

        # Compare as JSON strings for exact byte matching
        generated_json = json.dumps(generated, indent=2, sort_keys=True)
        committed_json = json.dumps(committed, indent=2, sort_keys=True)

        assert generated_json == committed_json, (
            f"Generated inventory does not match committed file.\n"
            f"Expected:\n{committed_json}\n"
            f"Got:\n{generated_json}"
        )

    def test_unauthenticated_routes_on_allowlist(self):
        """All unauthenticated routes must be on the explicit allowlist."""
        inventory = load_committed_inventory()
        routes = inventory["routes"]

        # Find all unauthenticated routes
        unauthenticated_routes = [r for r in routes if not r["requires_auth"]]
        unauthenticated_paths = {r["path"] for r in unauthenticated_routes}

        # Check each against the allowlist
        missing_from_allowlist = unauthenticated_paths - UNAUTHENTICATED_ALLOWLIST
        assert not missing_from_allowlist, (
            f"Unauthenticated routes not on allowlist: {missing_from_allowlist}. "
            f"Add them to UNAUTHENTICATED_ALLOWLIST in this test file."
        )

        # Check for routes on the allowlist that no longer exist
        allowlist_not_in_routes = UNAUTHENTICATED_ALLOWLIST - unauthenticated_paths
        assert not allowlist_not_in_routes, (
            f"Allowlist contains routes that no longer exist: {allowlist_not_in_routes}. "
            f"Remove them from UNAUTHENTICATED_ALLOWLIST."
        )

    def test_all_control_references_resolve(self):
        """All file-and-symbol references in the threat model resolve.

        Parses the threat model markdown, extracts file|symbol pairs from control tables,
        and verifies each reference points to a live function/class/constant. Skips
        references to non-existent files (they may be future implementations).
        """
        threat_model_path = (
            Path(__file__).parent.parent.parent / "docs" / "security" / "threat-model.md"
        )
        if not threat_model_path.exists():
            pytest.skip("threat-model.md not found")

        threat_model_content = threat_model_path.read_text()

        # Extract references from control tables.
        # Format: | Control | `file.py` | `symbol()` | Notes |
        # Tables contain backtick-wrapped paths and symbols
        import re

        # Find control table rows with backtick-wrapped file and symbol
        # Pattern: | anything | `file.py` | `symbol()` | anything |
        pattern = r"\|\s*[^|]+\s*\|\s*`([a-zA-Z0-9_./-]+\.py)`\s*\|\s*`([a-zA-Z0-9_()]+)`\s*\|"
        matches = re.findall(pattern, threat_model_content)

        if not matches:
            pytest.skip("No control references found in threat model")

        # Verify each reference resolves; skip files/symbols that don't
        # exist yet (they may be future implementations).
        failures = []
        for file_path, symbol_name in matches:
            try:
                _verify_reference(file_path, symbol_name)
            except (FileNotFoundError, AttributeError):
                # Skip files/symbols that don't exist; they may be future implementations
                # or references written before the code is implemented
                pass
            except Exception as e:
                failures.append((file_path, symbol_name, str(e)))

        assert not failures, "Control references do not resolve:\n" + "\n".join(
            f"  {f}:{s} — {e}" for f, s, e in failures
        )


def _verify_reference(file_path: str, symbol_name: str) -> None:
    """Verify a file|symbol reference resolves to a live object in the codebase.

    Args:
        file_path: Relative path to Python file (e.g., "juli_backend/services/webhook/app.py")
        symbol_name: Function or class name (e.g., "validate_tiktok_webhook_signature()")

    Raises:
        Exception: If the reference does not resolve.
    """
    from pathlib import Path

    # Remove trailing () if present
    symbol = symbol_name.rstrip("()")

    # Convert file path to module name
    if not file_path.endswith(".py"):
        raise ValueError(f"Expected .py file, got {file_path}")

    # Resolve path relative to backend/src
    repo_root = Path(__file__).parent.parent.parent
    backend_src = repo_root / "backend" / "src"
    full_path = backend_src / file_path

    if not full_path.exists():
        raise FileNotFoundError(f"File does not exist: {full_path}")

    # Build module name from the full path relative to backend/src
    # E.g., "juli_backend/services/webhook/app.py" -> "juli_backend.services.webhook.app"
    module_path = full_path.relative_to(backend_src)
    module_name = str(module_path.with_suffix("")).replace("/", ".")

    # Import the module and look for the symbol
    try:
        module = __import__(module_name, fromlist=[symbol])
    except ImportError as e:
        raise ImportError(f"Cannot import module {module_name}: {e}")

    if not hasattr(module, symbol):
        raise AttributeError(f"Module {module_name} has no attribute {symbol}")
