"""Migration round-trip and tenant-isolation checks for #1712 (migration
`069_act_records_and_checklists`) -- `run_act_records` and
`run_checklist_items`.

#1712 is a **schema-only** slice: the two tables ship with no reader and no
writer, and #1713 adds the producer. That makes the usual "exercise the
repository" verification unavailable, and makes this module the whole of the
evidence. So it is deliberately not a file-content test with a Postgres
afterthought: every claim the issue's acceptance criteria make is a claim about
PostgreSQL behaviour -- RLS denial, `CHECK` constraints, a composite foreign
key, a partial/expression index -- and none of them are observable against the
SQLite fixture `tests/unit/conftest.py` builds from `Base.metadata`. Asserting
them there would prove only that the test agrees with itself.

Shape follows `tests/unit/test_migration_workflow_subject_roundtrip.py`, the
repo's exemplar: seed rows at the PRIOR revision, apply the migration, assert
the new shape, then `downgrade -1` -> `upgrade` and re-assert against the
*same* pre-existing rows, holding row counts constant throughout. Only rows
that existed before the upgrade can prove a migration left them alone; a row
created afterwards proves nothing.

For a create-table migration the round trip has one honest difference from
062's. 062 added columns, so its own rows survived the trip. 069 creates
tables, and `downgrade -1` drops them -- so what must be held constant is the
*pre-existing* `shops`/`workflow_runs` rows the new tables hang off, and the
re-upgrade must be able to re-bind new records to the very same run id. A
migration that took a `workflow_runs` row with it on the way down, or left one
unusable on the way back up, is exactly the failure this catches.

File-content assertions need no database and always run. Everything else is
gated by `requires_postgres` (`tests/integration/test_migrations.py`, the same
gate every other migration-shaped test here uses) and skips cleanly wherever
`DATABASE_URL` is not a reachable local Postgres.

This module calls `command.downgrade(cfg, "base")` (via `_reset_to_revision`),
so it is listed in `tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES` and runs
against a database of its own, never the shared one.

Deliberately carries **no** `migration_heavy` marker, matching the 062 module:
that marker deselects a test from the issue-tier `test` job in `pr.yml`, and a
migration whose only proof runs on merge_group is a migration that reaches a
PR unverified.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.database.tenant_scoped_tables import (
    TABLE_CLASSIFICATION_MAP,
    get_tenant_scoped_tables,
)
from tests.integration.test_migrations import requires_postgres

__all__ = ["requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_069_PATH = MIGRATIONS_DIR / "069_act_records_and_checklists.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PRE_REVISION = "065_users_email"
_THIS_REVISION = "069_act_records_and_checklists"

ACT_RECORDS = "run_act_records"
CHECKLIST_ITEMS = "run_checklist_items"
NEW_TABLES = (ACT_RECORDS, CHECKLIST_ITEMS)

#: Exactly the five kinds #1712 names, and the four states, and the one
#: channel. Repeated here rather than imported from the migration on purpose:
#: importing would make the test agree with whatever the migration says, which
#: is not the question. These are read off the issue.
EXPECTED_KINDS = {"reminder", "digest", "automated_act", "completion", "exception"}
EXPECTED_STATES = {"pending", "delivered", "read", "failed"}
EXPECTED_CHANNELS = {"in_app"}

#: Every column #1712's "What to build" paragraph names, in the spelling that
#: survived contact with PostgreSQL. `when` is a reserved word and became
#: `occurred_at`; everything else is verbatim.
EXPECTED_ACT_COLUMNS = {
    "id",
    "shop_id",
    "workflow_run_id",
    "kind",
    "what",
    "occurred_at",
    "why",
    "otherwise",
    "undo_hint",
    "state",
    "channel",
    "created_at",
    "updated_at",
}
EXPECTED_CHECKLIST_COLUMNS = {
    "id",
    "shop_id",
    "workflow_run_id",
    "key",
    "text",
    "done",
    "done_at",
    "edited_by_seller",
    "position",
    "created_at",
    "updated_at",
}


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
    """Refuse to downgrade against anything but a local, disposable Postgres --
    issue #734's discipline, reproduced here rather than importing a private
    helper from another test module."""
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


def _seed_pre_069_rows(engine: Engine) -> dict:
    """Seed two independent tenants at `065_users_email`'s shape -- before
    either new table existed.

    Two shops, not one: every isolation claim below is "shop A's session sees
    A's rows and not B's", and a single-tenant fixture can only ever show the
    first half, which a policy that returns everything would also satisfy.
    """
    seeded: dict = {}
    with engine.begin() as conn:
        for label in ("a", "b"):
            user_id = uuid.uuid4()
            shop_id = uuid.uuid4()
            product_id = uuid.uuid4()
            run_id = uuid.uuid4()
            conn.execute(
                text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
                {"id": user_id, "phone": f"+{uuid.uuid4().int % 10**14:014d}"},
            )
            conn.execute(
                text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
                {"id": shop_id, "uid": user_id, "name": f"Act Records Shop {label.upper()}"},
            )
            conn.execute(
                text(
                    "INSERT INTO products "
                    "(id, shop_id, tiktok_product_id, name, status, update_time) "
                    "VALUES (:id, :shop_id, :tt, 'Act Records Widget', 'ACTIVE', now())"
                ),
                {"id": product_id, "shop_id": shop_id, "tt": f"tt-{uuid.uuid4().hex[:10]}"},
            )
            conn.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(id, shop_id, product_id, subject_ref, state, status, "
                    " prompt_version, prompt_sha256) "
                    "VALUES (:id, :shop_id, :product_id, :subject_ref, '{}', 'completed', "
                    " 'v1', :sha)"
                ),
                {
                    "id": run_id,
                    "shop_id": shop_id,
                    "product_id": product_id,
                    "subject_ref": str(product_id),
                    "sha": "a" * 64,
                },
            )
            seeded[label] = {"shop_id": shop_id, "product_id": product_id, "run_id": run_id}
    return seeded


def _insert_act_record(conn, tenant: dict, *, kind: str = "reminder") -> uuid.UUID:
    record_id = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {ACT_RECORDS} "  # noqa: S608 - fixed module constant
            "(id, shop_id, workflow_run_id, kind, what, occurred_at, why) "
            "VALUES (:id, :shop_id, :run_id, :kind, 'Reminded the seller', now(), "
            "'the clearance window closes tomorrow')"
        ),
        {
            "id": record_id,
            "shop_id": tenant["shop_id"],
            "run_id": tenant["run_id"],
            "kind": kind,
        },
    )
    return record_id


def _insert_checklist_item(conn, tenant: dict, *, key: str = "place_the_order", position: int = 0):
    item_id = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {CHECKLIST_ITEMS} "  # noqa: S608 - fixed module constant
            "(id, shop_id, workflow_run_id, key, text, position) "
            "VALUES (:id, :shop_id, :run_id, :key, 'Place the supplier order', :position)"
        ),
        {
            "id": item_id,
            "shop_id": tenant["shop_id"],
            "run_id": tenant["run_id"],
            "key": key,
            "position": position,
        },
    )
    return item_id


def _read_revision_ids(path: Path) -> tuple[str | None, str | None]:
    body = path.read_text(encoding="utf-8")
    revision = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
    return (
        revision.group(1) if revision else None,
        down.group(1) if down and down.group(1) else None,
    )


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_069_revision_equals_filename_stem() -> None:
    assert MIGRATION_069_PATH.exists(), f"missing {MIGRATION_069_PATH}"
    revision, _ = _read_revision_ids(MIGRATION_069_PATH)
    assert revision == _THIS_REVISION
    assert revision == MIGRATION_069_PATH.stem
    assert revision is not None and len(revision) <= 32, (
        f"revision id {revision!r} is {len(revision or '')} chars -- "
        "alembic_version.version_num is VARCHAR(32), so a longer id fails only "
        "at upgrade time, against a real database"
    )


def test_migration_069_chains_onto_the_versions_tail_and_is_the_only_child() -> None:
    """The number was RESERVED (069), the parent is whatever `versions/` head
    actually exists on this branch, and nothing else claims that parent.

    A second child of one revision is how this repo forked its Alembic chain
    before: 061 was reserved twice, by #1701 and #2019, and the loser had to
    renumber to 062. That is the defect this asserts against -- not the number.
    """
    _, down_revision = _read_revision_ids(MIGRATION_069_PATH)
    assert down_revision == _PRE_REVISION

    revisions: dict[str, str | None] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        revision, down = _read_revision_ids(path)
        if revision:
            revisions[revision] = down

    siblings = sorted(r for r, d in revisions.items() if d == _PRE_REVISION)
    assert siblings == [_THIS_REVISION], (
        f"expected {_PRE_REVISION}'s only child in versions/ to be {_THIS_REVISION}, "
        f"got {siblings} -- a second child means a migration number was reserved twice"
    )
    children = sorted(r for r, d in revisions.items() if d == _THIS_REVISION)
    assert children == [], (
        f"{children} chains onto {_THIS_REVISION}; update _PRE_REVISION here and "
        "re-check the deferred step is still the tail"
    )


def test_both_new_tables_are_classified_tenant_scoped() -> None:
    """Acceptance criterion 1: "listed in the tenant-scoped table set".

    `tenant_direct` rather than `tenant_via_parent` because each row carries
    its own `shop_id` -- the same shape `tool_executions` has had since
    migration 034, and the reason the RLS policies can compare a column
    instead of joining to the parent on the seller's hot path.

    A classification entry is not self-executing: the #1329 isolation proof
    enumerates every table with a `shop_id` out of `pg_catalog` and FAILS on
    any it cannot find in this map, which is exactly how migration 045 was
    caught having missed two tables.
    """
    tenant_scoped = set(get_tenant_scoped_tables())
    for table in NEW_TABLES:
        assert TABLE_CLASSIFICATION_MAP.get(("public", table)) == "tenant_direct", (
            f"public.{table} is not classified tenant_direct; the #1329 isolation "
            "proof enumerates every table with a shop_id out of pg_catalog and "
            "fails on any it cannot find in the map"
        )
        assert ("public", table) in tenant_scoped


def test_the_migration_satisfies_the_additive_release_gate() -> None:
    """Two new tables are additive, so an automatic release must accept them.

    `infra/scripts/migration_additive_gate.py` refuses a pending revision that
    is destructive or data-moving, and a refusal here would mean
    `deploy_lane_api` returns before any candidate starts -- the #2050
    deadlock. The gate reads `upgrade()`; this migration's `drop_table`s live
    in `downgrade()`, which is the only place they may live.
    """
    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_069_PATH])
    assert result.accepted, result.report()


# ---------------------------------------------------------------------------
# Postgres-backed round trip.
# ---------------------------------------------------------------------------


@requires_postgres
def test_upgrade_downgrade_roundtrip() -> None:
    """#1712 acceptance criterion 1, plus the rollback its release-evidence
    section promises ("`downgrade -1` drops both tables; safe while no writer
    exists").

    Seeds at 065, upgrades, asserts the shape and the constraints against real
    PostgreSQL, then `downgrade -1` -> `upgrade` and re-asserts against the
    SAME seeded `shops`/`workflow_runs` rows, holding their counts constant at
    every step.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        seeded = _seed_pre_069_rows(engine)
        tenant_a = seeded["a"]

        with engine.connect() as conn:
            pre_shop_count = conn.execute(text("SELECT COUNT(*) FROM shops")).scalar_one()
            pre_run_count = conn.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one()

        def _assert_pre_existing_rows_held() -> None:
            with engine.connect() as conn:
                shops = conn.execute(text("SELECT COUNT(*) FROM shops")).scalar_one()
                runs = conn.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one()
                assert shops == pre_shop_count, "a shops row was lost"
                assert runs == pre_run_count, "a workflow_runs row was lost"
                still_there = conn.execute(
                    text("SELECT shop_id FROM workflow_runs WHERE id = :id"),
                    {"id": tenant_a["run_id"]},
                ).scalar_one()
                assert still_there == tenant_a["shop_id"], (
                    "the seeded run changed shop, or vanished"
                )

        def _assert_tables_absent() -> None:
            names = set(inspect(engine).get_table_names())
            assert not (set(NEW_TABLES) & names), (
                f"downgrade -1 left {sorted(set(NEW_TABLES) & names)} behind"
            )

        def _assert_tables_present_with_the_specified_shape() -> None:
            insp = inspect(engine)
            names = set(insp.get_table_names())
            assert set(NEW_TABLES) <= names, (
                f"missing {sorted(set(NEW_TABLES) - names)} after upgrade"
            )
            act_columns = {c["name"] for c in insp.get_columns(ACT_RECORDS)}
            assert act_columns == EXPECTED_ACT_COLUMNS, (
                f"{ACT_RECORDS} columns are {sorted(act_columns)}, expected "
                f"{sorted(EXPECTED_ACT_COLUMNS)}"
            )
            checklist_columns = {c["name"] for c in insp.get_columns(CHECKLIST_ITEMS)}
            assert checklist_columns == EXPECTED_CHECKLIST_COLUMNS, (
                f"{CHECKLIST_ITEMS} columns are {sorted(checklist_columns)}, expected "
                f"{sorted(EXPECTED_CHECKLIST_COLUMNS)}"
            )
            # Nullable exactly where the issue leaves room for "no counterfactual"
            # and "nothing to undo"; NOT NULL everywhere the record is meaningless
            # without it.
            nullable = {c["name"]: c["nullable"] for c in insp.get_columns(ACT_RECORDS)}
            assert nullable["otherwise"] is True
            assert nullable["undo_hint"] is True
            for required in ("shop_id", "workflow_run_id", "kind", "what", "occurred_at", "why"):
                assert nullable[required] is False, f"{required} must be NOT NULL"

        def _assert_a_record_round_trips() -> None:
            """Writing and reading one row of each table, bound to the seeded
            run -- the tables are useless if the FK they carry cannot be
            satisfied by a run that already existed."""
            with engine.begin() as conn:
                record_id = _insert_act_record(conn, tenant_a)
                item_id = _insert_checklist_item(conn, tenant_a)
            with engine.connect() as conn:
                row = conn.execute(
                    text(  # noqa: S608 - fixed module constant
                        f"SELECT state, channel, otherwise, undo_hint FROM {ACT_RECORDS} "
                        "WHERE id = :id"
                    ),
                    {"id": record_id},
                ).one()
                assert row.state == "pending", "a new record is born pending"
                assert row.channel == "in_app", "v1 has no transport but the app"
                assert row.otherwise is None and row.undo_hint is None
                item = conn.execute(
                    text(  # noqa: S608 - fixed module constant
                        f"SELECT done, done_at, edited_by_seller, position "
                        f"FROM {CHECKLIST_ITEMS} WHERE id = :id"
                    ),
                    {"id": item_id},
                ).one()
                assert item.done is False and item.done_at is None
                assert item.edited_by_seller is False
                assert item.position == 0

        _assert_tables_absent()
        command.upgrade(cfg, _THIS_REVISION)
        _assert_tables_present_with_the_specified_shape()
        _assert_pre_existing_rows_held()
        _assert_a_record_round_trips()

        command.downgrade(cfg, "-1")
        _assert_tables_absent()
        _assert_pre_existing_rows_held()

        command.upgrade(cfg, _THIS_REVISION)
        _assert_tables_present_with_the_specified_shape()
        _assert_pre_existing_rows_held()
        # Against the SAME pre-existing run, after the full trip.
        _assert_a_record_round_trips()
    finally:
        engine.dispose()


@requires_postgres
def test_tables_are_tenant_isolated() -> None:
    """#1712 acceptance criterion 2: the runtime role reading either table
    without tenant context sees zero rows, per ADR-086.

    Three observations, because only the three together mean anything:

    1. As the owner, both tenants' rows are there -- so a later zero is a
       policy denying, not an empty table.
    2. As `juli_app` with **no** `app.current_shop_id`, zero rows. Not
       `permission denied`: the migration grants SELECT precisely so this
       reads as a denial by policy rather than by a missing grant.
    3. As `juli_app` scoped to shop A, exactly A's rows and none of B's.

    `SET ROLE juli_app` rather than a second connection, matching
    `tests/integration/test_two_tenant_isolation_proof.py`: `juli_app` is
    NOLOGIN by design, and RLS applies to `current_user`, which `SET ROLE`
    changes. The role is not the table owner and does not hold `BYPASSRLS`
    (ADR-086 asserts both rather than assuming them), so the policies bite.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        seeded = _seed_pre_069_rows(engine)
        command.upgrade(cfg, _THIS_REVISION)

        with engine.begin() as conn:
            _insert_act_record(conn, seeded["a"])
            _insert_act_record(conn, seeded["b"])
            _insert_checklist_item(conn, seeded["a"])
            _insert_checklist_item(conn, seeded["b"])

        def _count_as_owner(table: str) -> int:
            with engine.connect() as conn:
                return conn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - module constant
                ).scalar_one()

        def _count_as_runtime_role(table: str, shop_id: uuid.UUID | None) -> int:
            with engine.connect() as conn:
                conn.execute(text("SET ROLE juli_app"))
                if shop_id is not None:
                    conn.execute(
                        text("SELECT set_config('app.current_shop_id', :val, true)").bindparams(
                            val=str(shop_id)
                        )
                    )
                count = conn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - module constant
                ).scalar_one()
                conn.execute(text("RESET ROLE"))
                return count

        for table in NEW_TABLES:
            assert _count_as_owner(table) == 2, (
                f"{table} should hold one row per tenant before isolation is measured; "
                "a zero below would otherwise prove nothing"
            )
            assert _count_as_runtime_role(table, None) == 0, (
                f"{table} returned rows to juli_app with no app.current_shop_id set -- "
                "ADR-086 requires zero"
            )
            assert _count_as_runtime_role(table, seeded["a"]["shop_id"]) == 1, (
                f"{table} denied shop A its own row; the policy is not just denying "
                "everything, which a broken policy would also do"
            )
            assert _count_as_runtime_role(table, seeded["b"]["shop_id"]) == 1
    finally:
        engine.dispose()


@requires_postgres
def test_a_record_cannot_reference_a_run_or_a_shop_that_does_not_exist() -> None:
    """Both foreign keys bite, and `shop_id` is a real tenancy column rather
    than a free-text field.

    The stronger guarantee -- a composite FK onto `workflow_runs (id, shop_id)`
    that makes the duplicated tenancy fact un-driftable, answering ADR-085's
    objection outright -- is NOT in this migration: it requires a new unique
    constraint on `workflow_runs`, which belongs to #1701/#1706/#1707/#1709 in
    this same wave, and #1712's prepared scope forbids touching that table.
    This test therefore asserts what the schema does guarantee today, and the
    migration docstring records the composite FK as the follow-up for whoever
    next owns `workflow_runs`. `tool_executions` has carried the same
    shop_id-plus-run_id shape, with the same two independent FKs, since
    migration 034.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        seeded = _seed_pre_069_rows(engine)
        command.upgrade(cfg, _THIS_REVISION)

        unknown = {"shop_id": seeded["a"]["shop_id"], "run_id": uuid.uuid4()}
        with pytest.raises(IntegrityError, match="fk_run_act_records_run"):
            with engine.begin() as conn:
                _insert_act_record(conn, unknown)
        with pytest.raises(IntegrityError, match="fk_run_checklist_items_run"):
            with engine.begin() as conn:
                _insert_checklist_item(conn, unknown)

        orphan_shop = {"shop_id": uuid.uuid4(), "run_id": seeded["a"]["run_id"]}
        with pytest.raises(IntegrityError, match="shop_id"):
            with engine.begin() as conn:
                _insert_act_record(conn, orphan_shop)
    finally:
        engine.dispose()


@requires_postgres
def test_the_check_constraints_refuse_the_values_the_issue_excludes() -> None:
    """`kind`, `state`, `channel` and the `done`/`done_at` biconditional.

    A `CHECK` is the only thing standing between #1713's writer and a typo'd
    `kind` that no reader will ever match, and it exists only in PostgreSQL --
    the SQLite unit fixture does not enforce it, so a test that ran there would
    pass against a migration that had never written the constraint at all.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        seeded = _seed_pre_069_rows(engine)
        command.upgrade(cfg, _THIS_REVISION)
        tenant = seeded["a"]

        # Every kind the issue names is accepted...
        with engine.begin() as conn:
            for kind in sorted(EXPECTED_KINDS):
                _insert_act_record(conn, tenant, kind=kind)
        # ...and one it does not is not.
        with pytest.raises(IntegrityError, match="ck_run_act_records_kind"):
            with engine.begin() as conn:
                _insert_act_record(conn, tenant, kind="sms_blast")

        with pytest.raises(IntegrityError, match="ck_run_act_records_state"):
            with engine.begin() as conn:
                record_id = _insert_act_record(conn, tenant)
                conn.execute(
                    text(  # noqa: S608 - fixed module constant
                        f"UPDATE {ACT_RECORDS} SET state = 'snoozed' WHERE id = :id"
                    ),
                    {"id": record_id},
                )

        # v1 renders in the app and nowhere else (spec §8.1 P0-8).
        with pytest.raises(IntegrityError, match="ck_run_act_records_channel"):
            with engine.begin() as conn:
                record_id = _insert_act_record(conn, tenant)
                conn.execute(
                    text(  # noqa: S608 - fixed module constant
                        f"UPDATE {ACT_RECORDS} SET channel = 'zalo' WHERE id = :id"
                    ),
                    {"id": record_id},
                )

        # S-FR-12: "the tick time is in the ledger" -- ticked without a time
        # loses that fact, and a time without a tick describes nothing.
        with pytest.raises(IntegrityError, match="ck_run_checklist_items_done_at"):
            with engine.begin() as conn:
                item_id = _insert_checklist_item(conn, tenant)
                conn.execute(
                    text(  # noqa: S608 - fixed module constant
                        f"UPDATE {CHECKLIST_ITEMS} SET done = true WHERE id = :id"
                    ),
                    {"id": item_id},
                )
        with pytest.raises(IntegrityError, match="ck_run_checklist_items_done_at"):
            with engine.begin() as conn:
                item_id = _insert_checklist_item(conn, tenant, key="print_and_pack", position=1)
                conn.execute(
                    text(  # noqa: S608 - fixed module constant
                        f"UPDATE {CHECKLIST_ITEMS} SET done_at = now() WHERE id = :id"
                    ),
                    {"id": item_id},
                )
        # Both together is the shape a tick actually produces.
        with engine.begin() as conn:
            item_id = _insert_checklist_item(conn, tenant, key="apply_the_label", position=2)
            conn.execute(
                text(  # noqa: S608 - fixed module constant
                    f"UPDATE {CHECKLIST_ITEMS} SET done = true, done_at = now() WHERE id = :id"
                ),
                {"id": item_id},
            )
        with engine.connect() as conn:
            done_at = conn.execute(
                text(  # noqa: S608 - fixed module constant
                    f"SELECT done_at FROM {CHECKLIST_ITEMS} WHERE id = :id"
                ),
                {"id": item_id},
            ).scalar_one()
            assert done_at is not None
    finally:
        engine.dispose()


@requires_postgres
def test_a_checklist_key_and_position_are_unique_within_one_run() -> None:
    """Two runs may both have a `place_the_order` item; one run may not.

    Without this a re-delivered card, or a retried producer in #1713, silently
    doubles every item on the seller's checklist -- the failure mode the
    `processed_events` ledger exists to stop elsewhere in this codebase.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        seeded = _seed_pre_069_rows(engine)
        command.upgrade(cfg, _THIS_REVISION)

        with engine.begin() as conn:
            _insert_checklist_item(conn, seeded["a"], key="place_the_order", position=0)
            # A different run may reuse both the key and the position.
            _insert_checklist_item(conn, seeded["b"], key="place_the_order", position=0)

        with pytest.raises(IntegrityError, match="uq_run_checklist_items_run_key"):
            with engine.begin() as conn:
                _insert_checklist_item(conn, seeded["a"], key="place_the_order", position=1)
        with pytest.raises(IntegrityError, match="uq_run_checklist_items_run_position"):
            with engine.begin() as conn:
                _insert_checklist_item(conn, seeded["a"], key="print_and_pack", position=0)
        with pytest.raises(IntegrityError, match="ck_run_checklist_items_position"):
            with engine.begin() as conn:
                _insert_checklist_item(conn, seeded["a"], key="negative", position=-1)
    finally:
        engine.dispose()


@requires_postgres
def test_the_runtime_role_holds_select_and_no_write_verb_yet() -> None:
    """#1712 ships no writer, so `juli_app` gets `SELECT` and nothing else.

    SELECT is not optional: acceptance criterion 2 is a *read* returning zero
    rows, and a role with no grant would fail with `permission denied` instead
    -- a different sentence about a different defect.
    `tests/integration/test_runtime_role_grant_coverage.py` independently
    requires SELECT on every tenant-scoped table.

    INSERT/UPDATE are #1713's, together with the call site that justifies them;
    granting UPDATE here would break
    `test_no_public_table_holds_update_beyond_its_call_site`, which compares
    the live UPDATE surface for equality against a registry of real mutation
    sites.
    """
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, _PRE_REVISION)
        command.upgrade(cfg, _THIS_REVISION)
        with engine.connect() as conn:
            for table in NEW_TABLES:
                granted = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT privilege_type FROM information_schema.role_table_grants "
                            "WHERE grantee = 'juli_app' AND table_schema = 'public' "
                            "AND table_name = :table"
                        ),
                        {"table": table},
                    )
                }
                assert granted == {"SELECT"}, (
                    f"juli_app holds {sorted(granted)} on public.{table}; #1712 has no "
                    "reader and no writer, so SELECT and nothing else is the surface"
                )
    finally:
        engine.dispose()
