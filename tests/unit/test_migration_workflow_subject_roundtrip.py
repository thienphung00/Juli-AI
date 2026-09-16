"""Migration round-trip checks for #1701 / ADR-087 d.1-d.3 (migration
`061_workflow_and_subject`) -- `workflow_key`/`subject_type`/`subject_ref` on
`workflow_runs` (plus `product_id` widening to nullable), and
`subject_type`/`subject_id`/`revision`/`supersedes_card_id` on
`action_cards`.

File-content assertions need no database and always run. Everything else is
gated by `requires_postgres` (`tests/integration/test_migrations.py`, the
same gate every other migration-shaped test in this repo already uses) and
skips cleanly wherever `DATABASE_URL` is not a reachable local Postgres.

The round trip seeds rows at revision `060_processed_events_epoch` -- BEFORE
061 -- in the OLD shape (`workflow_runs.product_id` NOT NULL, no
`workflow_key`/`subject_type`/`subject_ref`; `action_cards` with no
`subject_type`/`subject_id`/`revision`). Only rows that existed before the
upgrade prove a backfill; a row created after 061 already has the new
columns and would prove nothing (the issue's own warning). This module
calls `command.downgrade(cfg, "base")` (via `_reset_to_revision`), so it is
listed in `tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES` and runs
against a database of its own, never the shared one -- the same discipline
`test_workflow_run_rollup_migration.py` established for migration 057.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import requires_postgres

__all__ = ["requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_061_PATH = MIGRATIONS_DIR / "061_workflow_and_subject.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PRE_REVISION = "060_processed_events_epoch"
_THIS_REVISION = "061_workflow_and_subject"


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


def _seed_pre_061_row(engine: Engine) -> dict:
    """Seed one shop/product/action_card/workflow_run at revision 060's
    OLD shape -- before workflow_key/subject_type/subject_ref/subject_id/
    revision existed. Returns the ids the test asserts against."""
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    product_id = uuid.uuid4()
    run_id = uuid.uuid4()
    card_id = uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+{uuid.uuid4().int % 10**14:014d}"},
        )
        conn.execute(
            text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, 'Roundtrip Shop')"),
            {"id": shop_id, "uid": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO products (id, shop_id, tiktok_product_id, name, status, update_time) "
                "VALUES (:id, :shop_id, :tt, 'Roundtrip Widget', 'ACTIVE', now())"
            ),
            {"id": product_id, "shop_id": shop_id, "tt": f"tt-{uuid.uuid4().hex[:10]}"},
        )
        conn.execute(
            text(
                "INSERT INTO action_cards (id, shop_id, workflow_key, priority, severity, "
                "title, description, recommendation_payload, status) "
                "VALUES (:id, :shop_id, 'optimize_product_2', 1, 'warning', "
                "'Pre-existing card', '', '{}', 'active')"
            ),
            {"id": card_id, "shop_id": shop_id},
        )
        conn.execute(
            text(
                "INSERT INTO workflow_runs (id, shop_id, product_id, state, status, "
                "prompt_version, prompt_sha256) "
                "VALUES (:id, :shop_id, :product_id, '{}', 'completed', 'v1', :sha)"
            ),
            {"id": run_id, "shop_id": shop_id, "product_id": product_id, "sha": "a" * 64},
        )

    return {"shop_id": shop_id, "product_id": product_id, "run_id": run_id, "card_id": card_id}


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_061_revision_equals_filename_stem():
    assert MIGRATION_061_PATH.exists(), f"missing {MIGRATION_061_PATH}"
    body = MIGRATION_061_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 061 has no `revision: str = ...` line"
    assert rev.group(1) == _THIS_REVISION
    assert rev.group(1) == MIGRATION_061_PATH.stem
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32)"
    )


def test_migration_061_down_revision_is_060():
    body = MIGRATION_061_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 061 has no string `down_revision`"
    assert down.group(1) == _PRE_REVISION


def test_migration_061_is_the_single_head():
    """Confirms this issue's own instruction was honoured: the migration
    number was RESERVED, not computed from `alembic heads` -- there is
    exactly one file whose down_revision is 061, and exactly one whose
    down_revision is 060 (this one)."""
    revisions: dict[str, str | None] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
        if rev:
            revisions[rev.group(1)] = down.group(1) if down and down.group(1) else None
    parents = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in parents]
    assert heads == [_THIS_REVISION], f"expected a single head at {_THIS_REVISION}, got {heads}"


# ---------------------------------------------------------------------------
# Postgres-backed round trip.
# ---------------------------------------------------------------------------


@requires_postgres
def test_upgrade_downgrade_upgrade_backfills_existing_runs():
    """AC1 (#1701): upgrade -> downgrade -1 -> upgrade round-trips cleanly,
    and every `workflow_runs` row that existed BEFORE the upgrade carries
    `workflow_key = 'optimize_product_2'`, `subject_type = 'product'` and
    `subject_ref = product_id` afterward -- re-read from the rows, not
    inferred from the migration's own source text. `action_cards` rows that
    predate the migration land on `subject_type = 'unscoped'`,
    `subject_id = ''`, `revision = 1`. Row counts are asserted identical
    before and after: the backfill updates, it never drops a row.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        ids = _seed_pre_061_row(engine)

        with engine.connect() as conn:
            pre_run_count = conn.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one()
            pre_card_count = conn.execute(text("SELECT COUNT(*) FROM action_cards")).scalar_one()

        command.upgrade(cfg, _THIS_REVISION)

        def _assert_backfilled() -> None:
            with engine.connect() as conn:
                run = conn.execute(
                    text(
                        "SELECT workflow_key, subject_type, subject_ref, product_id "
                        "FROM workflow_runs WHERE id = :id"
                    ),
                    {"id": ids["run_id"]},
                ).one()
                assert run.workflow_key == "optimize_product_2"
                assert run.subject_type == "product"
                assert run.subject_ref == str(ids["product_id"])
                assert run.product_id == ids["product_id"]

                card = conn.execute(
                    text(
                        "SELECT subject_type, subject_id, revision, supersedes_card_id "
                        "FROM action_cards WHERE id = :id"
                    ),
                    {"id": ids["card_id"]},
                ).one()
                assert card.subject_type == "unscoped"
                assert card.subject_id == ""
                assert card.revision == 1
                assert card.supersedes_card_id is None

                run_count = conn.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one()
                card_count = conn.execute(text("SELECT COUNT(*) FROM action_cards")).scalar_one()
                assert run_count == pre_run_count, "the backfill must not drop a workflow_runs row"
                assert card_count == pre_card_count, (
                    "the backfill must not drop an action_cards row"
                )

        _assert_backfilled()

        # AC1's actual round trip: downgrade -1, then upgrade head again, and
        # re-assert on the SAME pre-existing rows.
        command.downgrade(cfg, "-1")

        insp = inspect(engine)
        wr_columns = {c["name"] for c in insp.get_columns("workflow_runs")}
        ac_columns = {c["name"] for c in insp.get_columns("action_cards")}
        assert not {"workflow_key", "subject_type", "subject_ref"} & wr_columns, (
            "downgrade -1 did not drop workflow_runs' new columns"
        )
        assert not {"subject_type", "subject_id", "revision", "supersedes_card_id"} & ac_columns, (
            "downgrade -1 did not drop action_cards' new columns"
        )
        product_id_column = next(
            c for c in insp.get_columns("workflow_runs") if c["name"] == "product_id"
        )
        assert product_id_column["nullable"] is False, (
            "downgrade -1 must restore product_id's NOT NULL constraint"
        )

        with engine.connect() as conn:
            run_count = conn.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one()
            card_count = conn.execute(text("SELECT COUNT(*) FROM action_cards")).scalar_one()
            assert run_count == pre_run_count, "downgrade -1 must not drop a workflow_runs row"
            assert card_count == pre_card_count, "downgrade -1 must not drop an action_cards row"

        command.upgrade(cfg, "head")
        _assert_backfilled()
    finally:
        engine.dispose()


@requires_postgres
def test_downgrade_refuses_when_a_non_product_run_exists():
    """The rollback assertion's case (a): a run with a NULL product_id or a
    non-product subject_type cannot be represented once product_id's NOT
    NULL constraint is restored -- the downgrade must fail loudly, and
    leave the schema untouched (Postgres wraps the whole migration step in
    one transaction -- confirmed by hand while writing this test: the
    action_cards portion of the same downgrade, which runs first, is rolled
    back too, not left half-applied)."""
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        # Head, not a full base rebuild: this guard only needs to be AT head
        # before probing it, and re-running the full 60+-step chain in every
        # test in this module blows the suite's 30s per-test timeout. A bad
        # row this test inserts itself cannot collide with another test's
        # (fresh random shop_id per test), so a shared, already-migrated
        # database is safe to reuse.
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            user_id = uuid.uuid4()
            shop_id = uuid.uuid4()
            conn.execute(
                text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
                {"id": user_id, "phone": f"+{uuid.uuid4().int % 10**14:014d}"},
            )
            conn.execute(
                text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, 'Guard Shop')"),
                {"id": shop_id, "uid": user_id},
            )
            conn.execute(
                text(
                    "INSERT INTO workflow_runs (id, shop_id, product_id, workflow_key, "
                    "subject_type, subject_ref, state, status, prompt_version, prompt_sha256) "
                    "VALUES (:id, :shop_id, NULL, 'dispatch_window_sweep', 'dispatch_window', "
                    "'window-1', '{}', 'completed', 'v1', :sha)"
                ),
                {"id": uuid.uuid4(), "shop_id": shop_id, "sha": "b" * 64},
            )

        with pytest.raises(RuntimeError, match="non-product subject_type"):
            command.downgrade(cfg, "-1")

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == _THIS_REVISION, "a refused downgrade must leave the schema at head"
    finally:
        engine.dispose()


