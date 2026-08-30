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
import os
from pathlib import Path

import pytest

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


def _conftest():
    spec = importlib.util.spec_from_file_location("_juli_root_conftest", CONFTEST)
    assert spec and spec.loader, f"could not load {CONFTEST}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _isolated_modules() -> frozenset[str]:
    return _conftest()._ISOLATED_DATABASE_MODULES


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
        "tests/conftest.py::_ISOLATED_DATABASE_MODULES, so they run against the "
        "shared database and will drop its schema out from under whatever pytest "
        f"runs next (#1405): {unlisted}"
    )


def test_every_isolated_module_still_exists():
    """A rename must not silently retire isolation for a module.

    Replaces an earlier "no dead entries" check that compared the list against
    the downgrade-to-base scan. That comparison stopped being right once
    isolation gained a second reason (#1425): a module isolated because it
    asserts on global counts legitimately never downgrades, and the old test
    would have called it a dead entry. Existence is the invariant that still
    holds for every isolated module regardless of why it is isolated.
    """
    present = {p.name for p in TESTS_DIR.rglob("test_*.py")}
    missing = sorted(_isolated_modules() - present)
    assert not missing, (
        "These modules are declared in _ISOLATED_DATABASE_MODULES but no longer "
        f"exist — a rename would silently drop their isolation: {missing}"
    )


def test_the_destructive_subset_is_a_subset():
    """`_DESTRUCTIVE_MIGRATION_MODULES` is derived, and must stay a subset.

    If it ever diverges, the guard above would be checking one list while the
    fixture reads another — the two would disagree silently, which is the exact
    failure mode this file exists to prevent.
    """
    c = _conftest()
    assert c._DESTRUCTIVE_MIGRATION_MODULES <= c._ISOLATED_DATABASE_MODULES


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


# ---------------------------------------------------------------------------
# The non-local DATABASE_URL refusal (audited 2026-08-28).
#
# `requires_postgres` gates on reachability, not locality, and production is
# reachable. `core/config/runtime.py` calls load_dotenv at import time, so on a
# checkout with a `.env` the production URL arrives by itself — no
# misconfiguration required. Eleven modules then downgrade Alembic to base.
# ---------------------------------------------------------------------------
def _refusal():
    spec = importlib.util.spec_from_file_location("_juli_root_conftest_guard", CONFTEST)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._refuse_non_local_test_database


def test_a_non_local_database_url_is_refused(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:5432/prod")
    monkeypatch.delenv("JULI_ALLOW_REMOTE_TEST_DATABASE", raising=False)
    with pytest.warns(UserWarning, match="non-local host"):
        _refusal()()
    assert os.environ["DATABASE_URL"] == "", (
        "a non-local DATABASE_URL must not survive into the test session — "
        "eleven modules downgrade to base against whatever it names"
    )


def test_a_local_database_url_is_left_alone(monkeypatch):
    local = "postgresql://postgres@localhost:5432/juli_test"
    monkeypatch.setenv("DATABASE_URL", local)
    monkeypatch.delenv("JULI_ALLOW_REMOTE_TEST_DATABASE", raising=False)
    _refusal()()
    assert os.environ["DATABASE_URL"] == local


def test_the_key_is_claimed_even_when_unset(monkeypatch):
    """The subtle half: load_dotenv runs AFTER conftest.

    `load_dotenv(override=False)` skips names already present in os.environ, and
    `.env` is only read when a test module first imports `juli_backend` — after
    this file has been imported. Popping the variable would leave the door open
    for that later injection. Claiming the key with an empty string is what
    actually closes it, so pin that it is claimed rather than merely absent.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JULI_ALLOW_REMOTE_TEST_DATABASE", raising=False)
    _refusal()()
    assert "DATABASE_URL" in os.environ, (
        "the key must be claimed, not left absent, or load_dotenv re-injects "
        "the production URL during collection"
    )
    assert os.environ["DATABASE_URL"] == ""


def test_the_opt_in_still_works(monkeypatch):
    remote = "postgresql://u:p@throwaway.example.com:5432/scratch"
    monkeypatch.setenv("DATABASE_URL", remote)
    monkeypatch.setenv("JULI_ALLOW_REMOTE_TEST_DATABASE", "1")
    _refusal()()
    assert os.environ["DATABASE_URL"] == remote
