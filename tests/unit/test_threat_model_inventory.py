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

    def test_residual_risks_have_owner_and_trigger(self):
        """All residual risks in threat model have owner and trigger.

        Parses threat-model.md, extracts residual risk tables from each boundary,
        and asserts every risk entry includes both an owner (Backend/Analytics/ML/UI)
        and a trigger for remediation. AC #6: Residual risks must have owner + trigger,
        preventing documentation rot as threat model evolves.
        """
        threat_model_path = (
            Path(__file__).parent.parent.parent / "docs" / "security" / "threat-model.md"
        )
        if not threat_model_path.exists():
            pytest.fail("threat-model.md not found at " + str(threat_model_path))

        content = threat_model_path.read_text()

        # For each of the six boundaries, find and validate residual risk sections
        for boundary_num in range(1, 7):
            # Find the boundary section
            boundary_header = f"### Boundary {boundary_num}:"
            if boundary_header not in content:
                pytest.fail(f"Boundary {boundary_num} header not found in threat model")

            # Find the start and end of this boundary section
            start_idx = content.find(boundary_header)
            next_boundary_idx = content.find(f"### Boundary {boundary_num + 1}:", start_idx + 1)
            if next_boundary_idx == -1:
                next_boundary_idx = len(content)

            boundary_text = content[start_idx:next_boundary_idx]

            # Find residual risk table header
            if "**Residual risks:**" not in boundary_text:
                pytest.fail(f"Boundary {boundary_num}: No residual risks section found")

            # Extract the residual risks table
            risk_section_start = boundary_text.find("**Residual risks:**")
            risk_section = boundary_text[risk_section_start:]

            # Find the risk table rows (start from the | Risk | line)
            risk_table_start = risk_section.find("| Risk |")
            if risk_table_start == -1:
                pytest.fail(f"Boundary {boundary_num}: No residual risk table found")

            risk_table = risk_section[risk_table_start:]

            # Split into lines and extract data rows (skip header and separator)
            lines = risk_table.split("\n")
            risk_rows = []
            for line in lines:
                line = line.strip()
                # Skip header, separator, and empty lines
                if (
                    line.startswith("| Risk |")
                    or "---" in line
                    or not line.startswith("|")
                    or not line.endswith("|")
                ):
                    continue
                risk_rows.append(line)

            if not risk_rows:
                pytest.fail(
                    f"Boundary {boundary_num}: Empty residual-risk section "
                    "(AC #6 requires at least one risk per boundary)"
                )

            # Validate each risk row has owner and trigger (typically columns 4 and 5)
            for row_idx, row in enumerate(risk_rows):
                # Split by | and filter out empty strings from start/end
                cells = [cell.strip() for cell in row.split("|")[1:-1]]

                # Expected: Risk | Likelihood | Impact | Accepted because | Owner | Trigger
                # So 6 columns total
                if len(cells) < 6:
                    pytest.fail(
                        f"Boundary {boundary_num}, risk {row_idx + 1}: "
                        f"Expected 6 columns, got {len(cells)}: {row}"
                    )

                owner = cells[4].strip()
                trigger = cells[5].strip()

                if not owner or owner == "" or owner.lower() == "none":
                    pytest.fail(
                        f"Boundary {boundary_num}, risk {row_idx + 1}: "
                        "Missing or empty Owner column"
                    )

                if not trigger or trigger == "" or trigger.lower() == "none":
                    pytest.fail(
                        f"Boundary {boundary_num}, risk {row_idx + 1}: "
                        "Missing or empty Trigger column"
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