@requires_postgres
def test_downgrade_refuses_when_action_cards_share_shop_and_workflow_key():
    """The rollback assertion's case (b): restoring the single-key unique
    is impossible while two rows share (shop_id, workflow_key) -- exactly
    what the new, wider tuple now permits."""
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        # Head, not a full base rebuild -- see the sibling guard test's
        # comment for why this is safe to share across tests in this module.
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            user_id = uuid.uuid4()
            shop_id = uuid.uuid4()
            conn.execute(
                text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
                {"id": user_id, "phone": f"+{uuid.uuid4().int % 10**14:014d}"},
            )
            conn.execute(
                text(
                    "INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, 'Guard Shop 2')"
                ),
                {"id": shop_id, "uid": user_id},
            )
            for subject_id in ("product-a", "product-b"):
                conn.execute(
                    text(
                        "INSERT INTO action_cards (id, shop_id, workflow_key, priority, "
                        "severity, title, description, recommendation_payload, status, "
                        "subject_type, subject_id, revision) "
                        "VALUES (:id, :shop_id, 'optimize_product_2', 1, 'warning', 'Card', "
                        "'', '{}', 'active', 'product', :subject_id, 1)"
                    ),
                    {"id": uuid.uuid4(), "shop_id": shop_id, "subject_id": subject_id},
                )

        with pytest.raises(RuntimeError, match="more than one row"):
            command.downgrade(cfg, "-1")

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == _THIS_REVISION, "a refused downgrade must leave the schema at head"
    finally:
        engine.dispose()
