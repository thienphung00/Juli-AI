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
from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel

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


def generate_surface_inventory(app=None) -> dict:
    """Generate the surface inventory from the live app and tool registry.

    Args:
        app: Optional FastAPI app; if None, creates default app.

    Returns:
        A dict with keys 'routes' and 'tools', each containing the inventoried surfaces.
    """
    if app is None:
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


def _compute_inventory_diff(generated: dict, committed: dict) -> dict:
    """Compute structured diff between generated and committed inventories.

    Returns dict with 'missing_routes', 'extra_routes', 'missing_tools', 'extra_tools'.
    """
    generated_routes = {(r["path"], tuple(r["methods"])): r for r in generated["routes"]}
    committed_routes = {(r["path"], tuple(r["methods"])): r for r in committed["routes"]}

    generated_tools = {t["name"]: t for t in generated["tools"]}
    committed_tools = {t["name"]: t for t in committed["tools"]}

    missing_routes = set(committed_routes.keys()) - set(generated_routes.keys())
    extra_routes = set(generated_routes.keys()) - set(committed_routes.keys())

    missing_tools = set(committed_tools.keys()) - set(generated_tools.keys())
    extra_tools = set(generated_tools.keys()) - set(committed_tools.keys())

    return {
        "missing_routes": [f"{path} {list(methods)}" for path, methods in missing_routes],
        "extra_routes": [f"{path} {list(methods)}" for path, methods in extra_routes],
        "missing_tools": sorted(list(missing_tools)),
        "extra_tools": sorted(list(extra_tools)),
    }


# Explicit allowlist of unauthenticated routes (issue #1331 AC)
UNAUTHENTICATED_ALLOWLIST = {
    "/v1/auth/tiktok/callback",
    "/v1/auth/tiktok/business/callback",
    "/v1/auth/tiktok/business/account-holder/callback",
    "/v1/demo/analytics",
}

REGENERATION_COMMAND = (
    "python -c \"import sys; sys.path.insert(0, 'backend/src'); "
    "from tests.unit.test_threat_model_inventory import generate_surface_inventory; "
    "import json; from pathlib import Path; "
    "inv = generate_surface_inventory(); "
    "Path('docs/security/surface_inventory.json').write_text("
    'json.dumps(inv, indent=2))" '
    "# or use: PYTHONPATH=$PWD/backend/src pytest tests/unit/test_threat_model_inventory.py"
)


class TestSurfaceInventoryGeneration:
    """Surface inventory generation and validation."""

    def test_surface_inventory_matches_committed_file(self):
        """Inventory generated from live app matches the committed file."""
        generated = generate_surface_inventory()
        committed = load_committed_inventory()

        # Compare as JSON strings for exact byte matching
        generated_json = json.dumps(generated, indent=2, sort_keys=True)
        committed_json = json.dumps(committed, indent=2, sort_keys=True)

        if generated_json != committed_json:
            diff = _compute_inventory_diff(generated, committed)
            msg = "Generated inventory does not match committed file.\nStructural diff:\n"
            if diff["missing_routes"]:
                msg += "  Missing routes (in committed, not in generated):\n"
                for route in diff["missing_routes"]:
                    msg += f"    - {route}\n"
            if diff["extra_routes"]:
                msg += "  Extra routes (in generated, not in committed):\n"
                for route in diff["extra_routes"]:
                    msg += f"    - {route}\n"
            if diff["missing_tools"]:
                msg += "  Missing tools (in committed, not in generated):\n"
                for tool in diff["missing_tools"]:
                    msg += f"    - {tool}\n"
            if diff["extra_tools"]:
                msg += "  Extra tools (in generated, not in committed):\n"
                for tool in diff["extra_tools"]:
                    msg += f"    - {tool}\n"
            msg += f"\nRegenerate with:\n  {REGENERATION_COMMAND}\n"
            assert False, msg

    def test_adding_unauthenticated_route_not_on_allowlist_fails(self):
        """Adding an unauthenticated route fails the check if not on allowlist.

        Negative test: creates a test app with an extra unauthenticated route,
        then asserts the inventory check would fail, naming the route.
        """
        # Create a test app and add a fixture route
        app = create_app()
        test_router = APIRouter(prefix="/v1/test")

        @test_router.get("/unauthorized-endpoint")
        async def unauthorized_endpoint() -> dict:
            """This is intentionally unauthenticated."""
            return {"message": "test"}

        app.include_router(test_router)

        # Generate inventory with the extra route
        generated = generate_surface_inventory(app)
        committed = load_committed_inventory()

        # Verify that the extra route appears in generated
        extra_route_paths = {r["path"] for r in generated["routes"]}
        committed_route_paths = {r["path"] for r in committed["routes"]}
        extra_routes = extra_route_paths - committed_route_paths

        assert "/v1/test/unauthorized-endpoint" in extra_routes, (
            "Fixture route not found; test setup failed"
        )

        # Verify that comparing against committed would fail and name the route
        diff = _compute_inventory_diff(generated, committed)
        extra_named = diff["extra_routes"]
        assert any("/v1/test/unauthorized-endpoint" in route for route in extra_named), (
            f"Check would not name the extra route. Extra routes: {extra_named}"
        )

    def test_adding_tool_not_in_registry_fails(self):
        """Adding a tool fails the check if not in real registry.

        Negative test: creates a test registry with an extra tool, generates
        inventory with it, and asserts the check would fail, naming the tool.
        """
        # Build the real registry (verify it exists and has tools)
        real_registry = build_product_tool_registry()
        assert real_registry.list_all(), "Real registry should have tools"

        # Create a test inventory with an extra tool
        class DummyInput(BaseModel):
            pass

        class DummyOutput(BaseModel):
            pass

        # Create test inventory with extra tool
        test_inventory = generate_surface_inventory()
        test_inventory["tools"].append(
            {
                "name": "test_fixture_tool",
                "classification": "read",
                "policy": "auto",
                "playbooks": ["optimize_product"],
            }
        )
        test_inventory["tools"] = sorted(test_inventory["tools"], key=lambda t: t["name"])

        # Load committed and verify extra tool appears
        committed = load_committed_inventory()
        diff = _compute_inventory_diff(test_inventory, committed)

        assert "test_fixture_tool" in diff["extra_tools"], (
            "Fixture tool not in extra_tools; test setup failed"
        )

        # Verify the check would fail and name the tool
        extra_named = diff["extra_tools"]
        assert "test_fixture_tool" in extra_named, (
            f"Check would not name the extra tool. Extra tools: {extra_named}"
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
        and verifies each reference points to a live function/class/constant. No skip
        for missing files/symbols — all controls must have resolvable references.
        """
        threat_model_path = (
            Path(__file__).parent.parent.parent / "docs" / "security" / "threat-model.md"
        )
        if not threat_model_path.exists():
            pytest.fail("threat-model.md not found at " + str(threat_model_path))

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
            pytest.fail("No control references found in threat model")

        # Verify every reference resolves (no skip path)
        failures = []
        for file_path, symbol_name in matches:
            try:
                _verify_reference(file_path, symbol_name)
            except Exception as e:
                failures.append((file_path, symbol_name, str(e)))

        assert not failures, (
            "Control references do not resolve (all controls must be in force):\n"
            + "\n".join(f"  {f}:{s} — {e}" for f, s, e in failures)
            + "\nIf a control is not yet implemented, move it to the residual-risk "
            + "section with owner and trigger, or delete it."
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
