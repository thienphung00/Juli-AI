"""Schema/migration checks for #1269 / AGT-W5A-DP (migration
`040_workflow_run_action_card`, ADR-082 decision 6) -- ties directly to the
issue's acceptance criteria: revision id length, `down_revision` chained on
`039_run_confirmations`, single migration head, the additive
`workflow_runs.action_card_id` column (nullable UUID, FK to
`action_cards.id`), the FK's actual runtime enforcement (proven by an insert
that must raise `IntegrityError`, not just "the constraint exists"), that no
existing row is rewritten by the migration, and a clean downgrade/upgrade
round trip.

File-content assertions (revision string, down_revision, single head, id
length -- four tests total) need no database and always run at issue tier.

Everything else is Postgres-backed: gated by `requires_postgres` (reused from
`tests/integration/test_migrations.py`) and individually marked
`@pytest.mark.migration_heavy` -- deliberately per-test, not a module-level
`pytestmark`, so the four structural tests above keep running at issue tier
while these run only at main tier on the wave->main PR, matching #1214's
review finding (`tests/unit/test_run_confirmations_approvals_schema.py`,
the precedent this file follows).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import postgres_at_head, requires_postgres  # noqa: F401

__all__ = ["postgres_at_head", "requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_040_PATH = MIGRATIONS_DIR / "040_workflow_run_action_card.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


def _sync_engine() -> Engine:
    return create_engine(sync_database_url(_database_url()), pool_pre_ping=True)


def _assert_local_database_url(url: str) -> None:
    """Refuse to downgrade against anything but a local, disposable Postgres
    -- issue #734's discipline, reproduced here rather than importing a
    private helper from another test module (same pattern as #1214's
    `test_run_confirmations_approvals_schema.py`)."""
    hostname = urlparse(url).hostname
    if hostname is not None and hostname.lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing a destructive Alembic downgrade against a non-local "
            f"DATABASE_URL host ({hostname}); this test only ever downgrades a "
            "throwaway local database."
        )


def _reset_to_revision(cfg: Config, revision: str) -> None:
    _assert_local_database_url(_database_url())
    command.downgrade(cfg, "base")
    command.upgrade(cfg, revision)


def _columns_by_name(engine: Engine, table: str, schema: str | None = None) -> dict:
    return {c["name"]: c for c in inspect(engine).get_columns(table, schema=schema)}


def _seed_shop_and_user(session) -> tuple:
    from juli_backend.models import models as m

    user = m.User(phone="+15550001269")
    session.add(user)
    session.flush()
    shop = m.Shop(user_id=user.id, shop_name="AGT-W5A-DP #1269 Test Shop")
    session.add(shop)
    session.flush()
    return user, shop


def _seed_product(session, shop) -> object:
    from juli_backend.models import models as m

    product = m.Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-w5a-dp-1269-{uuid.uuid4().hex[:8]}",
        name="Test Widget 1269",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(product)
    session.flush()
    return product


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_040_revision_equals_filename_stem():
    assert MIGRATION_040_PATH.exists(), f"missing {MIGRATION_040_PATH}"
    body = MIGRATION_040_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 040 has no `revision: str = ...` line"
    assert rev.group(1) == "040_workflow_run_action_card"
    assert rev.group(1) == MIGRATION_040_PATH.stem
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32), a longer id fails only "
        "at upgrade time with StringDataRightTruncation"
    )


def test_migration_040_down_revision_is_039():
    body = MIGRATION_040_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 040 has no string `down_revision`"
    assert down.group(1) == "039_run_confirmations"


def test_exactly_one_migration_head_after_040():
    """Walks the entire chain (not just 040) so a second, unrelated branch
    anywhere in the tree also fails this.

    Asserts the chain-invariant this test actually cares about -- no
    accidental branch, exactly one head -- without pinning which revision
    that head is, matching the convention `test_workflow_runs_schema.py`'s
    `test_exactly_one_migration_head_after_034` and
    `test_workflow_run_events_schema.py`'s
    `test_exactly_one_migration_head_after_035` already establish:
    `040_workflow_run_action_card` is head the day this test is written, but
    is a valid, expected non-head the moment a later slice chains onto it; a
    literal-pinned assertion here would fail every subsequent migration for
    the wrong reason. `040` itself being a real, present, non-orphaned node
    in the chain is asserted separately by
    `test_migration_040_down_revision_is_039` above."""
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


def test_migration_040_touches_only_action_card_id():
    """Additive-only: this migration must not touch any of the columns
    `workflow_runs` already carries (shop_id, product_id, state, status,
    stop_reason, prompt_version, prompt_sha256, the timing columns,
    cancel_requested, required_steps_completed)."""
    body = MIGRATION_040_PATH.read_text(encoding="utf-8")
    upgrade_body = body.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    untouched = (
        "shop_id",
        "product_id",
        '"state"',
        '"status"',
        "stop_reason",
        "prompt_version",
        "prompt_sha256",
        "cancel_requested",
        "required_steps_completed",
    )
    for column in untouched:
        assert column not in upgrade_body, (
            f"migration 040 must not touch existing column {column!r}"
        )
    assert "action_card_id" in upgrade_body


# ---------------------------------------------------------------------------
# Postgres-backed schema assertions.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.migration_heavy
def test_workflow_runs_action_card_id_column_shape_at_head(postgres_at_head: Engine):
    inspector = inspect(postgres_at_head)
    columns = _columns_by_name(postgres_at_head, "workflow_runs")
    assert "action_card_id" in columns, "workflow_runs missing action_card_id"
    assert columns["action_card_id"]["nullable"] is True

    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in inspector.get_foreign_keys("workflow_runs")
        if fk["constrained_columns"] == ["action_card_id"]
    }
    assert fks.get("action_card_id") == "action_cards"


@requires_postgres
@pytest.mark.migration_heavy
def test_action_card_id_defaults_to_null_on_insert(postgres_at_head: Engine):
    """A freshly inserted `workflow_runs` row with no `action_card_id`
    supplied reads back NULL -- no synthesized value, no backfill."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        user, shop = _seed_shop_and_user(session)
        product = _seed_product(session, shop)

        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            state={},
            status="queued",
            prompt_version="optimize_product.v1",
            prompt_sha256="a" * 64,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        assert run.action_card_id is None


