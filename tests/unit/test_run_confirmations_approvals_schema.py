"""Schema/migration checks for #1214 / AGT-W5A-DP (migration
`039_run_confirmations`) -- ties directly to the issue's acceptance
criteria: the `run_confirmations` shape (ADR-075 decision 2), the
`action_card_approvals` audit-record shape (ADR-075 decision 1), the
partial unique index's actual runtime behavior (a second `pending` row for
the same run must raise `IntegrityError`, not just "the index exists"),
revision id length, exactly one migration head, and a clean
downgrade/upgrade round trip.

File-content assertions (revision string, down_revision, single head, id
length) need no database and always run. Everything else is gated by
`requires_postgres` (reused from `tests/integration/test_migrations.py`,
the same gate every other migration-shaped test in this repo already uses)
and skips cleanly wherever `DATABASE_URL` is not a reachable local
Postgres.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import postgres_at_head, requires_postgres  # noqa: F401

__all__ = ["postgres_at_head", "requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_039_PATH = MIGRATIONS_DIR / "039_run_confirmations.py"

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
    private helper from another test module."""
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

    user = m.User(phone="+15550001214")
    session.add(user)
    session.flush()
    shop = m.Shop(user_id=user.id, shop_name="AGT-W5A-DP Test Shop")
    session.add(shop)
    session.flush()
    return user, shop


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_039_revision_equals_filename_stem():
    assert MIGRATION_039_PATH.exists(), f"missing {MIGRATION_039_PATH}"
    body = MIGRATION_039_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 039 has no `revision: str = ...` line"
    assert rev.group(1) == "039_run_confirmations"
    assert rev.group(1) == MIGRATION_039_PATH.stem
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32), a longer id fails only "
        "at upgrade time with StringDataRightTruncation"
    )


def test_migration_039_down_revision_is_038():
    body = MIGRATION_039_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 039 has no string `down_revision`"
    assert down.group(1) == "038_credential_refresh_cols"


def test_exactly_one_migration_head_after_039():
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
    assert heads[0] == "039_run_confirmations"


def test_migration_039_does_not_touch_required_steps_completed():
    """Item 3 of #1214 (`workflow_runs.required_steps_completed`) already
    shipped in 037 (W4, #1235) -- this migration must not add it again.
    Checked against `upgrade()`'s body only (not the whole file), since the
    module docstring legitimately *names* the column to explain why it is
    untouched here."""
    body = MIGRATION_039_PATH.read_text(encoding="utf-8")
    upgrade_body = body.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "required_steps_completed" not in upgrade_body


# ---------------------------------------------------------------------------
# Postgres-backed schema assertions.
# ---------------------------------------------------------------------------


@requires_postgres
def test_run_confirmations_table_shape_at_head(postgres_at_head: Engine):
    inspector = inspect(postgres_at_head)
    assert "run_confirmations" in inspector.get_table_names()
    columns = _columns_by_name(postgres_at_head, "run_confirmations")
    for col in (
        "id",
        "workflow_run_id",
        "tool_call_id",
        "options",
        "status",
        "selected_option_id",
        "created_at",
        "decided_at",
        "expires_at",
    ):
        assert col in columns, f"run_confirmations missing column {col}"
    assert columns["selected_option_id"]["nullable"] is True
    assert columns["decided_at"]["nullable"] is True

    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in inspector.get_foreign_keys("run_confirmations")
    }
    assert fks.get("workflow_run_id") == "workflow_runs"

    index_names = {ix["name"] for ix in inspector.get_indexes("run_confirmations")}
    assert "uq_run_confirmations_pending_run" in index_names
    assert "ix_run_confirmations_workflow_run" in index_names


@requires_postgres
def test_action_card_approvals_table_shape_at_head(postgres_at_head: Engine):
    inspector = inspect(postgres_at_head)
    assert "action_card_approvals" in inspector.get_table_names()
    columns = _columns_by_name(postgres_at_head, "action_card_approvals")
    for col in ("id", "action_card_id", "approved_by_user_id", "approved_at", "card_snapshot"):
        assert col in columns, f"action_card_approvals missing column {col}"

    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in inspector.get_foreign_keys("action_card_approvals")
    }
    assert fks.get("action_card_id") == "action_cards"
    assert fks.get("approved_by_user_id") == "users"

    index_names = {ix["name"] for ix in inspector.get_indexes("action_card_approvals")}
    assert "ix_action_card_approvals_action_card" in index_names


