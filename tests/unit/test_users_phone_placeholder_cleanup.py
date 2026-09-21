"""The deferred contract step that un-fabricates existing phone numbers (#1972).

`064_users_phone_nullable` made the column nullable and the code stopped
inventing numbers, so no NEW row carries one. The rows written before that
release still do, and clearing them is an `UPDATE` -- data-moving, which
`infra/scripts/migration_additive_gate.py` refuses from an automatic release by
design and with no allowlist. So it ships as a separately-operated contract
step under `migrations/deferred/`, run by hand, exactly as
`docs/runbooks/backend-deploy-runbook.md` prescribes.

Two questions, answered separately because they fail separately.

**Is it parked correctly?** In `versions/` it would be pending on every release,
the gate would refuse, no candidate would start, and 064's expand code could
never go live -- the deadlock #2050 spent a week in. It must also be the TAIL of
the chain: a deferred step with a later revision above it forks the chain the
moment an operator copies it into a serving release's `versions/`, and
`alembic upgrade head` then refuses with multiple heads.

**Does its predicate clear the right rows?** This is the half that cannot be
argued, only run. The predicate is a per-row identity, so the only honest test
seeds a fabricated number beside a real one -- and beside a number that is a
valid derivation of a *different* row's id -- and sees which survives. That runs
against real Postgres, in a schema of its own on a `search_path`, so it never
touches the shared `public.users`.
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
CLEANUP_PATH = DEFERRED_DIR / "066_users_placeholder_phone_cleanup.py"
RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/backend-deploy-runbook.md"

CLEANUP_REVISION = "066_users_placeholder_phone_cleanup"
#: The step's parent. It was 064 when #1972 landed this file; #1973 added
#: `065_users_email` to `versions/` and renumbered the step onto it, so that
#: the deferred step stays the TAIL of the chain rather than becoming a
#: second child of 064 -- which forks the chain the moment an operator
#: copies it into a serving release's `versions/`.
PHONE_REVISION = "065_users_email"

_SCHEMA = "phone_cleanup_066"


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
# Placement
# ---------------------------------------------------------------------------


def test_the_cleanup_step_is_in_deferred_and_not_in_versions() -> None:
    assert CLEANUP_PATH.is_file(), f"{CLEANUP_PATH} is missing"
    stray = [p.name for p in VERSIONS_DIR.glob("*.py") if "placeholder" in p.name]
    assert stray == [], (
        f"{stray} is in versions/, so the additive gate inspects it as pending and "
        "refuses every release -- and 064's expand code, which this step depends "
        "on, could never reach production."
    )


def test_the_cleanup_step_chains_onto_the_expand_step() -> None:
    assert _revision_ids(CLEANUP_PATH) == (CLEANUP_REVISION, PHONE_REVISION)


def test_the_cleanup_step_is_the_tail_of_the_chain() -> None:
    """Nothing in `versions/` shares this step's parent or descends from it.

    Either would fork the chain as soon as an operator copies this file into a
    serving release's `versions/` -- which is exactly what the runbook
    procedure does -- and `alembic upgrade head` refuses with multiple heads.
    """
    siblings = sorted(
        path.name for path in VERSIONS_DIR.glob("*.py") if _revision_ids(path)[1] == PHONE_REVISION
    )
    assert siblings == [], (
        f"{siblings} revises {PHONE_REVISION}, the same parent as the deferred "
        f"{CLEANUP_REVISION}. Two children of one revision fork the chain."
    )
    children = sorted(
        path.name
        for path in VERSIONS_DIR.glob("*.py")
        if _revision_ids(path)[1] == CLEANUP_REVISION
    )
    assert children == [], children


def test_the_runbook_names_the_outstanding_contract_step() -> None:
    """An unoperated contract step nobody wrote down is a step that never runs."""
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "Separately-operated contract migrations" in runbook
    assert CLEANUP_REVISION in runbook, (
        "the runbook's outstanding list does not name this step, so nothing tells "
        "an operator it exists or what its precondition is"
    )


# ---------------------------------------------------------------------------
# The release gate must refuse it -- that is the signature, not a defect
# ---------------------------------------------------------------------------


def test_the_additive_gate_refuses_the_cleanup_step() -> None:
    """A version of this file the gate accepted would have stopped moving rows."""
    result = _gate()([CLEANUP_PATH])

    assert not result.accepted, result.report()
    kinds = {(f.kind, f.operation) for f in result.findings}
    assert ("data_moving", "execute(UPDATE)") in kinds, result.report()


def test_the_deferred_directory_holds_only_migrations_the_gate_refuses() -> None:
    """A file parked out of the chain that the gate would accept has no reason
    to be there, and silently skipping a releasable migration is its own defect."""
    deferred = sorted(p for p in DEFERRED_DIR.glob("*.py") if p.name != "__init__.py")
    assert deferred, "deferred/ is empty -- delete it rather than leaving it to rot"
    for path in deferred:
        assert not _gate()([path]).accepted, (
            f"{path.name} is additive, so it belongs in versions/, not deferred/"
        )


def test_the_cleanup_step_refuses_to_downgrade() -> None:
    """Reversing it means re-fabricating numbers, which is the defect itself."""
    cleanup = _load(CLEANUP_PATH, "deferred_066_downgrade_check")

    with pytest.raises(NotImplementedError, match="not reversible"):
        cleanup.downgrade()
    assert cleanup.upgrade is not None, "upgrade must still be callable"


# ---------------------------------------------------------------------------
# The predicate, against real rows
# ---------------------------------------------------------------------------


@pytest.fixture
def users_table_at_064():
    """`users` as 064/065 leave it: nullable phone, UNIQUE retained, email.

    The cleanup step touches only `phone`, so `email` is here for fidelity
    with the shape it actually runs against, not because the step reads it.
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
                "  phone VARCHAR(20),"
                "  email VARCHAR(320),"
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