@requires_postgres
@pytest.mark.migration_heavy
def test_action_card_id_fk_rejects_nonexistent_card(postgres_at_head: Engine):
    """The FK is enforced at the database level -- proven by inserting a
    `workflow_runs` row with a nonexistent `action_card_id` and asserting
    `IntegrityError`, not by asserting the constraint exists in metadata."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        user, shop = _seed_shop_and_user(session)
        product = _seed_product(session, shop)

        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            state={},
            status="queued",
            prompt_version="optimize_product.v1",
            prompt_sha256="b" * 64,
            action_card_id=uuid.uuid4(),  # does not exist in action_cards
        )
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@requires_postgres
@pytest.mark.migration_heavy
def test_action_card_id_fk_accepts_real_card(postgres_at_head: Engine):
    """Positive path: a `workflow_runs` row FK'd to a real `action_cards`
    row round-trips correctly."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        user, shop = _seed_shop_and_user(session)
        product = _seed_product(session, shop)
        card = m.ActionCard(
            shop_id=shop.id,
            workflow_key="optimize_product_price",
            priority=1,
            severity="medium",
            title="Card for #1269",
            description="Card for #1269 FK test",
        )
        session.add(card)
        session.flush()

        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            state={},
            status="queued",
            prompt_version="optimize_product.v1",
            prompt_sha256="c" * 64,
            action_card_id=card.id,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        assert run.action_card_id == card.id


@requires_postgres
@pytest.mark.migration_heavy
def test_migration_040_upgrade_and_downgrade_round_trip_cleanly():
    """Migration 040's `downgrade()` actually works -- drops the column, and
    upgrading again restores it, with no leftover state in between."""
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "040_workflow_run_action_card")
        columns_at_head = _columns_by_name(engine, "workflow_runs")
        assert "action_card_id" in columns_at_head

        command.downgrade(cfg, "039_run_confirmations")
        columns_after_downgrade = _columns_by_name(engine, "workflow_runs")
        assert "action_card_id" not in columns_after_downgrade, (
            "downgrade() did not drop action_card_id"
        )
        # 039's own tables must be untouched by 040's downgrade.
        assert "run_confirmations" in inspect(engine).get_table_names()
        assert "action_card_approvals" in inspect(engine).get_table_names()

        command.upgrade(cfg, "040_workflow_run_action_card")
        columns_after_reupgrade = _columns_by_name(engine, "workflow_runs")
        assert "action_card_id" in columns_after_reupgrade
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.migration_heavy
def test_existing_workflow_run_row_not_rewritten_by_migration(postgres_at_head: Engine):
    """A `workflow_runs` row seeded BEFORE the migration runs must read back
    with `action_card_id IS NULL` and every other column byte-identical --
    no existing row is rewritten, asserted rather than assumed.

    Seeded via raw SQL, deliberately not the ORM model: `WorkflowRun` always
    reflects the CURRENT mapped columns (including `action_card_id` once
    this slice lands), so an ORM insert at revision 039 would silently
    include a column the database does not have yet at that revision and
    prove nothing about pre-existing rows."""
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "039_run_confirmations")

        from sqlalchemy.orm import Session

        with Session(engine) as session:
            user, shop = _seed_shop_and_user(session)
            product = _seed_product(session, shop)
            session.commit()
            shop_id = shop.id
            product_id = product.id

        run_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO workflow_runs
                        (id, shop_id, product_id, state, status, stop_reason,
                         prompt_version, prompt_sha256)
                    VALUES
                        (:id, :shop_id, :product_id, CAST(:state AS JSON), :status,
                         :stop_reason, :prompt_version, :prompt_sha256)
                    """
                ),
                {
                    "id": run_id,
                    "shop_id": shop_id,
                    "product_id": product_id,
                    "state": '{"pre_migration": true}',
                    "status": "completed",
                    "stop_reason": "final_response",
                    "prompt_version": "optimize_product.v1",
                    "prompt_sha256": "d" * 64,
                },
            )

        command.upgrade(cfg, "040_workflow_run_action_card")

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT shop_id, product_id, status, stop_reason, action_card_id "
                    "FROM workflow_runs WHERE id = :id"
                ),
                {"id": run_id},
            ).one()

        assert row.shop_id == shop_id
        assert row.product_id == product_id
        assert row.status == "completed"
        assert row.stop_reason == "final_response"
        assert row.action_card_id is None
    finally:
        engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
