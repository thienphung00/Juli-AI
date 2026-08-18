"""Schema/migration checks for #1125 / AGT-W3B (migration
`035_workflow_run_events_table`) — ties to the issue's acceptance criteria:
the `workflow_run_events` shape, the unique `(workflow_run_id,
sequence_number)` index behaving as a crash-replay no-op guard at the
database level (ADR-074 d.1), the real FK to `workflow_runs.id` rejecting an
orphaned row, the migration chaining onto `034_workflow_runs_table`
specifically, exactly one Alembic head, and that the migration cannot apply
cleanly against a database missing `034_*`.

File-content assertions (revision string, down_revision, single head) need
no database and always run. Everything else is gated by `requires_postgres`
(reused from `tests/integration/test_migrations.py`, the same gate every
other migration-shaped test in this repo already uses) and skips cleanly
wherever `DATABASE_URL` is not a reachable local Postgres.

Reuses `test_workflow_runs_schema.py`'s `_assert_local_database_url`
discipline (issue #734) for any operation that resets a database to an
earlier revision -- only ever a throwaway local Postgres.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import postgres_at_head, requires_postgres  # noqa: F401

__all__ = ["postgres_at_head", "requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_035_PATH = MIGRATIONS_DIR / "035_workflow_run_events_table.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _assert_local_database_url(url: str) -> None:
    """Refuse a destructive Alembic downgrade against anything but a local,
    disposable Postgres -- issue #734's discipline, reproduced here rather
    than importing a private helper from another test module (matching
    `test_workflow_runs_schema.py`'s own convention)."""
    hostname = urlparse(url).hostname
    if hostname is not None and hostname.lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing a destructive Alembic downgrade against a non-local "
            f"DATABASE_URL host ({hostname}); this test only ever downgrades a "
            "throwaway local database."
        )


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option(
        "sqlalchemy.url", sync_database_url(os.environ.get("DATABASE_URL", "").strip())
    )
    return cfg


def _sync_engine() -> Engine:
    return create_engine(sync_database_url(os.environ.get("DATABASE_URL", "").strip()))


def _reset_to_revision(cfg: Config, revision: str) -> None:
    _assert_local_database_url(os.environ.get("DATABASE_URL", "").strip())
    command.downgrade(cfg, "base")
    command.upgrade(cfg, revision)


def _columns_by_name(engine: Engine, table: str) -> dict:
    return {c["name"]: c for c in inspect(engine).get_columns(table)}


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_035_revision_equals_filename_stem():
    assert MIGRATION_035_PATH.exists(), f"missing {MIGRATION_035_PATH}"
    body = MIGRATION_035_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 035 has no `revision: str = ...` line"
    assert rev.group(1) == "035_workflow_run_events_table"
    assert rev.group(1) == MIGRATION_035_PATH.stem


def test_migration_035_down_revision_is_034():
    body = MIGRATION_035_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 035 has no string `down_revision`"
    assert down.group(1) == "034_workflow_runs_table"


def test_exactly_one_migration_head_after_035():
    """Walks the entire chain (not just 035) so a second, unrelated branch
    anywhere in the tree also fails this.

    Asserts the chain-invariant this test actually cares about -- no
    accidental branch, exactly one head -- without pinning which revision
    that head is, for the same reason `test_workflow_runs_schema.py`'s
    `test_exactly_one_migration_head_after_034` gives:
    `035_workflow_run_events_table` was head the day this test was written,
    but is a valid, expected non-head the moment a later slice
    (`036_cancel_requested_column`, #1160) chains onto it; a literal-pinned
    assertion here would fail every subsequent migration for the wrong
    reason, exactly the anti-pattern
    `tests/integration/test_migrations.py`'s `_latest_revision()` docstring
    already warns against. `035` itself being a real, present, non-orphaned
    node in the chain is asserted separately by
    `test_migration_035_down_revision_is_034` above and (once a later slice
    chains onto it) whatever that slice's own down-revision test asserts."""
    revisions: dict[str, str | None] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
        if rev:
            revisions[rev.group(1)] = down.group(1) if down and down.group(1) else None
    parents = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in parents]
    assert len(heads) == 1, f"expected exactly one head, got {sorted(heads)}"


# ---------------------------------------------------------------------------
# Postgres-backed schema assertions.
# ---------------------------------------------------------------------------