def _apply(engine, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load(CLEANUP_PATH, name).upgrade()


@requires_postgres
def test_it_clears_only_rows_whose_phone_was_derived_from_their_own_id(
    users_table_at_064,
) -> None:
    """The predicate, proven against real rows rather than argued about.

    Five rows, and exactly one may change: the one whose stored phone is
    byte-for-byte the value the removed code derived from that row's id. A real
    Vietnamese mobile shares the `+849` prefix -- every
    Viettel/Vinaphone/Mobifone number does, which is precisely why a
    `LIKE '+849%'` predicate would have been a data-loss bug -- and must survive
    untouched, as must one seller holding a number that is a valid derivation of
    ANOTHER row's id.
    """
    engine = users_table_at_064
    cleanup = _load(CLEANUP_PATH, "deferred_066_predicate")

    fabricated_id = uuid.uuid4()
    real_id = uuid.uuid4()
    sentinel_id = uuid.uuid4()
    borrowed_id = uuid.uuid4()
    other_id = uuid.uuid4()
    phoneless_id = uuid.uuid4()

    seeded = {
        # Written by the removed code: derived from this row's own id.
        fabricated_id: cleanup._fabricated_phone_for(fabricated_id),
        # A real VN mobile. Same `+849` prefix a loose LIKE would have caught.
        real_id: "+84901234567",
        # An internal app-review account's fixed sentinel, out of #1972's scope.
        sentinel_id: "+849000000001",
        # A valid derivation -- of someone else's id. The predicate is per-row.
        borrowed_id: cleanup._fabricated_phone_for(other_id),
        phoneless_id: None,
    }

    with engine.begin() as conn:
        for user_id, phone in seeded.items():
            conn.execute(
                text(f"INSERT INTO {_SCHEMA}.users (id, phone) VALUES (:id, :phone)"),
                {"id": str(user_id), "phone": phone},
            )

    _apply(engine, "deferred_066_apply")

    with engine.begin() as conn:
        rows = dict(conn.execute(text(f"SELECT id, phone FROM {_SCHEMA}.users")).fetchall())

    assert rows[fabricated_id] is None, "the fabricated number was not cleared"
    assert rows[real_id] == "+84901234567", "a real number was destroyed"
    assert rows[sentinel_id] == "+849000000001", "an internal sentinel was cleared"
    assert rows[borrowed_id] == cleanup._fabricated_phone_for(other_id), (
        "a row was cleared on another row's derivation -- the predicate is not per-row"
    )
    assert rows[phoneless_id] is None


@requires_postgres
def test_it_is_idempotent(users_table_at_064) -> None:
    """An operator unsure whether it already ran must be able to just run it."""
    engine = users_table_at_064
    cleanup = _load(CLEANUP_PATH, "deferred_066_idempotent")

    fabricated_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {_SCHEMA}.users (id, phone) VALUES (:id, :phone)"),
            {"id": str(fabricated_id), "phone": cleanup._fabricated_phone_for(fabricated_id)},
        )

    _apply(engine, "deferred_066_first")
    _apply(engine, "deferred_066_second")

    with engine.begin() as conn:
        remaining = conn.execute(
            text(f"SELECT count(*) FROM {_SCHEMA}.users WHERE phone IS NOT NULL")
        ).scalar_one()
    assert remaining == 0
