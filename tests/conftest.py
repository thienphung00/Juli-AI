import os
import uuid
import warnings

import pytest

# #1217 / ADR-075 decision 3: `workers/celery_app.py` now runs
# `assert_agent_runtime_config()` at *module import* time, whose check 5
# (SUPABASE_JWT_SECRET) is unconditional -- independent of
# AGENT_WORKFLOWS_ENABLED, which stays unset (and therefore skips every
# other check) for the whole unit-test suite by default. `celery_app` is
# imported transitively by many test modules that have nothing to do with
# auth (any test importing `workers.tasks`, which imports
# `workers.tasks.agent_workflow`, which imports `celery_app`) -- pytest
# imports every test module during collection, before any per-test
# `monkeypatch` fixture ever runs, so those modules need this set at import
# time, not test time. `setdefault` only fills the gap: any test that
# `monkeypatch.delenv("SUPABASE_JWT_SECRET", ...)` to exercise the
# missing-secret path (e.g. `test_api_main.py`,
# `test_get_current_user.py`) still removes it for that test's duration and
# `monkeypatch` restores it afterward, unaffected by this default.
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-collection-default")

# #1282 / AGT-W5B: check 5 is extended to also require SUPABASE_URL be a
# structurally usable Supabase API URL (JWKS derives from it) -- see
# `workers/agent_runtime_boot.py`'s check 5 docstring for what this proves
# and does not. Same import-time-default rationale as SUPABASE_JWT_SECRET
# above: `celery_app` imports transitively, before any per-test monkeypatch
# runs. A test exercising the "SUPABASE_URL missing/unusable" failure path
# still `monkeypatch.delenv`/`setenv`s it for that test's duration.
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


# --------------------------------------------------------------------------
# SAFETY: the test suite must never point at a database it does not own.
#
# `requires_postgres` in seventeen modules skips on *unreachable*, not on
# *non-local*. Production is extremely reachable. And nothing has to be
# misconfigured for it to be selected: `core/config/runtime.py` calls
# `load_dotenv(repo_root/".env", override=False)` at import time, so on a
# developer machine with a `.env`, importing anything under `juli_backend`
# injects the production DATABASE_URL into the environment. Verified on this
# checkout with DATABASE_URL unset:
#
#     host: aws-1-us-west-2.pooler.supabase.com   is local: False
#
# Eleven of those modules then run `downgrade(cfg, "base")`, which drops every
# table in whatever they are pointed at. That is the 2026-07-30 production wipe
# again, and the only thing that has prevented it is that individual modules
# each remembered to add their own `_assert_local_database_url` — sixteen
# separate copies, any one of which can be omitted by the next module.
#
# So refuse centrally, at import time, before pytest collects anything: a
# non-local DATABASE_URL is removed from the environment for the test session.
# Every `_postgres_reachable()` then returns False and its module skips exactly
# as it does on a machine with no Postgres — the already-supported path, not a
# new one. Tests that need a specific URL set it themselves with monkeypatch
# and are unaffected.
#
# `JULI_ALLOW_REMOTE_TEST_DATABASE=1` opts back in for a deliberate run against
# a remote *throwaway* database. It is not a production escape hatch: the
# per-module isolation fixture below still refuses to create or drop databases
# on a non-local host.
# --------------------------------------------------------------------------
def _refuse_non_local_test_database() -> None:
    if os.environ.get("JULI_ALLOW_REMOTE_TEST_DATABASE", "").strip() == "1":
        return

    url = os.environ.get("DATABASE_URL", "").strip()

    # Claim the key even when it is currently unset. `load_dotenv(override=False)`
    # skips any name already present in os.environ, and it runs LATER than this
    # file: conftest is imported before collection, but `.env` is only read when
    # a test module first imports something under `juli_backend`. Popping the
    # variable would therefore leave the door open — the next module import
    # re-injects the production URL and every `_postgres_reachable()` after that
    # point says yes. An empty string counts as present, so this closes it.
    if not url:
        os.environ["DATABASE_URL"] = ""
        return

    if not url.startswith("postgresql"):
        return

    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "localhost").lower()
    if host in _LOCAL_HOSTS:
        return

    os.environ["DATABASE_URL"] = ""
    warnings.warn(
        f"DATABASE_URL pointed at the non-local host {host!r}; it has been removed "
        "for this test session. Postgres-backed tests will skip. Eleven test "
        "modules downgrade Alembic to base, which drops every table in the target "
        "database. Set a local DATABASE_URL to run them, or "
        "JULI_ALLOW_REMOTE_TEST_DATABASE=1 for a remote throwaway database.",
        stacklevel=1,
    )


_refuse_non_local_test_database()


