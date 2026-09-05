"""Every RLS policy reads its tenant GUC through the helper (#1467).

`SET LOCAL` restores a custom GUC to its default at commit, and that default is the empty
string — not unset. A policy that casts the raw `current_setting(...)` to `uuid` therefore
raises on the next query after any committed transaction:

    juli_app=> begin; set local app.current_user_id='...'; commit;
    juli_app=> select count(*) from shops;
    ERROR:  invalid input syntax for type uuid: ""

Migration 050 routes every policy through `app_current_shop_id()` / `app_current_user_id()`,
which apply `nullif(..., '')` before the cast so an absent context yields NULL and the policy
excludes every row — a clean denial rather than an error.

WHY THIS ASSERTS HELPER USE RATHER THAN `nullif` PLACEMENT.

Both express the same fix. Checking that `nullif` sits in the right position inside 166
hand-written expressions is a far weaker test than checking that an expression calls the one
function where the semantics live: the first can pass on an expression that applies `nullif` to
the wrong operand, the second cannot. It is also the shape that survives new policies — a
migration that adds one either calls the helper or fails here.

RELATIONSHIP TO `test_rls_policy_current_setting_form.py` (#1455).

That module rejects the one-argument `current_setting`, which raises when the GUC was NEVER set.
This module rejects any raw `current_setting` in a policy at all. After 050 the former holds
trivially, because no policy calls `current_setting` directly any more. It is kept rather than
deleted: it states a narrower invariant that must remain true if a future migration ever writes
a raw call, and it fails for a different reason than this one does.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

HELPERS = ("app_current_shop_id", "app_current_user_id")
_TENANT_GUCS = ("app.current_shop_id", "app.current_user_id")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


requires_postgres = pytest.mark.skipif(
    not _database_url().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)


@pytest.fixture(scope="module")
def guc_engine() -> Iterator[Engine]:
    """A catalog-read engine on the shared database.

    Deliberately not `postgres_at_head` from `test_migrations.py`: importing it
    would make this module destructive-by-inheritance, which
    `test_destructive_migration_isolation.py` detects. The shared database is
    already guaranteed at head by the session fixture in `tests/conftest.py`.
    """
    from juli_backend.core.config.runtime import sync_database_url

    engine = create_engine(sync_database_url(_database_url()))
    try:
        yield engine
    finally:
        engine.dispose()


def _policy_expressions(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as conn:
        return [
            (
                f"{row.schemaname}.{row.tablename}.{row.policyname}",
                f"{row.qual or ''} {row.with_check or ''}",
            )
            for row in conn.execute(
                text("SELECT schemaname, tablename, policyname, qual, with_check FROM pg_policies")
            )
        ]


@requires_postgres
@pytest.mark.migration_heavy
def test_the_helpers_exist_and_tolerate_an_absent_context(guc_engine) -> None:
    """The helpers must return NULL for both shapes of "no context".

    An absent GUC gives NULL and an unset-after-commit GUC gives `''`; the
    helper has to flatten both to NULL, because the policies now depend on it
    doing so. Asserted against the database rather than the migration source.
    """
    with guc_engine.connect() as conn:
        for helper in HELPERS:
            exists = conn.execute(
                text("SELECT 1 FROM pg_proc WHERE proname = :name"), {"name": helper}
            ).scalar()
            assert exists, f"{helper}() is missing; migration 050 did not run"

        for helper, guc in zip(HELPERS, _TENANT_GUCS, strict=True):
            never_set = conn.execute(text(f"SELECT {helper}()")).scalar()  # noqa: S608
            assert never_set is None, f"{helper}() must be NULL when {guc} was never set"

            after_release = conn.execute(
                text(f"SELECT set_config(:guc, '', false), {helper}()"),  # noqa: S608
                {"guc": guc},
            ).all()
            assert after_release[0][1] is None, (
                f"{helper}() must be NULL when {guc} is the empty string — that is the "
                "state SET LOCAL leaves behind at commit, and the whole point of the helper"
            )


@requires_postgres
@pytest.mark.migration_heavy
def test_no_policy_reads_a_tenant_guc_without_the_helper(guc_engine) -> None:
    """The invariant. One raw call is enough to poison its table."""
    offenders = [
        name
        for name, expression in _policy_expressions(guc_engine)
        if any(guc in expression for guc in _TENANT_GUCS)
        and not any(helper in expression for helper in HELPERS)
    ]

    assert not offenders, (
        "These policies read a tenant GUC without going through the helper, so they cast the "
        "raw setting to uuid and raise on the empty string SET LOCAL leaves at commit: "
        f"{offenders}. Use app_current_shop_id() / app_current_user_id() (#1467)."
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_the_scan_is_not_vacuous(guc_engine) -> None:
    """Guard the guard.

    The invariant above is satisfied by an empty corpus, and an empty corpus is
    what a broken fixture or an unmigrated database produces. Pin that the
    policies are really there and really call the helpers.
    """
    expressions = _policy_expressions(guc_engine)
    assert len(expressions) >= 50, (
        f"only {len(expressions)} policies found — the database is not at head, so the "
        "invariant above would hold vacuously"
    )

    using_helper = [
        name for name, expression in expressions if any(helper in expression for helper in HELPERS)
    ]
    assert len(using_helper) >= 50, (
        f"only {len(using_helper)} policies call a helper; migration 050 rewrites every "
        "policy that reads a tenant GUC, so a small number here means the rewrite was "
        "partial rather than that the invariant holds"
    )
