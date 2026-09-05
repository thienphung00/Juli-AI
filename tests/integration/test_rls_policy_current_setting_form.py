"""No RLS policy may use the raising form of `current_setting` (#1455).

`current_setting('app.current_user_id')` RAISES when the parameter is unset.
`current_setting('app.current_user_id', true)` returns NULL. Both are legal SQL and they look
almost identical in a migration diff, which is how two policies survived migration 045's
rewrite and reached production:

    juli_app@prod=> select count(*) from shops;
    ERROR:  unrecognized configuration parameter "app.current_user_id"

WHY THE RAISING FORM IS WRONG HERE, AND NOT MERELY DIFFERENT.

An RLS policy exists to decide which rows a caller may see. Under the two-argument form, a
missing tenant context yields NULL, the qualifier is false for every row, and the caller sees
nothing — a clean denial. Under the one-argument form the query aborts with a message naming a
Postgres configuration parameter, which tells the caller nothing about tenancy and cannot be
handled as "no rows". Policies for the same command are OR'd, but Postgres still evaluates the
raising qualifier, so one such policy poisons every query on the table regardless of how many
correct policies sit beside it.

WHY THIS IS A TEST AND NOT A REVIEW NOTE.

Three grant/policy omissions on the W7 wave share one shape — a hand-maintained list that did
not match its own stated intent:

  1. Migration 045 enabled RLS but missed two tenant-scoped tables (#1329, fixed in 046).
  2. Migration 044 created a table and granted the runtime role nothing (#1453, fixed in 048).
  3. Migration 045 documented three legacy policies to drop and dropped one (#1455, fixed here).

Each was found by a person reading the database, after merge and after deploy. This asserts the
class rather than the three instances.

WHY IT READS pg_policies RATHER THAN THE MIGRATION SOURCE.

The migrations are not the authority on what the database contains — that is the whole lesson
of the three omissions above. A source scan would have passed on all three, because in each
case the source said the right thing and the database disagreed.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# `current_setting('...')` with exactly one argument. The two-argument form has
# a comma before the closing paren, so requiring no comma is what separates them.
# `::text` appears because Postgres renders the literal's cast in pg_policies.
_RAISING_FORM = re.compile(r"current_setting\(\s*'[^']+'(?:::text)?\s*\)")


def _legacy_policies() -> tuple[tuple[str, str, str], ...]:
    """Read the triples straight from migration 049.

    Restating them here would be a second list to keep in step, which is the
    failure mode this whole file exists to catch.
    """
    import importlib.util
    from pathlib import Path as _Path

    path = (
        _Path(__file__).resolve().parents[2]
        / "backend/src/juli_backend/database/migrations/versions"
        / "049_drop_legacy_isolation_policies.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_049", path)
    assert spec and spec.loader, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LEGACY_POLICIES


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


requires_postgres = pytest.mark.skipif(
    not _database_url().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)


@pytest.fixture(scope="module")
def policy_engine() -> Iterator[Engine]:
    """A catalog-read engine on the shared database.

    Deliberately not `postgres_at_head` from `test_migrations.py`: importing it
    would make this module destructive-by-inheritance, which
    `test_destructive_migration_isolation.py` now detects. The shared database is
    already guaranteed at head by the session fixture in `tests/conftest.py`.
    """
    from juli_backend.core.config.runtime import sync_database_url

    engine = create_engine(sync_database_url(_database_url()))
    try:
        yield engine
    finally:
        engine.dispose()


def _policies(engine: Engine) -> list[tuple[str, str, str, str]]:
    with engine.connect() as conn:
        return [
            (
                row.schemaname,
                row.tablename,
                row.policyname,
                f"{row.qual or ''} {row.with_check or ''}",
            )
            for row in conn.execute(
                text("SELECT schemaname, tablename, policyname, qual, with_check FROM pg_policies")
            )
        ]


@requires_postgres
@pytest.mark.migration_heavy
def test_no_policy_uses_the_raising_current_setting_form(policy_engine) -> None:
    """The invariant. A single offender poisons every query on its table."""
    offenders = [
        f"{schema}.{table}.{policy}"
        for schema, table, policy, expression in _policies(policy_engine)
        if _RAISING_FORM.search(expression)
    ]

    assert not offenders, (
        "These RLS policies call current_setting without the missing_ok argument, so any query "
        "on their table RAISES when the tenant context is unset instead of returning no rows — "
        f"and one such policy poisons the table however many correct policies sit beside it: "
        f"{offenders}. Use current_setting('app.current_user_id', true) (#1455)."
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_the_detector_tells_the_two_forms_apart(policy_engine) -> None:
    """Guard the guard.

    If the pattern silently stopped matching, the test above would pass on an
    empty offender list and this file would become decorative — the exact way the
    lists it exists to replace failed. Pin both directions against the real
    rendering Postgres produces in `pg_policies`, and prove the corpus it scans
    is not empty.
    """
    raising = "(user_id = (current_setting('app.current_user_id'::text))::uuid)"
    safe = "(user_id = (current_setting('app.current_user_id'::text, true))::uuid)"

    assert _RAISING_FORM.search(raising), "the detector no longer recognises the raising form"
    assert not _RAISING_FORM.search(safe), "the detector now flags the safe two-argument form"

    assert len(_policies(policy_engine)) >= 50, (
        "the policy scan came back nearly empty, so the invariant above would hold vacuously — "
        "the database is not at head, or pg_policies is not readable from this connection"
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_dropping_the_legacy_policies_left_full_command_coverage(policy_engine) -> None:
    """The tables 049 touches still cover all four commands afterwards.

    ADR-086 names the hazard: a table left RLS-enabled with no policy for some
    command denies it outright, and a denial is indistinguishable from an empty
    table. Migration 049 checks this before dropping; this checks the result.

    SCOPED TO THE TABLES 049 TOUCHES, deliberately. A first version asserted full
    coverage for every RLS-enabled table and failed on `production_write_audit`,
    which migration 047 made append-only on purpose — "no UPDATE or DELETE
    grants. SELECT/INSERT only for juli_app". Its missing policies are intended
    denial. Asserting four commands everywhere would have made incomplete
    coverage look like a defect wherever it was actually the design, and the
    pressure would then be to add policies that widen access.
    """
    tables = {(schema, table) for schema, table, _policy, _column in _legacy_policies()}

    uncovered = []
    for schema, table in sorted(tables):
        with policy_engine.connect() as conn:
            commands = {
                row.cmd
                for row in conn.execute(
                    text(
                        "SELECT DISTINCT cmd FROM pg_policies "
                        "WHERE schemaname = :schema AND tablename = :table"
                    ),
                    {"schema": schema, "table": table},
                )
            }
        if "ALL" in commands:
            continue
        missing = [c for c in ("SELECT", "INSERT", "UPDATE", "DELETE") if c not in commands]
        if missing:
            uncovered.append(f"{schema}.{table} missing {missing}")

    assert not uncovered, (
        "Dropping the legacy FOR ALL policy left these tables with no policy for some command, "
        f"so that command is denied outright to juli_app and reads as empty (ADR-086): "
        f"{uncovered}"
    )
