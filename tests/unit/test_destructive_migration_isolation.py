"""The isolation list cannot go stale (#1405).

`downgrade(cfg, "base")` drops every table in the database it runs against, so
a module that does it needs a database of its own. `tests/conftest.py` gives
one to every module named in `_DESTRUCTIVE_MIGRATION_MODULES`.

A list is only as good as its maintenance. Add a twelfth module that downgrades
to base, forget to list it, and the exact #1405 failure comes straight back —
silently, and only in whatever job happens to order it before a schema test.
That is precisely how this survived thirteen W7 slices: it reproduced in
`full-regression` and nowhere else.

So this test derives the truth from the source rather than trusting the list:
every test module that downgrades to base MUST be isolated. It is the guard the
#1405 acceptance criteria asked for — "whatever ordering or isolation guarantee
was missing is asserted by a test that fails if it regresses."

It deliberately does NOT require Postgres. The invariant is about which modules
are declared, not about what they do at runtime, so it holds in every job —
including the ones that deselect `migration_heavy`.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
CONFTEST = TESTS_DIR / "conftest.py"

# This module documents the pattern it detects, so it would match itself.
_SELF = Path(__file__).name


def _downgrades_to_base(source: str) -> bool:
    """True when the module actually CALLS downgrade(..., "base").

    Parsed rather than grepped. A regex over the text matches the same words in
    a docstring: the first version of this test reported
    `test_agent_runner_ledger.py` and `test_agent_events_streaming_matrix.py` as
    destructive purely because their comments describe the pattern. A false
    positive here is not harmless — it would push a module onto the isolation
    list, handing it a private database and quietly changing what it tests.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != "downgrade":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and arg.value == "base":
                return True
    return False


def _isolated_modules() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location("_juli_root_conftest", CONFTEST)
    assert spec and spec.loader, f"could not load {CONFTEST}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._DESTRUCTIVE_MIGRATION_MODULES


def _modules_that_downgrade_to_base() -> set[str]:
    found: set[str] = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        if path.name == _SELF:
            continue
        if _downgrades_to_base(path.read_text(encoding="utf-8")):
            found.add(path.name)
    return found


def test_every_module_that_downgrades_to_base_is_isolated():
    """The list must cover reality, not the reality of the day it was written."""
    declared = _isolated_modules()
    actual = _modules_that_downgrade_to_base()

    unlisted = sorted(actual - declared)
    assert not unlisted, (
        "These modules downgrade to base but are not in "
        "tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES, so they run against the "
        "shared database and will drop its schema out from under whatever pytest "
        f"runs next (#1405): {unlisted}"
    )


def test_the_isolation_list_has_no_dead_entries():
    """A stale entry is a smaller problem than a missing one, but it still lies
    about what the suite does — and it makes the list harder to trust."""
    declared = _isolated_modules()
    actual = _modules_that_downgrade_to_base()

    stale = sorted(declared - actual)
    assert not stale, (
        "These modules are declared destructive but no longer downgrade to base; "
        f"drop them from _DESTRUCTIVE_MIGRATION_MODULES: {stale}"
    )


def test_the_detector_actually_detects():
    """Guard the guard.

    If the regex silently stopped matching, both tests above would pass on an
    empty set and this whole file would become decorative. Pin that the scan
    finds the modules we already know do this.
    """
    actual = _modules_that_downgrade_to_base()
    assert len(actual) >= 10, (
        f"expected the scan to find the known destructive modules, got {sorted(actual)}"
    )
    for known in (
        "test_workflow_runs_schema.py",
        "test_migrations.py",
    ):
        assert known in actual, f"{known} downgrades to base but the scan missed it"
