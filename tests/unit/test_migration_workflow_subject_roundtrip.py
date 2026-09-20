"""Migration round-trip checks for #1701 / ADR-087 d.1-d.3 (migration
`062_workflow_and_subject`) -- `workflow_key`/`subject_type`/`subject_ref` on
`workflow_runs` (plus `product_id` widening to nullable), and
`subject_type`/`subject_id`/`revision`/`supersedes_card_id` on
`action_cards`.

File-content assertions need no database and always run. Everything else is
gated by `requires_postgres` (`tests/integration/test_migrations.py`, the
same gate every other migration-shaped test in this repo already uses) and
skips cleanly wherever `DATABASE_URL` is not a reachable local Postgres.

#2050 split 062 into an expand step and a contract step, so this module now
asserts BOTH halves and the boundary between them. `subject_ref` arrives
NULLABLE and un-backfilled in 062 (the additive-only release gate refuses a
per-row `UPDATE` and a `SET NOT NULL` during a release, and refused every
release from 2026-09-16 until the split); the backfill and the narrowing live
in `063_workflow_subject_contract`, which was parked OUTSIDE `versions/` and
run by hand against production on 2026-09-20T12:06Z, then promoted into
`versions/` by #2057 now that it is applied and no longer pending. This
module applies that file's `upgrade()`/`downgrade()` directly, through
Alembic's own `Operations` context, against a connection this module controls
-- rather than driving it via `command.upgrade(cfg, "head")` -- because the
round trip below needs fine-grained control over exactly when the contract
step runs (after the expand step's NULLABLE assertion, and again after
`command.downgrade(cfg, "-1")`), independent of wherever the file happens to
sit in the chain today.

The round trip seeds rows at revision `061_credential_owner_enum` -- BEFORE
062, and the migration immediately below 062 on `main` (#1701's migration was
renumbered 061->062 when #2019's 061_credential_owner_enumeration.py merged
first and took the reserved number -- see 062_workflow_and_subject.py's own
docstring) -- in the OLD shape (`workflow_runs.product_id` NOT NULL, no
`workflow_key`/`subject_type`/`subject_ref`; `action_cards` with no
`subject_type`/`subject_id`/`revision`). Only rows that existed before the
upgrade prove a backfill; a row created after 062 already has the new
columns and would prove nothing (the issue's own warning). This module
calls `command.downgrade(cfg, "base")` (via `_reset_to_revision`), so it is
listed in `tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES` and runs
against a database of its own, never the shared one -- the same discipline
`test_workflow_run_rollup_migration.py` established for migration 057.
"""

from __future__ import annotations

import importlib.util
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import requires_postgres

__all__ = ["requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_062_PATH = MIGRATIONS_DIR / "062_workflow_and_subject.py"
# #2057 promoted 063 from deferred/ into versions/ once it was applied in
# production -- it is a normal chain member now, alongside 062.
CONTRACT_063_PATH = MIGRATIONS_DIR / "063_workflow_subject_contract.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PRE_REVISION = "061_credential_owner_enum"
_THIS_REVISION = "062_workflow_and_subject"


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


def _run_deferred_contract(engine: Engine, direction: str = "upgrade") -> None:
    """Execute `063_workflow_subject_contract`'s real `upgrade()`/`downgrade()`.

    #2057 promoted the file into `versions/`, so `command.upgrade(cfg, "head")`
    could reach it directly now -- but this test still loads the module and
    drives it through Alembic's own `Operations` context by hand, against a
    connection this test controls, because the round trip below needs the
    expand step's NULLABLE state asserted BEFORE the contract step runs and
    again AFTER `command.downgrade(cfg, "-1")`, independent of whichever
    revision `command.upgrade`/`command.downgrade` would otherwise land the
    chain on. It runs the SAME statements the operator ran by hand in
    production, with no reimplementation of the SQL here. `alembic_version` is
    intentionally NOT stamped by this helper: this test drives `command.*`
    against `_THIS_REVISION` (062) elsewhere in the same run, and stamping
    here out of band would desynchronize that from what `alembic_version`
    actually says.
    """
    spec = importlib.util.spec_from_file_location(
        "deferred_063_workflow_subject_contract", CONTRACT_063_PATH
    )
    assert spec is not None and spec.loader is not None, f"cannot load {CONTRACT_063_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            getattr(module, direction)()


def _subject_ref_is_nullable(engine: Engine) -> bool:
    column = next(
        c for c in inspect(engine).get_columns("workflow_runs") if c["name"] == "subject_ref"
    )
    return bool(column["nullable"])


def _seed_pre_062_row(engine: Engine) -> dict:
    """Seed one shop/product/action_card/workflow_run at revision
    061_credential_owner_enum's OLD shape -- before
    workflow_key/subject_type/subject_ref/subject_id/revision existed.
    Returns the ids the test asserts against."""
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


def test_migration_062_revision_equals_filename_stem():
    assert MIGRATION_062_PATH.exists(), f"missing {MIGRATION_062_PATH}"
    body = MIGRATION_062_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 062 has no `revision: str = ...` line"
    assert rev.group(1) == _THIS_REVISION
    assert rev.group(1) == MIGRATION_062_PATH.stem
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32)"
    )


