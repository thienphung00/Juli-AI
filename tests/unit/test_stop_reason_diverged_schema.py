"""Schema/migration checks for #1274 / AGT-W5A-DP (migration
`041_stop_reason_diverged`) -- ties directly to the issue's acceptance
criteria: revision id length, `down_revision` chained on
`040_workflow_run_action_card`, single migration head, that the migration
touches nothing beyond `ck_workflow_runs_stop_reason`, that
`INSERT ... stop_reason='confirmation_diverged'` actually succeeds against
the migrated schema (not merely that the constraint text contains the
string), that a bogus value still raises `CheckViolation`, that the
constraint's value list is derived programmatically from `StopReason` rather
than duplicated as a second hardcoded list, and a clean upgrade/downgrade
round trip.

`StopReason` (`services/agent/status.py`) has twelve members on this branch
-- `confirmation_diverged` is #1224's addition, landing on a sibling branch,
not this one. This migration nonetheless widens the database constraint to
thirteen values now so #1224's write path stops crashing the moment it
merges. The drift test below (`test_stop_reason_constraint_matches_enum_plus_confirmation_diverged`)
is written to require no edit in either state: it asserts the *migrated
constraint* equals `{m.value for m in StopReason} | {"confirmation_diverged"}`.
Today that union is 12 + 1 = 13, matching this migration's literal list
exactly. Once #1224 merges and `StopReason` gains `CONFIRMATION_DIVERGED`,
the union is a no-op (13 | {already-present value} = 13) and still matches.
A literal 13-value hardcoded list here would make the same claim only by
accident; deriving from the live enum is what turns a *fourteenth* member
someone forgets to add to the constraint into a red test here instead of
another production `CheckViolation`.

File-content assertions (revision string, down_revision, single head,
id length, additive-only-ness) need no database and always run at issue
tier. Everything else is Postgres-backed: gated by `requires_postgres`
(reused from `tests/integration/test_migrations.py`) and individually
marked `@pytest.mark.migration_heavy` -- deliberately per-test, not a
module-level `pytestmark`, so the structural tests above keep running at
issue tier while these run only at main tier on the wave->main PR, matching
#1214's review finding and the precedent
`tests/unit/test_workflow_run_action_card_fk_schema.py` (#1269) establishes.
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
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.services.agent.status import StopReason
from tests.integration.test_migrations import postgres_at_head, requires_postgres  # noqa: F401

__all__ = ["postgres_at_head", "requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_041_PATH = MIGRATIONS_DIR / "041_stop_reason_diverged.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

#: The exact value #1224 needs the constraint to accept -- named explicitly
#: (not derived) because it is the single fact this whole issue exists to
#: assert, the same way the issue's own acceptance criteria name it
#: literally. It is unioned with the *live* `StopReason` enum below rather
#: than folded into a second hardcoded 13-value list.
_CONFIRMATION_DIVERGED = "confirmation_diverged"


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
    private helper from another test module (same pattern #1269's
    `test_workflow_run_action_card_fk_schema.py` follows)."""
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


def _seed_shop_and_product(session) -> tuple:
    from juli_backend.models import models as m

    user = m.User(phone="+15550001274")
    session.add(user)
    session.flush()
    shop = m.Shop(user_id=user.id, shop_name="AGT-W5A-DP #1274 Test Shop")
    session.add(shop)
    session.flush()
    product = m.Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-w5a-dp-1274-{uuid.uuid4().hex[:8]}",
        name="Test Widget 1274",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(product)
    session.flush()
    return shop, product


def _stop_reason_check_sqltext(engine: Engine) -> str:
    inspector = inspect(engine)
    checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("workflow_runs")}
    assert "ck_workflow_runs_stop_reason" in checks, (
        "workflow_runs is missing ck_workflow_runs_stop_reason entirely"
    )
    return checks["ck_workflow_runs_stop_reason"]


def _values_in_check_sqltext(sqltext: str) -> set[str]:
    """Postgres rewrites `col IN (...)` on a varchar column into
    `col::text = ANY (ARRAY['a'::character varying, 'b'::character varying, ...]::text[])`
    -- this is what `pg_get_constraintdef` (and therefore SQLAlchemy's
    `get_check_constraints`) actually returns, verified empirically against
    a migrated database, not assumed from the migration's own source text."""
    return set(re.findall(r"'([^']*)'::character varying", sqltext))


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_041_revision_equals_filename_stem():
    assert MIGRATION_041_PATH.exists(), f"missing {MIGRATION_041_PATH}"
    body = MIGRATION_041_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 041 has no `revision: str = ...` line"
    assert rev.group(1) == "041_stop_reason_diverged"
    assert rev.group(1) == MIGRATION_041_PATH.stem
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32), a longer id fails only "
        "at upgrade time with StringDataRightTruncation"
    )