@requires_postgres
def test_workflow_run_events_table_shape_at_head(postgres_at_head: Engine):
    inspector = inspect(postgres_at_head)
    assert "workflow_run_events" in inspector.get_table_names()

    columns = _columns_by_name(postgres_at_head, "workflow_run_events")
    expected_columns = {
        "id",
        "workflow_run_id",
        "sequence_number",
        "event_type",
        "timestamp",
        "payload",
        "v",
    }
    assert expected_columns <= set(columns), f"missing columns: {expected_columns - set(columns)}"

    assert "JSONB" in str(columns["payload"]["type"]).upper()
    assert columns["payload"]["nullable"] is False
    assert columns["workflow_run_id"]["nullable"] is False
    assert columns["sequence_number"]["nullable"] is False
    assert columns["event_type"]["nullable"] is False
    assert columns["timestamp"]["nullable"] is False
    assert columns["v"]["nullable"] is False

    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in inspector.get_foreign_keys("workflow_run_events")
    }
    assert fks.get("workflow_run_id") == "workflow_runs"

    unique_column_sets = {
        frozenset(u["column_names"])
        for u in inspector.get_unique_constraints("workflow_run_events")
    }
    unique_index_sets = {
        frozenset(idx["column_names"])
        for idx in inspector.get_indexes("workflow_run_events")
        if idx.get("unique")
    }
    assert frozenset({"workflow_run_id", "sequence_number"}) in (
        unique_column_sets | unique_index_sets
    ), "missing unique (workflow_run_id, sequence_number) index/constraint"


def _seed_shop_product_run(session) -> tuple:
    from juli_backend.models import models as m

    user = m.User(phone="+15550001234")
    session.add(user)
    session.flush()
    shop = m.Shop(user_id=user.id, shop_name="AGT-W3B Test Shop")
    session.add(shop)
    session.flush()
    product = m.Product(
        shop_id=shop.id,
        tiktok_product_id="agt-w3b-product-1",
        name="Test Widget",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(product)
    session.flush()
    run = m.WorkflowRun(
        shop_id=shop.id,
        product_id=product.id,
        state={},
        status="running",
        prompt_version="optimize_product.v1",
        prompt_sha256="a" * 64,
    )
    session.add(run)
    session.flush()
    return shop, product, run


@requires_postgres
def test_second_insert_same_run_and_sequence_violates_unique_index(postgres_at_head: Engine):
    """ADR-074 d.1: the unique (workflow_run_id, sequence_number) index is
    the mechanism that turns a crash-replayed emit into a no-op -- assert
    this at the database level."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        _shop, _product, run = _seed_shop_product_run(session)

        session.add(
            m.WorkflowRunEvent(
                workflow_run_id=run.id,
                sequence_number=0,
                event_type="workflow.started",
                timestamp=datetime.now(UTC),
                payload={"workflow_key": "optimize_product", "product_ref": "p1"},
                v=1,
            )
        )
        session.commit()

        session.add(
            m.WorkflowRunEvent(
                workflow_run_id=run.id,
                sequence_number=0,
                event_type="workflow.status",
                timestamp=datetime.now(UTC),
                payload={"phase_narration": "duplicate replay"},
                v=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # A different sequence number for the same run is not blocked.
        session.add(
            m.WorkflowRunEvent(
                workflow_run_id=run.id,
                sequence_number=1,
                event_type="workflow.status",
                timestamp=datetime.now(UTC),
                payload={"phase_narration": "not a duplicate"},
                v=1,
            )
        )
        session.commit()


@requires_postgres
def test_orphaned_workflow_run_id_rejected(postgres_at_head: Engine):
    """ADR-074 d.1: a real FK to workflow_runs.id -- an event row naming a
    workflow_run_id that doesn't exist is rejected."""
    import uuid

    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        session.add(
            m.WorkflowRunEvent(
                workflow_run_id=uuid.uuid4(),
                sequence_number=0,
                event_type="workflow.started",
                timestamp=datetime.now(UTC),
                payload={},
                v=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@requires_postgres
def test_migration_035_fails_without_034():
    """Migration 035's own upgrade() body is invoked directly (bypassing
    Alembic's normal chain-resolving `command.upgrade`, which would just
    apply 034 first) against a database reset to 033 -- one revision short
    of 034, so `workflow_runs` does not exist yet. The `CREATE TABLE ...
    REFERENCES workflow_runs(id)` in 035's upgrade() must fail at the
    database level."""
    cfg = _alembic_config()
    _reset_to_revision(cfg, "033_impact_readings_table")

    script = ScriptDirectory.from_config(cfg)
    revision_script = script.get_revision("035_workflow_run_events_table")
    module = revision_script.module

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            ctx = MigrationContext.configure(conn)
            try:
                with Operations.context(ctx):
                    with pytest.raises(SQLAlchemyError):
                        module.upgrade()
            finally:
                trans.rollback()
    finally:
        engine.dispose()

    # Leave the database at head for any other test that reuses it.
    command.upgrade(cfg, "head")
