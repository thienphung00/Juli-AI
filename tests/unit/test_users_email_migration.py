"""Migration 065 adds `users.email`, and 066 clears the fabricated phones (#1973/#1972).

The two migrations are tested together because they are one chain and their
placement is the property most easily broken by a well-meaning tidy-up:

* **065 is additive and lives in `versions/`.** Adding a nullable column with
  no default leaves the previously deployed code compatible with the schema,
  so it ships with the release.
* **066 moves rows and lives in `deferred/`.** The additive-only gate refuses
  it -- correctly. In `versions/` it would be pending on every release, the
  gate would refuse, no candidate would start, and 065's expand code could
  never go live. It is the tail of the chain for the same reason: a deferred
  step with a later revision above it would fork the chain the moment an
  operator copied it into a serving release's `versions/`.

The Postgres half applies each migration's own `upgrade()` through Alembic's
`Operations` context against a `users` table built in the pre-065 shape, in a
schema of its own on a `search_path`, so nothing touches the shared
`public.users`. 066 in particular cannot be proven any other way: its predicate
is a per-row identity, and the only honest test is to seed a fabricated row
beside a real number and see which one survives.
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

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import requires_postgres

__all__ = ["requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_ROOT = REPO_ROOT / "backend/src/juli_backend/database/migrations"
VERSIONS_DIR = MIGRATIONS_ROOT / "versions"
DEFERRED_DIR = MIGRATIONS_ROOT / "deferred"
EMAIL_065_PATH = VERSIONS_DIR / "065_users_email.py"
CLEANUP_066_PATH = DEFERRED_DIR / "066_users_placeholder_phone_cleanup.py"
RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/backend-deploy-runbook.md"

EMAIL_REVISION = "065_users_email"
CLEANUP_REVISION = "066_users_placeholder_phone_cleanup"
PHONE_REVISION = "064_users_phone_nullable"

_SCHEMA = "users_email_065"


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


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Chain and placement
# ---------------------------------------------------------------------------


def test_the_chain_is_linear_064_065_066() -> None:
    """Each revision's parent is the one before it, with no branch."""
    assert _revision_ids(EMAIL_065_PATH) == (EMAIL_REVISION, PHONE_REVISION)
    assert _revision_ids(CLEANUP_066_PATH) == (CLEANUP_REVISION, EMAIL_REVISION)


def test_065_is_in_versions_and_066_is_not() -> None:
    assert EMAIL_065_PATH.is_file()
    assert CLEANUP_066_PATH.is_file()
    stray = [p.name for p in VERSIONS_DIR.glob("066*")]
    assert stray == [], (
        f"{stray} is in versions/, so the additive gate will inspect it as "
        "pending and refuse every release -- and 065's expand code, which this "
        "step depends on, could never reach production."
    )


def test_066_is_the_tail_of_the_chain() -> None:
    """Nothing in versions/ revises the deferred step.

    If a later migration did, copying 066 into a serving release's `versions/`
    -- which is exactly what the operator procedure does -- would give 065 two
    children and `alembic upgrade head` would refuse with multiple heads.
    """
    children = sorted(
        path.name
        for path in VERSIONS_DIR.glob("*.py")
        if _revision_ids(path)[1] == CLEANUP_REVISION
    )
    assert children == [], children

    later = sorted(
        path.name for path in VERSIONS_DIR.glob("*.py") if _revision_ids(path)[1] == EMAIL_REVISION
    )
    assert later == [], (
        f"{later} revises {EMAIL_REVISION}, the same parent as the deferred "
        "066. Two children of one revision fork the chain as soon as 066 is "
        "copied into a serving release."
    )


# ---------------------------------------------------------------------------
# The release gate's two opposite verdicts
# ---------------------------------------------------------------------------


def test_the_additive_gate_accepts_065() -> None:
    result = _gate()([EMAIL_065_PATH])

    assert result.accepted, result.report()
    assert result.inspected == [EMAIL_REVISION]


def test_the_additive_gate_refuses_066_and_that_is_correct() -> None:
    """The refusal IS this step's signature, not a defect to fix.

    A version of 066 the gate accepted would have stopped moving rows, which
    is the only thing it does.
    """
    result = _gate()([CLEANUP_066_PATH])

    assert not result.accepted, result.report()
    kinds = {(f.kind, f.operation) for f in result.findings}
    assert ("data_moving", "execute(UPDATE)") in kinds, result.report()


def test_the_runbook_names_the_outstanding_contract_step() -> None:
    """An unoperated contract step nobody wrote down is a step that never runs."""
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "Separately-operated contract migrations" in runbook
    assert CLEANUP_REVISION in runbook, (
        "the runbook's outstanding list does not name 066, so nothing tells an "
        "operator this step exists or what its precondition is"
    )


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