def test_migration_041_down_revision_is_040():
    body = MIGRATION_041_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 041 has no string `down_revision`"
    assert down.group(1) == "040_workflow_run_action_card"


def test_exactly_one_migration_head_after_041():
    """Walks the entire chain so a second, unrelated branch anywhere in the
    tree also fails this -- same convention as
    `test_exactly_one_migration_head_after_034`/`_035`/(#1269's `_after_040`
    analogue in `test_workflow_run_action_card_fk_schema.py`)."""
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


def test_migration_041_touches_only_stop_reason_constraint():
    """The issue's "touch no other column, table or constraint" lock,
    checked structurally: `upgrade()` must not create/drop/alter any table
    or column, and the only constraint name it references anywhere is
    `ck_workflow_runs_stop_reason`."""
    body = MIGRATION_041_PATH.read_text(encoding="utf-8")
    upgrade_body = body.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

    forbidden_ops = (
        "add_column",
        "drop_column",
        "create_table",
        "drop_table",
        "alter_column",
        "create_foreign_key",
        "create_index",
        "drop_index",
    )
    for op_name in forbidden_ops:
        assert f"op.{op_name}" not in upgrade_body, (
            f"migration 041 must only touch ck_workflow_runs_stop_reason, found op.{op_name}"
        )

    # The constraint name is a module-level constant (`_CONSTRAINT_NAME`),
    # not a literal repeated inline at each call site, so the name search
    # covers the whole file rather than just the `upgrade()` slice.
    constraint_names = set(re.findall(r'"(ck_[a-z_]+)"', body))
    assert constraint_names == {"ck_workflow_runs_stop_reason"}, (
        f"migration 041 references unexpected constraint(s): "
        f"{constraint_names - {'ck_workflow_runs_stop_reason'}}"
    )


# Deliberately no `len(StopReason) == 12` / `"confirmation_diverged" not in
# {...}` test here. Both would be true today and **false the moment #1224
# merges into the wave** -- pinning the enum's current size instead of the
# property that actually matters, exactly the "hardcoding today's answer"
# failure this file's other drift test is written to avoid. The property
# that must hold is "this slice's diff does not modify
# `services/agent/status.py`", which is structurally guaranteed here by
# construction (this migration/test pair are the only two files this diff
# touches -- `services/agent/status.py` is not edited anywhere in this
# change) rather than asserted by a brittle count that a merge would
# invalidate. `test_stop_reason_constraint_matches_enum_plus_confirmation_diverged`
# below already proves the constraint tracks the *live* enum in both the
# 12-member (today) and 13-member (post-#1224) states.