@requires_postgres
def test_run_confirmations_partial_unique_index_rejects_second_pending_row(
    postgres_at_head: Engine,
):
    """ADR-075 decision 2 / the confirmation-authorization ladder's "matches
    THE pending confirmation" step: a run may have at most one open decision
    request. Proven here by actually inserting two `pending` rows for the
    same `workflow_run_id` and asserting the second raises `IntegrityError`
    -- not by asserting the index exists."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        user, shop = _seed_shop_and_user(session)
        product = m.Product(
            shop_id=shop.id,
            tiktok_product_id="agt-w5a-dp-product-1",
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
            status="waiting_approval",
            prompt_version="optimize_product.v1",
            prompt_sha256="b" * 64,
        )
        session.add(run)
        session.flush()

        now = datetime.now(UTC)

        def new_confirmation(tool_call_id: str, status: str) -> m.RunConfirmation:
            return m.RunConfirmation(
                workflow_run_id=run.id,
                tool_call_id=tool_call_id,
                options=[
                    {
                        "option_id": "opt_1",
                        "proposed_change": {"price": "199000"},
                        "rationale": "hold margin",
                        "params_sha": "c" * 64,
                    }
                ],
                status=status,
                expires_at=now + timedelta(hours=4),
            )

        first = new_confirmation("call_1", "pending")
        session.add(first)
        session.commit()

        second = new_confirmation("call_2", "pending")
        session.add(second)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # A terminal row never blocks a fresh pending row for the same run.
        first.status = "approved"
        first.selected_option_id = "opt_1"
        first.decided_at = now
        session.commit()

        third = new_confirmation("call_3", "pending")
        session.add(third)
        session.commit()


@requires_postgres
def test_migration_039_upgrade_and_downgrade_round_trip_cleanly():
    """Migration 039's `downgrade()` actually works -- drops both tables,
    and upgrading again restores them, with no leftover state in between."""
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "039_run_confirmations")
        tables_at_head = set(inspect(engine).get_table_names())
        assert "run_confirmations" in tables_at_head
        assert "action_card_approvals" in tables_at_head

        command.downgrade(cfg, "038_credential_refresh_cols")
        tables_after_downgrade = set(inspect(engine).get_table_names())
        assert "run_confirmations" not in tables_after_downgrade, (
            "downgrade() did not drop run_confirmations"
        )
        assert "action_card_approvals" not in tables_after_downgrade, (
            "downgrade() did not drop action_card_approvals"
        )
        # 038's own columns must be untouched by 039's downgrade.
        assert "status" in _columns_by_name(engine, "tiktok_credentials")

        command.upgrade(cfg, "039_run_confirmations")
        tables_after_reupgrade = set(inspect(engine).get_table_names())
        assert "run_confirmations" in tables_after_reupgrade
        assert "action_card_approvals" in tables_after_reupgrade
    finally:
        engine.dispose()


@requires_postgres
def test_latest_downgrade_drops_only_revision_039_tables(postgres_at_head: Engine):
    """Downgrading past 039 removes both new tables; earlier tables/data
    (037's required_steps_completed, 038's credential columns) remain."""
    from tests.integration.test_migrations import _seed_representative_rows

    ids = _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert "run_confirmations" in inspect(postgres_at_head).get_table_names()
    assert "action_card_approvals" in inspect(postgres_at_head).get_table_names()

    command.downgrade(cfg, "038_credential_refresh_cols")

    tables = set(inspect(postgres_at_head).get_table_names())
    assert "run_confirmations" not in tables
    assert "action_card_approvals" not in tables
    assert "status" in _columns_by_name(postgres_at_head, "tiktok_credentials")
    assert "required_steps_completed" in _columns_by_name(postgres_at_head, "workflow_runs")

    with postgres_at_head.connect() as conn:
        from sqlalchemy import text

        product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar_one()
    assert product_count == 1
    assert ids["product_id"] is not None

    command.upgrade(cfg, "head")
    tables = set(inspect(postgres_at_head).get_table_names())
    assert "run_confirmations" in tables
    assert "action_card_approvals" in tables


@requires_postgres
def test_action_card_approval_survives_action_card_change(postgres_at_head: Engine):
    """The deciding constraint: the audit snapshot must survive the
    ActionCard it describes later changing -- proven by mutating the card
    after the approval row is written and asserting the snapshot is
    unaffected."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        user, shop = _seed_shop_and_user(session)
        card = m.ActionCard(
            shop_id=shop.id,
            workflow_key="optimize_product_price",
            priority=1,
            severity="medium",
            title="Original title",
            description="Original description",
        )
        session.add(card)
        session.flush()

        snapshot = {"title": card.title, "description": card.description, "status": card.status}
        approval = m.ActionCardApproval(
            action_card_id=card.id,
            approved_by_user_id=user.id,
            card_snapshot=snapshot,
        )
        session.add(approval)
        session.commit()

        card.title = "Mutated title"
        card.status = "approved"
        session.commit()

        session.refresh(approval)
        assert approval.card_snapshot["title"] == "Original title"
        assert approval.card_snapshot["status"] == "active"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