def test_migration_062_down_revision_is_061_credential_owner_enum():
    body = MIGRATION_062_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 062 has no string `down_revision`"
    assert down.group(1) == _PRE_REVISION


def test_migration_062_has_exactly_one_child_and_it_is_063():
    """Confirms this issue's own instruction was honoured: the migration
    number was RESERVED, not computed from `alembic heads` -- there is
    exactly one file whose down_revision is 062, and exactly one whose
    down_revision is 061_credential_owner_enum (this one). 061 itself was
    independently reserved twice (#1701 and #2019); #2019 merged first and
    kept 061, so this migration is 062, chained onto 061_credential_owner_enum,
    not the 060 it was originally reserved against.

    Originally asserted that 062 was the single head of `versions/` -- true
    only while 063 was parked in `deferred/` (#2050). #2057 promoted 063 into
    `versions/` once it was applied in production, so 062 now has exactly one
    child (063) rather than none; this asserts THAT instead of a specific
    global head, since a later migration may chain onto 063 without this
    test needing to change again."""
    revisions: dict[str, str | None] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
        if rev:
            revisions[rev.group(1)] = down.group(1) if down and down.group(1) else None
    children_of_062 = sorted(r for r, d in revisions.items() if d == _THIS_REVISION)
    assert children_of_062 == [CONTRACT_063_PATH.stem], (
        f"expected 062's only child to be {CONTRACT_063_PATH.stem}, got {children_of_062} -- "
        "a second child means a migration number was reserved twice"
    )
    children_of_061 = sorted(r for r, d in revisions.items() if d == _PRE_REVISION)
    assert children_of_061 == [_THIS_REVISION], (
        f"expected 061's only child to be {_THIS_REVISION}, got {children_of_061}"
    )


# ---------------------------------------------------------------------------
# Postgres-backed round trip.
# ---------------------------------------------------------------------------


