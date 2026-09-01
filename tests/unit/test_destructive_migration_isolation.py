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


def _fixtures_defined(source: str) -> set[str]:
    """Names in this module that are pytest fixtures.

    A fixture is the unit that carries destructiveness across an import: asking
    for `postgres_at_head` by name is what runs the downgrade in *your* module,
    whereas importing a plain helper runs nothing until you call it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            target = deco.func if isinstance(deco, ast.Call) else deco
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
            if name == "fixture":
                found.add(node.name)
                break
    return found


def _sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in TESTS_DIR.rglob("test_*.py")
        if path.name != _SELF
    }


def _modules_that_downgrade_to_base(sources: dict[str, str] | None = None) -> set[str]:
    sources = _sources() if sources is None else sources
    return {name for name, source in sources.items() if _downgrades_to_base(source)}


def _modules_that_inherit_destructiveness(
    sources: dict[str, str], direct: set[str]
) -> dict[str, set[str]]:
    """Modules that acquire a destructive fixture by importing it (#1402).

    THE BLIND SPOT THIS CLOSES.

    `test_schema_parity.py` downgrades the shared database to base twice, and
    the word `downgrade` appears nowhere in it: it writes
    `from tests.integration.test_migrations import postgres_at_head`, and the
    fixture does the dropping on its behalf. The AST scan above reads one module
    at a time, so it could not see that — the module was invisible to the guard
    for as long as the guard existed, which is why it survived every earlier
    round of this fix.

    Only *fixture* imports count. `test_migration_host_guard.py` imports
    `_validate_destructive_db_url` from the same destructive module; that is a
    pure predicate and running it drops nothing. Flagging it would hand a
    private database to a module that does not need one, and a guard that cries
    wolf gets its list padded until it means nothing.
    """
    fixtures_by_module = {name: _fixtures_defined(sources[name]) for name in direct}
    inherited: dict[str, set[str]] = {}

    for name, source in sources.items():
        if name in direct:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            origin = node.module.rsplit(".", 1)[-1] + ".py"
            destructive_fixtures = fixtures_by_module.get(origin)
            if not destructive_fixtures:
                continue
            if destructive_fixtures.intersection(alias.name for alias in node.names):
                inherited.setdefault(name, set()).add(origin)
    return inherited


def test_every_module_that_downgrades_to_base_is_isolated():
    """The list must cover reality, not the reality of the day it was written."""
    declared = _isolated_modules()
    sources = _sources()
    direct = _modules_that_downgrade_to_base(sources)
    inherited = _modules_that_inherit_destructiveness(sources, direct)
    actual = direct | set(inherited)

    unlisted = sorted(actual - declared)
    # Name the route for anything that got here through an import — otherwise the
    # failure reads as a false positive, because the named module contains no
    # `downgrade` call to look at.
    via_import = {name: sorted(inherited[name]) for name in unlisted if name in inherited}
    assert not unlisted, (
        "These modules downgrade to base but are not in "
        "tests/conftest.py::_ISOLATED_DATABASE_MODULES, so they run against the "
        "shared database and will drop its schema out from under whatever pytest "
        f"runs next (#1405): {unlisted}"
        + (f" — reached through an imported fixture from: {via_import}" if via_import else "")
    )


def test_the_scan_follows_destructive_fixtures_across_imports():
    """Guard the guard, second edge (#1402).

    Pins both halves of the import rule, because each was got wrong once:
    `test_schema_parity.py` must be found (it was invisible for thirteen W7
    slices), and `test_migration_host_guard.py` must NOT be (a first version of
    this rule flagged every import from a destructive module and caught it).
    """
    sources = _sources()
    direct = _modules_that_downgrade_to_base(sources)
    inherited = _modules_that_inherit_destructiveness(sources, direct)

    assert "test_schema_parity.py" in inherited, (
        "the scan no longer follows `postgres_at_head` across the import from "
        "test_migrations.py — the exact blind spot that hid this module"
    )
    assert "test_migration_host_guard.py" not in inherited, (
        "importing a plain helper from a destructive module is not itself "
        "destructive; flagging it pads the isolation list with modules that "
        "drop nothing"
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
# The disposability requirement (audited 2026-08-28, re-axed 2026-09-01).
#
# `requires_postgres` gates on reachability, not on ownership, and production is
# extremely reachable. `core/config/runtime.py` calls load_dotenv at import
# time, so on a checkout with a `.env` the production URL arrives by itself — no
# misconfiguration required. Twelve modules then downgrade Alembic to base.
#
# The first version of this guard asked "is the host local?". That is the wrong
# axis in both directions: it rejects an ephemeral cloud database while
# accepting a local restore of a production dump. The database must instead SAY
# it is disposable, which cannot happen by accident.
# ---------------------------------------------------------------------------
def _guard():
    spec = importlib.util.spec_from_file_location("_juli_root_conftest_guard", CONFTEST)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unmarked(monkeypatch):
    monkeypatch.delenv("JULI_TEST_DATABASE_DISPOSABLE", raising=False)
    monkeypatch.delenv("CI", raising=False)


def test_an_unmarked_database_url_is_cleared(monkeypatch):
    """Locality is not the test — the marker is.

    This URL is `localhost`, which the previous guard waved through. A local
    restore of a production dump is exactly as destroyable as production.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres@localhost:5432/juli_prod_restore")
    _unmarked(monkeypatch)
    with pytest.warns(UserWarning, match="JULI_TEST_DATABASE_DISPOSABLE"):
        _guard()._require_disposable_test_database()
    assert os.environ["DATABASE_URL"] == "", (
        "an unmarked DATABASE_URL must not survive into the test session — "
        "twelve modules downgrade to base against whatever it names"
    )


def test_a_marked_database_url_survives_wherever_it_lives(monkeypatch):
    """The half the locality guard got wrong in the other direction.

    A per-run cloud instance is the substrate the owner asked for. It is remote,
    it is disposable, and it must be usable — otherwise the guard quietly forces
    every test database to be local, which is the constraint being removed.
    """
    remote = "postgresql://u:p@ephemeral-run-4821.neon.tech:5432/scratch"
    monkeypatch.setenv("DATABASE_URL", remote)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("JULI_TEST_DATABASE_DISPOSABLE", "1")
    _guard()._require_disposable_test_database()
    assert os.environ["DATABASE_URL"] == remote


def test_the_key_is_claimed_even_when_unset(monkeypatch):
    """The subtle half: load_dotenv runs AFTER conftest.

    `load_dotenv(override=False)` skips names already present in os.environ, and
    `.env` is only read when a test module first imports `juli_backend` — after
    this file has been imported. Popping the variable would leave the door open
    for that later injection. Claiming the key with an empty string is what
    actually closes it, so pin that it is claimed rather than merely absent.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _unmarked(monkeypatch)
    _guard()._require_disposable_test_database()
    assert "DATABASE_URL" in os.environ, (
        "the key must be claimed, not left absent, or load_dotenv re-injects "
        "the production URL during collection"
    )
    assert os.environ["DATABASE_URL"] == ""


def test_ci_raises_rather_than_skipping_silently(monkeypatch):
    """Clearing the URL in CI would be attested evidence, not executed evidence.

    Twenty-nine Postgres-backed modules skip when DATABASE_URL is empty, and the
    job still reports success. That is the failure shape this repository has
    been bitten by repeatedly (ADR-079), so the unrecoverable case must be loud.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:5432/prod")
    # conftest.py calls the guard at module level, so loading it is itself a
    # run. Mark the environment for the load, then unmark for the call under
    # test — otherwise the import raises and `pytest.raises` never sees it.
    monkeypatch.setenv("JULI_TEST_DATABASE_DISPOSABLE", "1")
    module = _guard()
    monkeypatch.delenv("JULI_TEST_DATABASE_DISPOSABLE")
    monkeypatch.setenv("CI", "true")

    with pytest.raises(module.NonDisposableTestDatabaseError):
        module._require_disposable_test_database()


def test_ci_is_configured_to_declare_its_database_disposable():
    """The guard above is only safe if CI actually sets the marker (#1402).

    Without this, the fail-closed branch turns every CI job with a Postgres
    service into a hard error — the guard would be correct and the pipeline
    would be dead. Pin that every job supplying a DATABASE_URL also supplies the
    marker, so the two can never drift apart silently.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")
    urls = workflow.count("DATABASE_URL: postgresql://")
    markers = workflow.count("JULI_TEST_DATABASE_DISPOSABLE:")
    assert urls and markers >= urls, (
        f"pr.yml sets DATABASE_URL in {urls} place(s) but declares the database "
        f"disposable in {markers} — every job with a Postgres service must set "
        'JULI_TEST_DATABASE_DISPOSABLE: "1" or it will fail closed'
    )
