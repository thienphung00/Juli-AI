"""Migration 064 widens `users.phone` to NULL, and the release gate accepts it (#1972).

Two questions, answered separately because they fail separately.

**Is it release-safe?** `infra/scripts/migration_additive_gate.py` refuses a
pending migration that narrows a column or moves rows, because during a release
the candidate and the still-serving stable instance share one database and only
additive change keeps a code rollback possible. Dropping `NOT NULL` *widens*
what the column accepts, so the previous code -- which always supplied a phone
-- stays valid against this schema. The gate says so; this module runs the real
gate against the real file rather than asserting the conclusion.

**Does it do what it says on a real database?** `alter_column(nullable=True)`
is a one-liner whose behaviour lives entirely in Postgres, so the file-level
assertions above prove nothing about it. The Postgres-gated half below applies
064's own `upgrade()` -- the real function, through Alembic's own `Operations`
context -- to a `users` table built in the pre-064 shape, and then checks the
three properties that actually matter:

* the column accepts NULL afterwards;
* two phone-less rows coexist, because Postgres's UNIQUE treats NULLs as
  distinct (the property the fix depends on, and the one the SQLite unit
  fixture cannot prove);
* two identical *real* numbers are still rejected, because UNIQUE was kept.

It runs in a schema of its own on a `search_path`, so it never touches the
shared `public.users` and is not a destructive migration test.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import requires_postgres

__all__ = ["requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_ROOT = REPO_ROOT / "backend/src/juli_backend/database/migrations"
VERSIONS_DIR = MIGRATIONS_ROOT / "versions"
DEFERRED_DIR = MIGRATIONS_ROOT / "deferred"
MIGRATION_064_PATH = VERSIONS_DIR / "064_users_phone_nullable.py"

REVISION = "064_users_phone_nullable"
#: Production applied `063_workflow_subject_contract` by hand on 2026-09-20
#: (#2050's contract step). 064's parent is that revision, not 062 -- chaining
#: onto 062 would fork the chain at the revision production is actually on.
DOWN_REVISION = "063_workflow_subject_contract"

_SCHEMA = "phone_nullable_064"


def _revision_ids(path: Path) -> tuple[str | None, str | None]:
    body = path.read_text(encoding="utf-8")
    revision = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
    return (
        revision.group(1) if revision else None,
        down.group(1) if down and down.group(1) else None,
    )


def _gate():
    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    return evaluate_migration_paths


# ---------------------------------------------------------------------------
# Source-level: identity, placement, and the release gate
# ---------------------------------------------------------------------------


def test_064_exists_in_versions_and_not_in_deferred() -> None:
    """064 is an expand step, so it belongs in the chain the release lane runs."""
    assert MIGRATION_064_PATH.is_file(), f"{MIGRATION_064_PATH} is missing"
    assert not (DEFERRED_DIR / MIGRATION_064_PATH.name).exists(), (
        "064 is additive and must ship WITH the release; parking it in "
        "deferred/ would leave production on a NOT NULL column while the code "
        "that stopped supplying a phone is already serving."
    )


def test_064_chains_onto_the_revision_production_is_on() -> None:
    revision, down = _revision_ids(MIGRATION_064_PATH)

    assert revision == REVISION
    assert down == DOWN_REVISION, (
        f"064 revises {down!r}. Production is at {DOWN_REVISION!r} (applied by "
        "hand 2026-09-20); chaining onto anything else forks the Alembic chain."
    )


def test_064_reserves_a_revision_number_nothing_else_claims() -> None:
    """No other migration file, in versions/ or deferred/, is revision 064."""
    claimants = sorted(
        path.name
        for path in [*VERSIONS_DIR.glob("*.py"), *DEFERRED_DIR.glob("*.py")]
        if _revision_ids(path)[0] == REVISION
    )

    assert claimants == [MIGRATION_064_PATH.name], claimants


def test_the_additive_only_gate_accepts_064() -> None:
    """The release lane will start a candidate with this migration pending.

    Widening is the whole reason it passes, and the reason the *data* half of
    #1972 -- nulling the rows that already carry a fabricated number -- is not
    in this file: an UPDATE is data-moving, the gate refuses it by design, and
    it ships as a separately-operated contract step instead.
    """
    result = _gate()([MIGRATION_064_PATH])

    assert result.accepted, result.report()
    assert result.inspected == [REVISION]


def test_064_moves_no_rows() -> None:
    """The file contains no INSERT/UPDATE/DELETE, by the gate's own reckoning.

    A second, narrower statement of the same property: if a future edit adds
    "while we're here, let's also null the placeholders", the gate test above
    fails -- and so does this one, naming the reason.
    """
    result = _gate()([MIGRATION_064_PATH])

    data_moving = [f for f in result.findings if f.kind == "data_moving"]
    assert data_moving == [], [f.render() for f in data_moving]


# ---------------------------------------------------------------------------
# Postgres: what the ALTER actually does
# ---------------------------------------------------------------------------


def _load_migration_064():
    spec = importlib.util.spec_from_file_location(
        "versions_064_users_phone_nullable", MIGRATION_064_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pre_064_users_table():
    """A `users` table in the shape migration 001 left it, in a private schema.

    `search_path` is what lets 064's unqualified `op.alter_column("users", ...)`
    -- the real statement, unmodified -- land here instead of on the shared
    `public.users`. The schema is dropped afterwards, so this test is not
    destructive and needs no database of its own.
    """
    engine = create_engine(sync_database_url(os.environ["DATABASE_URL"]), pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        conn.execute(
            text(
                "CREATE TABLE users ("
                "  id UUID PRIMARY KEY,"
                "  phone VARCHAR(20) NOT NULL,"
                "  display_name VARCHAR(100),"
                "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                "  CONSTRAINT users_phone_key UNIQUE (phone)"
                ")"
            )
        )
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        engine.dispose()


def _phone_is_nullable(conn) -> bool:
    return (
        conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = 'users' "
                "AND column_name = 'phone'"
            ),
            {"s": _SCHEMA},
        ).scalar_one()
        == "YES"
    )


def _insert(conn, phone: str | None) -> None:
    conn.execute(
        text(f"INSERT INTO {_SCHEMA}.users (id, phone) VALUES (:id, :phone)"),
        {"id": str(uuid.uuid4()), "phone": phone},
    )


@requires_postgres
def test_064_makes_phone_nullable_on_postgres(pre_064_users_table) -> None:
    """Before: NULL is rejected. After 064's own upgrade(): accepted."""
    engine = pre_064_users_table

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        assert not _phone_is_nullable(conn)
        with pytest.raises(IntegrityError):
            _insert(conn, None)

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration_064().upgrade()

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        assert _phone_is_nullable(conn)
        _insert(conn, None)


@requires_postgres
def test_064_leaves_unique_intact_and_nulls_do_not_collide(pre_064_users_table) -> None:
    """The UNIQUE constraint survives, and NULLs are distinct under it.

    This is the property the whole fix rests on -- many phone-less sellers, one
    column, one UNIQUE index -- and it is a *Postgres* property. The unit
    `session` fixture is SQLite, so the coexistence test over there is
    suggestive, not proof; this is the proof.
    """
    engine = pre_064_users_table

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration_064().upgrade()

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        for _ in range(3):
            _insert(conn, None)
        assert (
            conn.execute(
                text(f"SELECT count(*) FROM {_SCHEMA}.users WHERE phone IS NULL")
            ).scalar_one()
            == 3
        )

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        _insert(conn, "+84901234567")

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        with pytest.raises(IntegrityError):
            _insert(conn, "+84901234567")