# --------------------------------------------------------------------------
# #1405: `downgrade(cfg, "base")` needs exclusive ownership of a database.
#
# Eleven modules run a full Alembic downgrade to base against whatever
# DATABASE_URL points at. That drops every table in the database, so each one
# wipes the schema out from under whatever pytest runs next. It only becomes
# visible when the ordering happens to line up, which is why it reproduced in
# `full-regression` and nowhere else: run alone, `test_workflow_runs_schema.py`
# is 14/14 and the three CI-failing modules together are 31/31.
#
# The symptom in CI was migration 034's downgrade hitting foreign keys from W7
# tables that were still present while alembic_version had been left BELOW the
# migrations that created them:
#
#     cannot drop table workflow_runs because other objects depend on it
#     DETAIL: production_write_authorizations_consumed_by_run_id_fkey
#             production_write_audit_run_id_fkey
#
# Four separate attempts to name the specific predecessor test each produced a
# different answer, because the corruption is emergent from the whole ordering
# rather than caused by any one pair — running the two prime suspects together
# passes 17/17 and leaves the database clean. Whichever test were named would
# stop being the culprit the next time the order shifted, so this fixes the
# class instead: give every module that downgrades to base its own database,
# and the ordering stops mattering.
#
# Keyed off an explicit list rather than the `migration_heavy` marker on
# purpose. That marker is a CI *selection* filter — `pr.yml` deselects it in
# two jobs — so marking the two currently-unmarked modules to reach them here
# would silently drop them from those jobs. Isolation and selection are
# different concerns and must not share a switch.
#
# TWO reasons a module needs its own database (#1425):
#
#   1. It MUTATES shared schema state — `downgrade(cfg, "base")` drops every
#      table, or `Base.metadata.create_all` creates them outside Alembic. Either
#      leaves the database in a shape the next module did not expect.
#   2. It ASSERTS ON global state — an unscoped `SELECT COUNT(*)` is only
#      correct if nothing else has written to the table.
#
# The second reason surfaced when #1405 fixed the first. `test_rls_policies`
# asserts `COUNT(*) FROM products == 2` to show the owner bypassing RLS; that
# held only because a destructive module happened to have emptied the table
# first. Give the destructive modules their own databases and the accidental
# cleanup disappears, so the count sees every row the run has accumulated.
#
# Scoping those queries would also work, but it changes what a security test
# asserts to work around an infrastructure problem. An owner-bypass test is
# *about* seeing everything RLS would otherwise hide; narrowing its queries
# weakens the contrast it exists to demonstrate.
# --------------------------------------------------------------------------
_DESTRUCTIVE_MIGRATION_MODULES = frozenset(
    {
        # Downgrades to base, dropping every table (#1405).
        "test_stop_reason_diverged_schema.py",
        "test_stop_reason_prompt_version_unrecoverable_schema.py",
        "test_run_confirmations_approvals_schema.py",
        "test_workflow_runs_schema.py",
        "test_workflow_run_events_schema.py",
        "test_workflow_run_action_card_fk_schema.py",
        "test_juli_app_role_downgrade_cross_database.py",
        "test_migrations.py",
        "test_restore_drill.py",
        "test_safe_alembic_upgrade.py",
        "test_safe_alembic_upgrade_local.py",
    }
)

# Isolated for the other two reasons. Kept separate so the subset relationship
# below holds by construction rather than by subtracting names — subtraction
# silently stops being correct the moment a name is added to one set and not
# the other.
_SHARED_STATE_MODULES = frozenset(
    {
        # Reason 2: asserts on unscoped global counts (#1425).
        "test_rls_policies.py",
        # Reason 1: `Base.metadata.create_all` against the shared database, which
        # leaves tables that a module running `alembic upgrade head` afterwards
        # collides with ("relation \"users\" already exists"). Surfaced when
        # #1429 made that create_all succeed — before then it failed on a missing
        # schema and never got far enough to leave anything behind.
        "test_tenant_context_seam.py",
    }
)

_ISOLATED_DATABASE_MODULES = _DESTRUCTIVE_MIGRATION_MODULES | _SHARED_STATE_MODULES


@pytest.fixture(scope="module", autouse=True)
def _isolated_migration_database(request):
    """Point a destructive-migration module at a database of its own.

    A no-op for every other module, and for a non-Postgres DATABASE_URL, so the
    overwhelming majority of the suite is untouched.

    The swap is done on `os.environ` rather than by handing modules a fixture
    because each of them resolves the URL through its own `_database_url()`
    helper at call time, reading the environment. Converting eleven modules to
    take a fixture would be a far larger and riskier diff for the same effect.
    """
    module_name = os.path.basename(str(getattr(request, "path", request.node.fspath)))
    base_url = os.environ.get("DATABASE_URL", "").strip()

    if module_name not in _ISOLATED_DATABASE_MODULES or not base_url.startswith("postgresql"):
        yield
        return

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from juli_backend.core.config.runtime import sync_database_url

    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")

    # Refuse to create/drop databases anywhere but a local throwaway cluster —
    # the same discipline #734 established for the downgrades themselves.
    if (admin_url.host or "localhost").lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing to provision an isolated migration database against the "
            f"non-local host {admin_url.host!r}."
        )

    # Postgres identifiers cap at 63 bytes; the stem keeps failures legible in
    # `\l` output when a run is interrupted before teardown.
    stem = module_name.removeprefix("test_").removesuffix(".py")[:28]
    db_name = f"juli_iso_{stem}_{uuid.uuid4().hex[:8]}"

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    isolated = make_url(sync_database_url(base_url)).set(database=db_name)
    # `str(URL)` masks the password as `***`; render_as_string(hide_password=False)
    # is required or every connection authenticates with a literal `***`. Same
    # defect as #1121 and #1131 (see test_agent_runner_concurrency.py).
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = isolated.render_as_string(hide_password=False)
    try:
        yield
    finally:
        os.environ["DATABASE_URL"] = previous
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            # Terminate stragglers first: a leaked connection makes DROP DATABASE
            # fail, and a leaked database is what creates the cross-database
            # juli_app grant that #1406 had to tolerate.
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


@pytest.fixture
def app_key():
    return "test_app_key_12345"


@pytest.fixture
def app_secret():
    return "test_app_secret_67890"


@pytest.fixture
def access_token():
    return "ROW_test_access_token"


@pytest.fixture
def refresh_token():
    return "ROW_test_refresh_token"


@pytest.fixture
def shop_id():
    return "shop_001"


@pytest.fixture
def tiktok_config(app_key, app_secret):
    return {
        "app_key": app_key,
        "app_secret": app_secret,
        "base_url": "https://open-api.tiktokglobalshop.com",
    }