@pytest.fixture
def pre_065_users_table():
    """`users` at revision 064 -- nullable phone, no email column."""
    engine = create_engine(sync_database_url(os.environ["DATABASE_URL"]), pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        conn.execute(
            text(
                "CREATE TABLE users ("
                "  id UUID PRIMARY KEY,"
                "  phone VARCHAR(20),"
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


def _apply(engine, path: Path, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load(path, name).upgrade()


@requires_postgres
def test_065_adds_a_nullable_email_column_that_tolerates_duplicates(
    pre_065_users_table,
) -> None:
    """Nullable, no default, and -- deliberately -- not unique."""
    engine = pre_065_users_table
    _apply(engine, EMAIL_065_PATH, "versions_065_users_email")

    with engine.begin() as conn:
        column = conn.execute(
            text(
                "SELECT is_nullable, character_maximum_length, column_default "
                "FROM information_schema.columns WHERE table_schema = :s "
                "AND table_name = 'users' AND column_name = 'email'"
            ),
            {"s": _SCHEMA},
        ).one()
        assert column.is_nullable == "YES"
        assert column.character_maximum_length == 320
        assert column.column_default is None

    # A seller who re-created their Supabase account: new sub, same address.
    with engine.begin() as conn:
        for _ in range(2):
            conn.execute(
                text(f"INSERT INTO {_SCHEMA}.users (id, email) VALUES (:id, :email)"),
                {"id": str(uuid.uuid4()), "email": "seller@example.com"},
            )
        assert (
            conn.execute(
                text(f"SELECT count(*) FROM {_SCHEMA}.users WHERE email = 'seller@example.com'")
            ).scalar_one()
            == 2
        )


@requires_postgres
def test_066_clears_only_the_rows_whose_phone_was_derived_from_their_own_id(
    pre_065_users_table,
) -> None:
    """The predicate, proven against real rows rather than argued about.

    Four rows are seeded and only one may change: the one whose stored phone is
    byte-for-byte the value the deleted code would have derived from that row's
    id. A real Vietnamese mobile sharing the `+849` prefix -- which every
    Viettel/Vinaphone/Mobifone number does, and which is exactly why a `LIKE
    '+849%'` predicate would have been a data-loss bug -- must survive
    untouched, as must one seller's number that happens to be ANOTHER row's
    derived placeholder.
    """
    engine = pre_065_users_table
    _apply(engine, EMAIL_065_PATH, "versions_065_users_email")
    cleanup = _load(CLEANUP_066_PATH, "deferred_066_users_placeholder_phone_cleanup")

    fabricated_id = uuid.uuid4()
    real_id = uuid.uuid4()
    sentinel_id = uuid.uuid4()
    borrowed_id = uuid.uuid4()
    other_id = uuid.uuid4()

    seeded = {
        # Written by the removed code: derived from this row's own id.
        fabricated_id: cleanup._fabricated_phone_for(fabricated_id),
        # A real VN mobile. Same `+849` prefix a loose LIKE would have caught.
        real_id: "+84901234567",
        # An internal app-review account's fixed sentinel, out of #1972's scope.
        sentinel_id: "+849000000001",
        # A number that IS a valid derivation -- of someone else's id. The
        # predicate is per-row, so this row must not be cleared.
        borrowed_id: cleanup._fabricated_phone_for(other_id),
    }

    with engine.begin() as conn:
        for user_id, phone in seeded.items():
            conn.execute(
                text(f"INSERT INTO {_SCHEMA}.users (id, phone) VALUES (:id, :phone)"),
                {"id": str(user_id), "phone": phone},
            )
        # And one row that already has no phone at all.
        conn.execute(
            text(f"INSERT INTO {_SCHEMA}.users (id, phone) VALUES (:id, NULL)"),
            {"id": str(uuid.uuid4())},
        )

    _apply(engine, CLEANUP_066_PATH, "deferred_066_apply")

    with engine.begin() as conn:
        rows = dict(conn.execute(text(f"SELECT id, phone FROM {_SCHEMA}.users")).fetchall())

    assert rows[fabricated_id] is None, "the fabricated number was not cleared"
    assert rows[real_id] == "+84901234567", "a real number was destroyed"
    assert rows[sentinel_id] == "+849000000001", "an internal sentinel was cleared"
    assert rows[borrowed_id] == cleanup._fabricated_phone_for(other_id), (
        "a row was cleared on another row's derivation -- the predicate is not per-row"
    )


@requires_postgres
def test_066_is_idempotent(pre_065_users_table) -> None:
    """Running the contract step twice is a no-op, not a second pass of damage.

    An operator who is unsure whether it already ran must be able to just run
    it, which is only true if the second run changes nothing.
    """
    engine = pre_065_users_table
    _apply(engine, EMAIL_065_PATH, "versions_065_users_email")
    cleanup = _load(CLEANUP_066_PATH, "deferred_066_users_placeholder_phone_cleanup")

    fabricated_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {_SCHEMA}.users (id, phone) VALUES (:id, :phone)"),
            {
                "id": str(fabricated_id),
                "phone": cleanup._fabricated_phone_for(fabricated_id),
            },
        )

    _apply(engine, CLEANUP_066_PATH, "deferred_066_first")
    _apply(engine, CLEANUP_066_PATH, "deferred_066_second")

    with engine.begin() as conn:
        assert (
            conn.execute(
                text(f"SELECT count(*) FROM {_SCHEMA}.users WHERE phone IS NOT NULL")
            ).scalar_one()
            == 0
        )


def test_066_refuses_to_downgrade() -> None:
    """Reversing it means re-fabricating numbers, which is the defect itself."""
    cleanup = _load(CLEANUP_066_PATH, "deferred_066_downgrade_check")

    with pytest.raises(NotImplementedError, match="not reversible"):
        cleanup.downgrade()
