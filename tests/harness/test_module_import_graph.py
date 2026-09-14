"""A TYPE_CHECKING import is not a dependency (#1859 follow-up).

`collect_import_graph` counted every `ast.ImportFrom` it could reach, including
the ones inside `if TYPE_CHECKING:` — which never execute, and whose entire
purpose is to express a type relationship WITHOUT creating a runtime one.
That was invisible while `parse_architecture_map` returned zero modules and the
graph was always empty. The moment the map parser became honest, the miscount
invented a six-module import cycle that included `backend/database`, whose only
outgoing edge was the type-only import its own module docstring explains.

These tests run against the REAL tree for the facts the tree already contains,
and against a synthetic repo for the guard shapes it does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load(name: str):
    """Import a harness script by name, without an E402 suppression."""
    for path in (VALIDATE_DIR, CI_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return __import__(name)


common = _load("common")
check_module_boundaries = _load("check_module_boundaries")

ALPHA = "backend/services/alpha"
BETA = "backend/services/beta"

# The real graph carries well over this many edges. A floor, so the extractor
# cannot regress to "no imports at all" and still pass.
NON_VACUOUS_EDGE_FLOOR = 30


def _row(path: str) -> str:
    return (
        f"| [`backend/src/juli_backend/{path}`](../../x/MODULE.md) | 1 | fixture | `x` | Test |\n"
    )


@pytest.fixture
def two_module_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A miniature repo with two mapped modules; alpha's import of beta varies."""

    def _build(alpha_source: str) -> dict[str, set[str]]:
        map_md = tmp_path / "docs" / "architecture" / "map.md"
        map_md.parent.mkdir(parents=True, exist_ok=True)
        map_md.write_text(
            "| Module | Tier | Purpose | Public interface | Area |\n"
            "|---|---|---|---|---|\n" + _row("services/alpha") + _row("services/beta"),
            encoding="utf-8",
        )
        src = tmp_path / "backend" / "src" / "juli_backend" / "services"
        for name, body in (("alpha", alpha_source), ("beta", "class Thing:\n    pass\n")):
            (src / name).mkdir(parents=True, exist_ok=True)
            (src / name / "impl.py").write_text(body, encoding="utf-8")
        monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(common, "ARCHITECTURE_MAP", map_md)
        return common.collect_import_graph(common.parse_architecture_map())

    return _build


class TestTypeOnlyImportsAreNotEdges:
    def test_a_type_checking_import_contributes_no_edge(self, two_module_repo) -> None:
        graph = two_module_repo(
            "from __future__ import annotations\n"
            "\n"
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from juli_backend.services.beta.impl import Thing\n"
            "\n"
            "\n"
            "def use(thing: 'Thing') -> None:\n"
            "    return None\n"
        )

        assert graph[ALPHA] == set()

    def test_a_qualified_typing_type_checking_import_contributes_no_edge(
        self, two_module_repo
    ) -> None:
        graph = two_module_repo(
            "import typing\n"
            "\n"
            "if typing.TYPE_CHECKING:\n"
            "    from juli_backend.services.beta.impl import Thing\n"
        )

        assert graph[ALPHA] == set()

    def test_a_runtime_import_is_still_an_edge(self, two_module_repo) -> None:
        """The guard on the guard: the fix must not blind the extractor."""
        graph = two_module_repo("from juli_backend.services.beta.impl import Thing\n")

        assert graph[ALPHA] == {BETA}

    def test_a_deferred_import_inside_a_function_is_still_an_edge(self, two_module_repo) -> None:
        """A function-body import runs; only TYPE_CHECKING never does."""
        graph = two_module_repo(
            "def use() -> None:\n    from juli_backend.services.beta.impl import Thing\n"
        )

        assert graph[ALPHA] == {BETA}

    def test_the_else_branch_of_a_type_checking_guard_is_runtime(self, two_module_repo) -> None:
        graph = two_module_repo(
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    Thing = object\n"
            "else:\n"
            "    from juli_backend.services.beta.impl import Thing\n"
        )

        assert graph[ALPHA] == {BETA}

    def test_a_negated_guard_stays_conservative(self, two_module_repo) -> None:
        """`if not TYPE_CHECKING:` runs, so its imports are kept."""
        graph = two_module_repo(
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if not TYPE_CHECKING:\n"
            "    from juli_backend.services.beta.impl import Thing\n"
        )

        assert graph[ALPHA] == {BETA}


class TestTheRealImportGraph:
    def test_the_extractor_is_not_vacuous(self) -> None:
        graph = common.collect_import_graph(common.parse_architecture_map())

        edges = sum(len(targets) for targets in graph.values())
        assert edges >= NON_VACUOUS_EDGE_FLOOR, (
            f"collect_import_graph found {edges} edges across the real tree; "
            "the extractor reads nothing"
        )

    def test_database_contributes_no_type_only_edge(self) -> None:
        """`database/__init__.py:36` guards its `services.etl` import."""
        graph = common.collect_import_graph(common.parse_architecture_map())

        assert "backend/services/etl" not in graph["backend/database"]

    def test_a_real_runtime_edge_survives(self) -> None:
        """`core/security/tiktok_oauth.py:29` is a top-level import."""
        graph = common.collect_import_graph(common.parse_architecture_map())

        assert "backend/integrations/tiktok" in graph["backend/core/security"]


class TestTheCycleAllowlist:
    def test_every_allowlisted_edge_is_explicit_and_cites_its_import_sites(self) -> None:
        for edge, entry in check_module_boundaries.KNOWN_CYCLE_EDGES.items():
            importer, imported = edge
            assert "*" not in importer and "*" not in imported
            assert len(entry.reason) >= 40, f"{edge} has no real reason"
            assert entry.importSites, f"{edge} cites no import site"
            for site in entry.importSites:
                path, _, lineno = site.partition(":")
                assert (REPO_ROOT / path).exists(), f"{edge} cites a missing file: {path}"
                assert lineno.split(" ")[0].isdigit(), f"{edge} cites no line: {site}"

    def test_every_allowlisted_edge_still_exists(self) -> None:
        """Anti-rot: the allowlist cannot outlive the cycle it excuses."""
        graph = common.collect_import_graph(common.parse_architecture_map())

        stale = [
            f"{importer} -> {imported}"
            for importer, imported in check_module_boundaries.KNOWN_CYCLE_EDGES
            if imported not in graph.get(importer, set())
        ]

        assert not stale, f"allowlisted cycle edges no longer exist: {stale}"

    def test_the_gate_still_detects_a_cycle_without_the_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-vacuity: emptying the allowlist must bring the real cycle back."""
        monkeypatch.setattr(check_module_boundaries, "KNOWN_CYCLE_EDGES", {})
        monkeypatch.setattr(check_module_boundaries, "git_changed_files", lambda: [])

        passed, message, details = check_module_boundaries.run_check(1859)

        assert passed is False
        assert "cycle" in message.lower()
        assert details["cycles"]

    def test_the_gate_passes_on_the_real_tree_with_the_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(check_module_boundaries, "git_changed_files", lambda: [])

        passed, _, details = check_module_boundaries.run_check(1859)

        assert details["cycles"] == [], f"unallowlisted cycle: {details['cycles']}"
        assert passed is True
        assert len(details["allowlistedCycleEdges"]) == len(
            check_module_boundaries.KNOWN_CYCLE_EDGES
        )
