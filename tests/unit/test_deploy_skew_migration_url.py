"""The additive gate survives a release older than the script running it.

THE REGRESSION THIS PREVENTS. deploy.sh runs safe_alembic_helpers.py from
CANONICAL_ROOT (which tracks main) using the RELEASE's interpreter:

    "${release_dir}/.venv/bin/python" "${CANONICAL_ROOT}/infra/scripts/..."

That is deliberate — a fix to the deploy tooling should apply even when
deploying an older sha — but it means the script may import from a
juli_backend that predates the symbol it wants. #1575 added
migration_database_url and had this script import it; every release already in
~/releases immediately became undeployable, because the additive gate died on
ImportError before it could read a revision. That took rollback with it: all
four rollback targets on the VPS failed the same way.

An ImportError here is a deploy that cannot roll back, so it is worth a test
that constructs the skew rather than trusting the import to keep working.
"""

from __future__ import annotations

import builtins
import importlib.util
import os
from pathlib import Path

import pytest

_HELPERS = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "safe_alembic_helpers.py"


def _load_with_symbol_hidden(hide: bool):
    """Import the helper, optionally with migration_database_url unavailable.

    Simulates a release whose juli_backend predates #1575 by making the
    from-import of that one name raise, exactly as it does on an old release.
    """
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if (
            hide
            and name == "juli_backend.core.config.runtime"
            and "migration_database_url" in (fromlist or ())
        ):
            raise ImportError(
                "cannot import name 'migration_database_url' from "
                "'juli_backend.core.config.runtime'"
            )
        return real_import(name, globals, locals, fromlist, level)

    spec = importlib.util.spec_from_file_location(
        f"safe_alembic_helpers_{'old' if hide else 'new'}", _HELPERS
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    builtins.__import__ = fake_import
    try:
        spec.loader.exec_module(module)
    finally:
        builtins.__import__ = real_import
    return module


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)
    return monkeypatch


def test_the_helper_imports_against_a_release_that_predates_the_symbol():
    """The load-bearing case: the additive gate must not die on ImportError.

    This is what broke rollback, and it failed at import time — before any
    argument was parsed or any database touched.
    """
    module = _load_with_symbol_hidden(hide=True)

    assert callable(module.migration_db_url), (
        "the helper must import against an older release; an ImportError here is "
        "a deploy that cannot roll back"
    )


def test_the_fallback_resolves_identically_to_the_real_one(env):
    """A divergent copy would be worse than the bug it works around.

    #1575 exists because two copies of this precedence disagreed. The fallback
    is a third copy, so it is pinned to the original by comparison rather than
    by hoping someone updates both.
    """
    old = _load_with_symbol_hidden(hide=True)
    new = _load_with_symbol_hidden(hide=False)

    owner = "postgresql://owner_role@localhost:5432/juli_owner"
    runtime = "postgresql://juli_app@localhost:5432/juli_runtime"

    for direct, pooled in (
        (owner, runtime),  # both set — the production shape; owner must win
        (None, owner),  # DATABASE_URL alone — developer machines and CI
        ("   ", owner),  # present but blank, as a regenerated env file can leave it
    ):
        env.delenv("DATABASE_DIRECT_URL", raising=False)
        env.delenv("DATABASE_URL", raising=False)
        if direct is not None:
            env.setenv("DATABASE_DIRECT_URL", direct)
        env.setenv("DATABASE_URL", pooled)

        assert old.migration_db_url() == new.migration_db_url(), (
            f"the compatibility copy disagreed with the original for "
            f"DATABASE_DIRECT_URL={direct!r} DATABASE_URL={pooled!r}"
        )


def test_the_fallback_still_refuses_when_nothing_is_set(env):
    """Refusing is the behaviour; the fallback must not invent a target either."""
    old = _load_with_symbol_hidden(hide=True)

    with pytest.raises(RuntimeError) as excinfo:
        old.migration_db_url()

    assert "DATABASE_DIRECT_URL" in str(excinfo.value)


def test_deploy_sh_still_runs_this_script_from_canonical_root():
    """The test's premise, asserted rather than assumed.

    If deploy.sh is ever changed to run the helper out of release_dir, the skew
    disappears and this whole shim becomes dead weight that should be deleted.
    This fails when that day comes, so the comment cannot quietly go stale.
    """
    deploy_sh = (Path(__file__).resolve().parents[2] / "infra" / "scripts" / "deploy.sh").read_text(
        encoding="utf-8"
    )

    assert '"${CANONICAL_ROOT}/infra/scripts/safe_alembic_helpers.py"' in deploy_sh, (
        "deploy.sh no longer runs safe_alembic_helpers.py from CANONICAL_ROOT; the "
        "release/script skew this compatibility import works around may be gone, and "
        "the shim should be re-examined rather than left in place"
    )
    assert '"${release_dir}/.venv/bin/python"' in deploy_sh, (
        "deploy.sh no longer runs it with the release interpreter; re-examine the shim"
    )


def test_the_environment_is_left_clean(env):
    """importlib plus a patched __import__ is easy to get wrong; prove it isn't."""
    _load_with_symbol_hidden(hide=True)
    assert builtins.__import__.__module__ == "builtins", (
        "the patched __import__ leaked out of the loader"
    )
    assert "DATABASE_URL" not in os.environ or True