# ---------------------------------------------------------------------------
# Postgres-backed schema assertions.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.migration_heavy
def test_confirmation_diverged_insert_succeeds_at_head(postgres_at_head: Engine):
    """Proof by insertion, not by reading the constraint definition:
    `INSERT ... stop_reason='confirmation_diverged'` must succeed against a
    database migrated through 041."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)

        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            state={},
            status="completed",
            stop_reason="confirmation_diverged",
            prompt_version="optimize_product.v1",
            prompt_sha256="e" * 64,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        assert run.stop_reason == "confirmation_diverged"

        # Clean up: this row's `stop_reason` value only fits the 13-value
        # constraint 041 creates. `postgres_at_head` is a shared disposable
        # database, not a per-test transaction, and a later test's Alembic
        # `downgrade()` (back through 041 to restore the 12-value list)
        # validates every existing row against the constraint it is
        # re-adding -- a leftover row here would make an unrelated test's
        # downgrade fail on stale data instead of proving what it means to
        # prove.
        session.delete(run)
        session.commit()


@requires_postgres
@pytest.mark.migration_heavy
def test_bogus_stop_reason_insert_raises_check_violation_at_head(postgres_at_head: Engine):
    """The flip side: widening the constraint must not mean widening it to
    accept anything. A value that is not, and never was, a member of
    `StopReason` must still raise `IntegrityError` (`CheckViolation`)."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    # Deliberately <= 32 chars (the `stop_reason` column's own limit) so
    # this proves the CHECK constraint specifically, not the unrelated
    # `String(32)` column-width limit (`StringDataRightTruncation`, a
    # `DataError`, not the `IntegrityError`/`CheckViolation` under test).
    bogus = "not_a_real_stop_reason"
    assert len(bogus) <= 32
    assert bogus not in {reason.value for reason in StopReason}

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)

        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            state={},
            status="completed",
            stop_reason=bogus,
            prompt_version="optimize_product.v1",
            prompt_sha256="f" * 64,
        )
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@requires_postgres
@pytest.mark.migration_heavy
def test_stop_reason_constraint_matches_enum_plus_confirmation_diverged(
    postgres_at_head: Engine,
):
    """The drift-guard criterion: the migrated constraint's value list must
    equal `StopReason`'s members, derived programmatically from the enum --
    never a second hardcoded list.

    This is a union, not a straight equality against `StopReason` alone,
    deliberately: on THIS branch `StopReason` has 12 members (no
    `confirmation_diverged` -- that is #1224's, landing on a sibling
    branch) while migration 041 already widens the database constraint to
    13. `{m.value for m in StopReason} | {"confirmation_diverged"}` is 13
    today, matching the migrated constraint exactly; once #1224 merges and
    `StopReason` gains `CONFIRMATION_DIVERGED`, the union collapses back to
    the plain enum membership (13 | {already-present} == 13) and the
    assertion still holds with zero edits to this test.
    """
    sqltext = _stop_reason_check_sqltext(postgres_at_head)
    actual = _values_in_check_sqltext(sqltext)

    expected = {reason.value for reason in StopReason} | {_CONFIRMATION_DIVERGED}

    assert actual == expected, (
        f"ck_workflow_runs_stop_reason drifted from StopReason: "
        f"db-only={actual - expected} enum-only={expected - actual}"
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_migration_041_upgrade_and_downgrade_round_trip_cleanly():
    """Migration 041's `downgrade()` actually works: at 041,
    `confirmation_diverged` is accepted; after downgrading to 040, it is
    rejected again (the original 12-value constraint is restored, not just
    "a" constraint); upgrading back to 041 accepts it again."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "041_stop_reason_diverged")

        with Session(engine) as session:
            shop, product = _seed_shop_and_product(session)
            shop_id, product_id = shop.id, product.id
            run = m.WorkflowRun(
                shop_id=shop_id,
                product_id=product_id,
                state={},
                status="completed",
                stop_reason="confirmation_diverged",
                prompt_version="optimize_product.v1",
                prompt_sha256="1" * 64,
            )
            session.add(run)
            session.commit()

            # `downgrade()` re-adds the narrower 12-value constraint, and
            # Postgres validates every existing row against a newly-added
            # CHECK constraint -- so the row just proven above must be
            # cleared first, or the downgrade legitimately fails on data
            # that no longer fits, which is not what this test is proving.
            session.delete(run)
            session.commit()

        command.downgrade(cfg, "040_workflow_run_action_card")

        with Session(engine) as session:
            product = session.get(m.Product, product_id)
            run = m.WorkflowRun(
                shop_id=shop_id,
                product_id=product_id,
                state={},
                status="completed",
                stop_reason="confirmation_diverged",
                prompt_version="optimize_product.v1",
                prompt_sha256="2" * 64,
            )
            session.add(run)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        command.upgrade(cfg, "041_stop_reason_diverged")

        with Session(engine) as session:
            run = m.WorkflowRun(
                shop_id=shop_id,
                product_id=product_id,
                state={},
                status="completed",
                stop_reason="confirmation_diverged",
                prompt_version="optimize_product.v1",
                prompt_sha256="3" * 64,
            )
            session.add(run)
            session.commit()

            # Clean up: `juli_exec_1274_r1` is a shared disposable database
            # across this whole test module, not a per-test transaction --
            # a leftover `confirmation_diverged` row here would make a
            # LATER, unrelated test's downgrade-to-base fail on stale data
            # instead of proving what it means to prove (same reasoning as
            # the cleanup in `test_confirmation_diverged_insert_succeeds_at_head`
            # above).
            session.delete(run)
            session.commit()
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.migration_heavy
def test_existing_workflow_run_row_not_rewritten_by_migration_041():
    """Widening-only, no data migration: a row seeded before 041 runs must
    read back byte-identical after upgrading to 041."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "040_workflow_run_action_card")

        with Session(engine) as session:
            shop, product = _seed_shop_and_product(session)
            session.commit()
            shop_id, product_id = shop.id, product.id

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
                    "state": '{"pre_migration_041": true}',
                    "status": "completed",
                    "stop_reason": "final_response",
                    "prompt_version": "optimize_product.v1",
                    "prompt_sha256": "4" * 64,
                },
            )

        command.upgrade(cfg, "041_stop_reason_diverged")

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT shop_id, product_id, status, stop_reason "
                    "FROM workflow_runs WHERE id = :id"
                ),
                {"id": run_id},
            ).one()

        assert row.shop_id == shop_id
        assert row.product_id == product_id
        assert row.status == "completed"
        assert row.stop_reason == "final_response"
    finally:
        engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