@requires_postgres
def test_expand_step_adds_the_columns_and_the_contract_step_backfills_them():
    """AC1 (#1701) as re-split by #2050: upgrade -> downgrade -1 -> upgrade
    round-trips cleanly, and the expand/contract boundary lands where the
    additive-only gate requires it.

    After the EXPAND step (062, the only revision in the Alembic chain), every
    `workflow_runs` row that existed before it carries
    `workflow_key = 'optimize_product_2'` and `subject_type = 'product'` from
    their constant server defaults -- and `subject_ref` is NULL, on a NULLABLE
    column. That NULL is asserted, not tolerated: it is the property that makes
    062 additive, so a future edit that quietly re-adds the backfill fails here
    as well as at the gate.

    After the CONTRACT step (063, run by hand from `deferred/`), the same row's
    `subject_ref` equals its own `product_id` and the column is NOT NULL --
    re-read from the rows, not inferred from either migration's source text.

    `action_cards` rows that predate the migration land on
    `subject_type = 'unscoped'`, `subject_id = ''`, `revision = 1` at the
    expand step; the contract step does not touch that table. Row counts are
    asserted identical throughout: the backfill updates, it never drops a row.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        ids = _seed_pre_062_row(engine)

        with engine.connect() as conn:
            pre_run_count = conn.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one()
            pre_card_count = conn.execute(text("SELECT COUNT(*) FROM action_cards")).scalar_one()

        command.upgrade(cfg, _THIS_REVISION)

        def _assert_row_counts_held(conn) -> None:
            run_count = conn.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one()
            card_count = conn.execute(text("SELECT COUNT(*) FROM action_cards")).scalar_one()
            assert run_count == pre_run_count, "the migration must not drop a workflow_runs row"
            assert card_count == pre_card_count, "the migration must not drop an action_cards row"

        def _assert_expanded(*, subject_ref_still_unset: bool) -> None:
            """The expand step's truth: columns present, constant defaults
            applied, `subject_ref` on a NULLABLE column.

            `subject_ref_still_unset` is False only when the contract step has
            already run and been rolled back. 063's downgrade reopens the
            column and deliberately does NOT un-backfill -- the backfilled
            values are the correct ones and erasing them would destroy
            information -- so the row keeps its subject there. Nullability is
            the property that decides whether the release gate passes; the
            value is not.
            """
            assert _subject_ref_is_nullable(engine), (
                "062 is the EXPAND step -- subject_ref must stay nullable until the "
                "contract step runs, or the additive-only gate refuses the release"
            )
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
                if subject_ref_still_unset:
                    assert run.subject_ref is None, (
                        "the expand step must NOT backfill subject_ref -- a per-row "
                        "UPDATE is exactly what the additive-only gate refuses"
                    )
                else:
                    assert run.subject_ref == str(ids["product_id"]), (
                        "063's downgrade must reopen the column without erasing the "
                        "subject it backfilled"
                    )
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

                _assert_row_counts_held(conn)

        def _assert_contracted() -> None:
            """The contract step's truth: the same pre-existing row now carries
            its own product_id as its subject, and the column is closed."""
            assert not _subject_ref_is_nullable(engine), (
                "the contract step must narrow subject_ref to NOT NULL"
            )
            with engine.connect() as conn:
                run = conn.execute(
                    text("SELECT subject_ref, product_id FROM workflow_runs WHERE id = :id"),
                    {"id": ids["run_id"]},
                ).one()
                assert run.subject_ref == str(ids["product_id"])
                assert run.product_id == ids["product_id"]
                _assert_row_counts_held(conn)

        _assert_expanded(subject_ref_still_unset=True)
        _run_deferred_contract(engine, "upgrade")
        _assert_contracted()

        # Back to the expand-step shape before exercising the chain's own
        # downgrade: 062 is what `alembic_version` still records, and the
        # operator's rollback of a hand-run contract step is 063's downgrade.
        _run_deferred_contract(engine, "downgrade")
        _assert_expanded(subject_ref_still_unset=False)

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

        # 062, not "head": #2057 promoted 063 into versions/, so `command.upgrade`
        # reaching "head" now would run 063's real upgrade() through Alembic's
        # own engine too (it is a normal chain member now) and land already
        # contracted -- one step past the EXPAND state this line means to
        # reassert before driving the contract step by hand again below.
        command.upgrade(cfg, _THIS_REVISION)
        _assert_expanded(subject_ref_still_unset=True)
        _run_deferred_contract(engine, "upgrade")
        _assert_contracted()
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
        # Land exactly on 062, not "head": the guard under test lives in
        # 062's own downgrade(), and #2057 promoted 063 into the chain right
        # above it, so "head" now means 063 and `downgrade(cfg, "-1")` from
        # there would run 063's downgrade (reopen subject_ref nullable) --
        # one step short of the guard this test means to probe. Upgrading to
        # head and then downgrading to 062 by name (rather than "-1")
        # reproduces the original "at 062, one -1 away from the guard" setup
        # regardless of what chains onto 062 later, and regardless of
        # whichever revision a prior test in this module left the shared
        # database at. A bad row this test inserts itself cannot collide with
        # another test's (fresh random shop_id per test), so a shared,
        # already-migrated database is safe to reuse.
        command.upgrade(cfg, "head")
        command.downgrade(cfg, _THIS_REVISION)
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
        assert version == _THIS_REVISION, "a refused downgrade must leave the schema at 062"
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
        # 062, not "head" -- see the sibling guard test's comment for why
        # (the guard under test lives in 062's downgrade, and #2057 put 063
        # one step above it in the chain) and for why this is safe to share
        # across tests in this module.
        command.upgrade(cfg, "head")
        command.downgrade(cfg, _THIS_REVISION)
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
        assert version == _THIS_REVISION, "a refused downgrade must leave the schema at 062"
    finally:
        engine.dispose()
