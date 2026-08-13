"""Repository-wide agent-tools client boundary sweep — issue #984 (W1-A).

ADR-068 decision 6(b) names three new boundary tests added alongside (not
replacing) the existing no-model contract tests; this is boundary test (b):
agent tool handlers never import the marketplace client directly — all
marketplace access goes through the guarded factories, so the read-only
production guard (`ProductionReadResources`) and the sandbox-write guard
(`SandboxWriteResources`) cannot be bypassed by a new code path.

**What this test adds over the existing per-module checks.**
`test_agent_tools_product_read.py::TestNoDirectClientConstruction
::test_product_module_never_imports_tiktok_client_construction_symbols` and
`test_agent_tools_product_write.py::TestNoDirectClientConstruction
::test_module_never_imports_tiktok_client_construction_symbols` each already
parse one hard-coded module file (`product.py`, `product_write.py`) and are
left as-is — this file does not duplicate or replace them. The gap #984
fills is the *repository-wide sweep*: every module under
`backend/src/juli_backend/services/agent/tools/`, discovered by walking the
directory rather than a hard-coded list, so a new handler module added
tomorrow (`product_reviews.py`, `orders.py`, whatever comes next) is covered
automatically without anyone remembering to add it to a per-module test.
A sweep that silently discovers zero files would pass vacuously — worse
than no test at all — so `TestDiscoveryIsNotVacuous` below asserts discovery
actually found the modules it should have.

**Convention.** This follows the AST-check convention in
`tests/unit/test_demo_execution_import_boundary.py`: a *static* import-graph
assertion, not a mock-call count — an import that is never written cannot be
reached at runtime under any branch, no matter how the module is exercised.

**Guarded-factory usage stays permitted.** Handlers legitimately obtain
resources through the guarded factories (`ProductionReadClientFactory`,
`SandboxWriteClientFactory` in `juli_backend.integrations.tiktok.factories`)
and depend on those factories' *output* shapes, `ProductionReadResources`
and `SandboxWriteResources` — confirmed by reading `product.py` and
`product_write.py`, which import exactly those two guarded-output types and
nothing else marketplace-adjacent (see each module's own docstring). The
forbidden set below is therefore the client-*construction* surface only —
the same four symbols the two existing per-module tests already forbid.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_TOOLS_DIR = REPO_ROOT / "backend/src/juli_backend/services/agent/tools"

# Mirrors the forbidden set already enforced per-module by
# test_agent_tools_product_read.py / test_agent_tools_product_write.py:
# symbols that construct or hold a marketplace transport directly. Guarded
# factory *output* types (ProductionReadResources, SandboxWriteResources)
# are deliberately absent from this set — handlers are expected to depend
# on those.
FORBIDDEN_CLIENT_CONSTRUCTION_SYMBOLS: frozenset[str] = frozenset(
    {
        "TikTokClient",
        "GuardedTikTokClient",
        "ProductionReadClientFactory",
        "SandboxWriteClientFactory",
    }
)

#: Whole-module imports that must never appear in an agent tool module.
#:
#: A symbol-name scan alone is bypassable: ``import
#: juli_backend.integrations.tiktok.factories as f`` followed by
#: ``f.ProductionReadClientFactory()`` constructs a guarded factory without
#: ever naming a forbidden symbol, so a name-based check sees nothing. That
#: is a bypass of the very property ADR-068 decision 6(b) requires, so the
#: whole-module form is forbidden outright.
#:
#: `ast.ImportFrom` against this package stays legal — handlers legitimately
#: do ``from juli_backend.integrations.tiktok import ProductionReadResources``
#: (the resource types the guarded factories hand them). Only binding a
#: *module* object, from which any attribute can be reached, is refused.
FORBIDDEN_WHOLE_MODULE_IMPORT_PREFIX = "juli_backend.integrations.tiktok"


def discover_agent_tool_modules(tools_dir: Path = AGENT_TOOLS_DIR) -> list[Path]:
    """Walk `tools_dir` for every `.py` module.

    Auto-discovery, not a hard-coded list — this is the property #984 adds
    over the existing per-module tests: a new handler module added tomorrow
    is swept automatically.
    """
    return sorted(tools_dir.rglob("*.py"))


def find_forbidden_client_construction_imports(source: str) -> set[str]:
    """Source-level (AST) scan for imported names matching a forbidden
    marketplace-client-construction symbol.

    Mirrors the exact collection strategy of the existing per-module checks:
    `ast.Import` aliases are recorded by their (possibly dotted) `alias.name`
    and `ast.ImportFrom` aliases by their bare imported member name, then
    intersected with `FORBIDDEN_CLIENT_CONSTRUCTION_SYMBOLS`.
    """
    tree = ast.parse(source)
    violations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_CLIENT_CONSTRUCTION_SYMBOLS:
                    violations.add(alias.name)
                # Whole-module import binds a module object, so every symbol
                # inside it is reachable by attribute access without ever
                # being named here. Refuse the module itself.
                if alias.name == FORBIDDEN_WHOLE_MODULE_IMPORT_PREFIX or alias.name.startswith(
                    FORBIDDEN_WHOLE_MODULE_IMPORT_PREFIX + "."
                ):
                    violations.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in FORBIDDEN_CLIENT_CONSTRUCTION_SYMBOLS:
                    violations.add(alias.name)
    return violations


def check_module_has_no_client_construction_import(module_path: Path) -> None:
    """Raise `AssertionError` naming `module_path` if it imports a forbidden
    client-construction symbol directly.

    This is the "fails loudly, naming the offending module" contract from
    the issue's acceptance criteria — `module_path` appears in the message,
    not just the symbol name, so a CI failure points straight at the file
    that needs fixing.
    """
    offending = find_forbidden_client_construction_imports(module_path.read_text(encoding="utf-8"))
    assert not offending, (
        f"{module_path}: agent tool module must not import marketplace client "
        f"construction symbols directly (guarded factories only): {sorted(offending)}"
    )


class TestDiscoveryIsNotVacuous:
    """A sweep that silently discovers zero files passes vacuously and is
    worse than no test — assert discovery actually found the modules it
    should have."""

    def test_discovery_finds_at_least_two_modules(self):
        discovered = discover_agent_tool_modules()
        assert len(discovered) >= 2, (
            f"expected the sweep to discover multiple agent tool modules under "
            f"{AGENT_TOOLS_DIR}, found: {discovered}"
        )

    def test_discovery_finds_the_known_handler_modules(self):
        """Sanity-checks discovery against the two modules the per-module
        tests already cover individually, proving the walk isn't missing
        the directory entirely or landing somewhere unexpected."""
        discovered_names = {path.name for path in discover_agent_tool_modules()}
        assert "product.py" in discovered_names
        assert "product_write.py" in discovered_names

    def test_discovery_is_a_directory_walk_not_a_hard_coded_list(self):
        """Proves the auto-discovery property directly: a module dropped
        into the directory at test time (not named anywhere in this file)
        is picked up by the same walk, unlike the two existing per-module
        tests which each name their one target module by hard-coded path."""
        assert AGENT_TOOLS_DIR.is_dir()
        all_py_files = {p for p in AGENT_TOOLS_DIR.rglob("*.py")}
        assert set(discover_agent_tool_modules()) == all_py_files


class TestRepositoryWideSweep:
    """The gap #984 fills: every module under the agent tools package,
    discovered by walking the directory — not a hard-coded per-module list."""

    def test_no_agent_tool_module_imports_client_construction_symbols(self):
        violations: dict[str, list[str]] = {}
        for module_path in discover_agent_tool_modules():
            offending = find_forbidden_client_construction_imports(
                module_path.read_text(encoding="utf-8")
            )
            if offending:
                violations[str(module_path.relative_to(REPO_ROOT))] = sorted(offending)

        assert not violations, (
            "agent tool module(s) import marketplace client construction symbols "
            f"directly (guarded factories only): {violations}"
        )

    @pytest.mark.parametrize("module_path", discover_agent_tool_modules(), ids=lambda p: p.name)
    def test_each_discovered_module_individually(self, module_path):
        """Same assertion as above, split per-module so a CI failure output
        names exactly which discovered module regressed."""
        check_module_has_no_client_construction_import(module_path)


class TestGuardedFactoryUsageRemainsPermitted:
    """ADR-068 decision 6(b): handlers legitimately obtain resources through
    the guarded factories — the check must not forbid that. The allowed
    surface below (`ProductionReadResources`, `SandboxWriteResources`) is
    read directly off `product.py` / `product_write.py`'s actual imports,
    not guessed."""

    def test_product_module_guarded_resource_import_is_not_flagged(self):
        offending = find_forbidden_client_construction_imports(
            (AGENT_TOOLS_DIR / "product.py").read_text(encoding="utf-8")
        )
        assert offending == set()

    def test_product_write_module_guarded_resource_import_is_not_flagged(self):
        offending = find_forbidden_client_construction_imports(
            (AGENT_TOOLS_DIR / "product_write.py").read_text(encoding="utf-8")
        )
        assert offending == set()

    def test_synthetic_module_importing_only_guarded_resource_types_passes(self, tmp_path):
        permitted_module = tmp_path / "permitted_handler.py"
        permitted_module.write_text(
            "from juli_backend.integrations.tiktok import (\n"
            "    ProductionReadResources,\n"
            "    SandboxWriteResources,\n"
            ")\n",
            encoding="utf-8",
        )

        # Must not raise.
        check_module_has_no_client_construction_import(permitted_module)


class TestCheckerFailsLoudlyOnASyntheticViolation:
    """Prove the checker actually fires rather than merely trusting it: drive
    it with synthetic source containing a violating import and assert the
    failure message names the offending module."""

    def test_synthetic_direct_client_import_is_detected_and_names_the_module(self, tmp_path):
        violating_module = tmp_path / "hypothetical_new_handler.py"
        violating_module.write_text(
            "from juli_backend.integrations.tiktok.client import TikTokClient\n",
            encoding="utf-8",
        )

        with pytest.raises(AssertionError) as exc_info:
            check_module_has_no_client_construction_import(violating_module)

        message = str(exc_info.value)
        assert "hypothetical_new_handler.py" in message
        assert "TikTokClient" in message

    def test_synthetic_guarded_client_import_is_also_detected_and_named(self, tmp_path):
        violating_module = tmp_path / "another_new_handler.py"
        violating_module.write_text(
            "from juli_backend.integrations.tiktok.guarded_client import GuardedTikTokClient\n",
            encoding="utf-8",
        )

        with pytest.raises(AssertionError) as exc_info:
            check_module_has_no_client_construction_import(violating_module)

        message = str(exc_info.value)
        assert "another_new_handler.py" in message
        assert "GuardedTikTokClient" in message

    def test_synthetic_direct_factory_construction_import_is_detected_and_named(self, tmp_path):
        """Bypassing the guarded factory *interface* by importing the
        concrete factory classes directly is exactly the escape hatch this
        boundary exists to close."""
        violating_module = tmp_path / "factory_bypass_handler.py"
        violating_module.write_text(
            "from juli_backend.integrations.tiktok.factories import (\n"
            "    ProductionReadClientFactory,\n"
            "    SandboxWriteClientFactory,\n"
            ")\n",
            encoding="utf-8",
        )

        with pytest.raises(AssertionError) as exc_info:
            check_module_has_no_client_construction_import(violating_module)

        message = str(exc_info.value)
        assert "factory_bypass_handler.py" in message
        assert "ProductionReadClientFactory" in message
        assert "SandboxWriteClientFactory" in message

    def test_whole_module_import_with_attribute_access_is_detected(self, tmp_path):
        """The bypass that a symbol-name scan alone cannot see.

        ``import juli_backend.integrations.tiktok.factories as f`` followed by
        ``f.ProductionReadClientFactory()`` constructs a guarded factory
        without ever naming a forbidden symbol. Confirmed by execution during
        the Wave 1 review pass: before this guard, a module in exactly this
        shape passed the whole boundary suite. ADR-068 decision 6(b) requires
        the boundary not be bypassable by a new code path, so the whole-module
        form is refused outright.
        """
        module = tmp_path / "evasion_by_module_import.py"
        module.write_text(
            "import juli_backend.integrations.tiktok.factories as factories\n"
            "\n"
            "\n"
            "def build():\n"
            "    return factories.ProductionReadClientFactory()\n",
            encoding="utf-8",
        )
        with pytest.raises(AssertionError) as exc_info:
            check_module_has_no_client_construction_import(module)
        assert "evasion_by_module_import.py" in str(exc_info.value)
        assert "juli_backend.integrations.tiktok.factories" in str(exc_info.value)

    def test_bare_package_import_is_also_detected(self, tmp_path):
        """``import juli_backend.integrations.tiktok`` reaches everything too."""
        module = tmp_path / "evasion_by_package_import.py"
        module.write_text(
            "import juli_backend.integrations.tiktok as tiktok\n"
            "\n"
            "\n"
            "def build():\n"
            "    return tiktok.TikTokClient()\n",
            encoding="utf-8",
        )
        with pytest.raises(AssertionError) as exc_info:
            check_module_has_no_client_construction_import(module)
        assert "juli_backend.integrations.tiktok" in str(exc_info.value)

    def test_from_import_of_guarded_resource_types_still_passes(self, tmp_path):
        """The legal form must stay legal — this guard must not over-block.

        Handlers receive already-built resources; refusing this shape would
        break every real handler.
        """
        module = tmp_path / "legitimate_handler.py"
        module.write_text(
            "from juli_backend.integrations.tiktok import (\n"
            "    ProductionReadResources,\n"
            "    SandboxWriteResources,\n"
            ")\n"
            "\n"
            "\n"
            "def handle(resources: ProductionReadResources) -> None:\n"
            "    del resources\n",
            encoding="utf-8",
        )
        check_module_has_no_client_construction_import(module)

    def test_clean_synthetic_module_does_not_raise(self, tmp_path):
        clean_module = tmp_path / "clean_handler.py"
        clean_module.write_text(
            "from juli_backend.integrations.tiktok import ProductionReadResources\n",
            encoding="utf-8",
        )

        # Must not raise.
        check_module_has_no_client_construction_import(clean_module)
