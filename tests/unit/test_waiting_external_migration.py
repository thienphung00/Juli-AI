"""Migration `073_waiting_external` — the database half of issue #1706.

The status vocabulary is pinned in five places at once and a four-place
version passes every Python test while breaking the wire. This file is the
database place: the two widened CHECK constraints, the two added columns, the
widened active-run partial index and the widened fleet enumeration.

Two tiers, on purpose, following `test_stop_reason_diverged_schema.py`'s
precedent (#1274). The structural half reads the migration source and the
model and needs no database, so it runs at issue tier on every PR. The
behavioural half is Postgres-backed and marked `migration_heavy`, because a
CHECK constraint IS the assertion here: SQLite enforces none of these, so a
SQLite test that inserted `status='waiting_external'` and watched it succeed
would prove the exact opposite of what it claimed.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.models.models import WorkflowRun
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from tests.integration.test_migrations import postgres_at_head, requires_postgres  # noqa: F401
from tests.support.builders import seed_user_row_at_any_revision

__all__ = ["postgres_at_head", "requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_ROOT = REPO_ROOT / "backend/src/juli_backend/database/migrations"
VERSIONS_DIR = MIGRATIONS_ROOT / "versions"
MIGRATION_PATH = VERSIONS_DIR / "073_waiting_external_run_state.py"

REVISION = "073_waiting_external"
DOWN_REVISION = "071_sync_state_last_outcome"

#: The one status and the two stop reasons this revision makes writable.
NEW_STATUS = "waiting_external"
NEW_STOP_REASONS = ("paused_for_external_wait", "external_wait_expired")
#: The two columns it adds.
NEW_COLUMNS = ("waiting_external_since", "external_wait_reason")

STATUS_CONSTRAINT = "ck_workflow_runs_status"
STOP_REASON_CONSTRAINT = "ck_workflow_runs_stop_reason"
ACTIVE_INDEX = "uq_workflow_runs_active_shop_product"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_ROOT))
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


def _assert_local_database_url(url: str) -> None:
    """#734's discipline: never downgrade anything but a throwaway local
    database."""
    hostname = urlparse(url).hostname
    if hostname is not None and hostname.lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing a destructive Alembic downgrade against a non-local "
            f"DATABASE_URL host ({hostname})."
        )


def _check_sqltext(engine: Engine, name: str) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = :name AND conrelid = 'public.workflow_runs'::regclass"
            ),
            {"name": name},
        ).scalar_one_or_none()
    assert row is not None, f"{name} is not present on workflow_runs"
    return str(row)


def _quoted_values(sqltext: str) -> set[str]:
    return set(re.findall(r"'([^']+)'", sqltext))


def _index_predicate(engine: Engine, name: str) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
            {"name": name},
        ).scalar_one_or_none()
    assert row is not None, f"{name} is not present"
    return str(row)


def _enumeration_body(engine: Engine) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.proname = "
                "'enumerate_active_workflow_runs'"
            )
        ).scalar_one_or_none()
    assert row is not None, "enumerate_active_workflow_runs() is not present"
    return str(row)


@pytest.fixture
def drained(postgres_at_head: Engine):
    """Remove every row carrying the new vocabulary once the test is done.

    Not housekeeping — the downgrade guard working as designed. `postgres_at_head`
    resets by downgrading to base, which passes through 073, and 073 refuses to
    narrow its CHECKs while a run is still waiting. A test that left one behind
    would block the NEXT test's reset with the very error this revision exists
    to raise. The teardown here is the miniature of the operational rule the
    migration's docstring states: drain the suspended runs, then revert.
    """
    yield postgres_at_head
    with postgres_at_head.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM public.workflow_runs "
                "WHERE status = :status OR stop_reason = ANY(:reasons)"
            ),
            {"status": NEW_STATUS, "reasons": list(NEW_STOP_REASONS)},
        )


def _seed_shop_and_product(session: Session) -> tuple:
    from juli_backend.models import models as m

    user_id = seed_user_row_at_any_revision(session, "+15550001706")
    shop = m.Shop(user_id=user_id, shop_name="W9-A #1706 Test Shop")
    session.add(shop)
    session.flush()
    product = m.Product(
        shop_id=shop.id,
        tiktok_product_id=f"w9a-1706-{uuid.uuid4().hex[:8]}",
        name="Test Widget 1706",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(product)
    session.flush()
    return shop, product


# ---------------------------------------------------------------------------
# Structural: the file, the chain, and the model/migration parity. No database.
# ---------------------------------------------------------------------------


class TestTheMigrationIsWhereAndWhatItClaims:
    def test_it_chains_onto_the_head_of_versions(self):
        body = MIGRATION_PATH.read_text(encoding="utf-8")
        assert f'revision: str = "{REVISION}"' in body
        assert f'down_revision: str | None = "{DOWN_REVISION}"' in body

    def test_the_revision_id_fits_the_alembic_version_column(self):
        """`alembic_version.version_num` is `VARCHAR(32)`. The long form
        `073_waiting_external_run_state` is 30 and would fit, but the short id
        is what the file declares and what every other file must reference --
        asserted so a later rename cannot quietly exceed the column (071's own
        note records the 34-character near-miss that made this a rule)."""
        assert len(REVISION) <= 32

    def test_every_new_column_is_on_the_model_and_in_the_migration(self):
        """The two lists must agree, or the SQLite-backed tests in
        `test_reaper_external_wait.py` pass over a schema Postgres does not
        have."""
        body = MIGRATION_PATH.read_text(encoding="utf-8")
        model_columns = set(WorkflowRun.__table__.columns.keys())
        for name in NEW_COLUMNS:
            assert name in model_columns, f"{name} is in the migration but not on the model"
            assert f'"{name}"' in body, f"{name} is on the model but not in the migration"

    def test_the_model_check_constraints_name_the_new_vocabulary(self):
        """The CHECK text lives in the model AND in this migration, and the
        two must move in the same commit or the schema-parity test finds the
        drift after the fact instead of before it."""
        constraints = {
            c.name: str(c.sqltext)
            for c in WorkflowRun.__table__.constraints
            if getattr(c, "name", None) in {STATUS_CONSTRAINT, STOP_REASON_CONSTRAINT}
        }
        assert _quoted_values(constraints[STATUS_CONSTRAINT]) == {
            member.value for member in WorkflowRunStatus
        }
        assert _quoted_values(constraints[STOP_REASON_CONSTRAINT]) == {
            member.value for member in StopReason
        }

    def test_the_model_active_index_predicate_names_the_new_status(self):
        """The decision this slice was told to make deliberately and state:
        a run waiting on the world STILL HOLDS ITS SUBJECT."""
        index = next(ix for ix in WorkflowRun.__table__.indexes if ix.name == ACTIVE_INDEX)
        predicate = str(index.dialect_options["postgresql"]["where"])
        assert NEW_STATUS in predicate
        assert _quoted_values(predicate) == {
            WorkflowRunStatus.QUEUED.value,
            WorkflowRunStatus.RUNNING.value,
            WorkflowRunStatus.WAITING_APPROVAL.value,
            WorkflowRunStatus.WAITING_EXTERNAL.value,
        }

    def test_the_upgrade_drops_nothing_it_does_not_recreate(self):
        """`op.drop_index`/`op.drop_constraint` appear only inside the
        `_replace_*` helpers, each of which creates the replacement
        immediately afterwards. No `drop_column`, no `drop_table`, and no
        data-moving statement anywhere in the upgrade path."""
        body = MIGRATION_PATH.read_text(encoding="utf-8")
        upgrade_body = body.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        for forbidden in ("op.drop_column", "op.drop_table", "op.bulk_insert"):
            assert forbidden not in upgrade_body


class TestTheAdditiveGateAcceptsIt:
    def test_the_gate_accepts_this_revision(self):
        """A CHECK-constraint extension that only ADDS an allowed value is
        additive, and so are two nullable columns and a widened partial index.
        Run against the real gate, not a re-implementation of its rules."""
        sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
        from migration_additive_gate import evaluate_migration_paths

        result = evaluate_migration_paths([MIGRATION_PATH])
        assert result.accepted, result.report()
        assert REVISION in result.inspected

    def test_the_deferred_step_is_still_refused_and_still_the_tail(self):
        """Renumbering the contract step onto this revision must not have
        turned it into something the gate accepts -- that refusal is the
        step's signature, and a version of it the gate accepted would have
        stopped moving data, which is its entire purpose."""
        sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
        from migration_additive_gate import evaluate_migration_paths

        deferred = MIGRATIONS_ROOT / "deferred/074_users_placeholder_phone_cleanup.py"
        assert deferred.is_file()
        result = evaluate_migration_paths([deferred])
        assert not result.accepted
        body = deferred.read_text(encoding="utf-8")
        assert f'down_revision: str | None = "{REVISION}"' in body


# ---------------------------------------------------------------------------
# Behavioural: against a real Postgres migrated to head. A CHECK constraint is
# the assertion, and SQLite enforces none of these.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.migration_heavy
def test_the_status_check_equals_the_enum(postgres_at_head: Engine):
    """Derived from the live enum, never a second hardcoded list: a ninth
    status someone forgets to add to the constraint is a red test here rather
    than a production `CheckViolation`."""
    actual = _quoted_values(_check_sqltext(postgres_at_head, STATUS_CONSTRAINT))
    expected = {member.value for member in WorkflowRunStatus}
    assert actual == expected, f"db-only={actual - expected} enum-only={expected - actual}"


@requires_postgres
@pytest.mark.migration_heavy
def test_the_stop_reason_check_equals_the_enum(postgres_at_head: Engine):
    actual = _quoted_values(_check_sqltext(postgres_at_head, STOP_REASON_CONSTRAINT))
    expected = {member.value for member in StopReason}
    assert actual == expected, f"db-only={actual - expected} enum-only={expected - actual}"


@requires_postgres
@pytest.mark.migration_heavy
def test_a_waiting_external_row_really_inserts(postgres_at_head: Engine, drained: Engine):
    """Not "the constraint text contains the string" -- the INSERT itself.

    Both new stop reasons are exercised too, because the run the runner writes
    carries `paused_for_external_wait` and the run the reaper writes carries
    `external_wait_expired`, and a constraint that accepted one but not the
    other would strand a run at whichever end it refused.
    """
    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)
        from juli_backend.models import models as m

        for stop_reason, status in (
            ("paused_for_external_wait", NEW_STATUS),
            ("external_wait_expired", "timed_out"),
        ):
            session.add(
                m.WorkflowRun(
                    shop_id=shop.id,
                    product_id=product.id,
                    subject_ref=f"{stop_reason}-{uuid.uuid4().hex[:8]}",
                    state={},
                    status=status,
                    stop_reason=stop_reason,
                    waiting_external_since=datetime.now(UTC),
                    external_wait_reason="supplier_delivery",
                    prompt_version="optimize_product.v1",
                    prompt_sha256="f" * 64,
                )
            )
            session.commit()


@requires_postgres
@pytest.mark.migration_heavy
def test_a_bogus_status_is_still_refused(postgres_at_head: Engine):
    """The widening is a widening, not a removal: the CHECK still refuses
    anything outside the vocabulary."""
    from juli_backend.models import models as m

    bogus = "waiting_for_godot"
    assert len(bogus) <= 20
    assert bogus not in {member.value for member in WorkflowRunStatus}

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)
        session.add(
            m.WorkflowRun(
                shop_id=shop.id,
                product_id=product.id,
                state={},
                status=bogus,
                prompt_version="optimize_product.v1",
                prompt_sha256="f" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@requires_postgres
@pytest.mark.migration_heavy
def test_the_new_columns_exist_and_are_nullable(postgres_at_head: Engine):
    columns = {c["name"]: c for c in inspect(postgres_at_head).get_columns("workflow_runs")}
    for name in NEW_COLUMNS:
        assert name in columns, f"{name} missing from the migrated schema"
        assert columns[name]["nullable"], (
            f"{name} must be nullable -- a NOT NULL column the previous release "
            "never writes fails its inserts during the shared-database window"
        )
        assert columns[name].get("default") is None


@requires_postgres
@pytest.mark.migration_heavy
def test_an_externally_waiting_run_still_holds_its_subjects_active_slot(
    postgres_at_head: Engine,
    drained: Engine,
):
    """The decision, proven rather than implied.

    With a run parked in `waiting_external` for a subject, a second run for
    the SAME (shop_id, workflow_key, subject_type, subject_ref) must collide.
    A silent loss of the subject's active-run slot is the failure this
    assertion exists to catch, and it is invisible to every Python test.
    """
    from juli_backend.models import models as m

    predicate = _index_predicate(postgres_at_head, ACTIVE_INDEX)
    assert NEW_STATUS in predicate

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)
        subject_ref = f"subject-{uuid.uuid4().hex[:8]}"
        session.add(
            m.WorkflowRun(
                shop_id=shop.id,
                product_id=product.id,
                subject_ref=subject_ref,
                state={},
                status=NEW_STATUS,
                stop_reason="paused_for_external_wait",
                waiting_external_since=datetime.now(UTC),
                external_wait_reason="supplier_delivery",
                prompt_version="optimize_product.v1",
                prompt_sha256="f" * 64,
            )
        )
        session.commit()

        session.add(
            m.WorkflowRun(
                shop_id=shop.id,
                product_id=product.id,
                subject_ref=subject_ref,
                state={},
                status="queued",
                prompt_version="optimize_product.v1",
                prompt_sha256="f" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@requires_postgres
@pytest.mark.migration_heavy
def test_the_fleet_enumeration_returns_an_externally_waiting_run(
    postgres_at_head: Engine, drained: Engine
):
    """052's lesson, reproduced. Without this widening the reaper's third
    sweep selects zero rows as `juli_app` with no shop context and reports
    success having done nothing -- the successful no-op ADR-089 exists to
    remove, visible only against a real database.
    """
    from juli_backend.models import models as m

    assert NEW_STATUS in _enumeration_body(postgres_at_head)

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)
        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            subject_ref=f"subject-{uuid.uuid4().hex[:8]}",
            state={},
            status=NEW_STATUS,
            stop_reason="paused_for_external_wait",
            waiting_external_since=datetime.now(UTC),
            external_wait_reason="supplier_delivery",
            prompt_version="optimize_product.v1",
            prompt_sha256="f" * 64,
        )
        session.add(run)
        session.commit()

        enumerated = {
            row[0]
            for row in session.execute(
                text("SELECT out_run_id FROM public.enumerate_active_workflow_runs()")
            ).all()
        }
        assert run.id in enumerated


@requires_postgres
@pytest.mark.migration_heavy
def test_the_downgrade_refuses_while_a_run_is_still_waiting(
    postgres_at_head: Engine, drained: Engine
):
    """Narrowing a CHECK under live rows must fail by NAME.

    An opaque constraint-validation error is what tempts an operator into
    deleting the suspended runs, and those runs are inert under the previous
    release -- its reaper does not recognise the state and will never reap
    them. So the refusal is asserted pre-merge rather than discovered during a
    rollback.
    """
    from juli_backend.models import models as m

    cfg = _alembic_config()
    _assert_local_database_url(_database_url())

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)
        session.add(
            m.WorkflowRun(
                shop_id=shop.id,
                product_id=product.id,
                subject_ref=f"subject-{uuid.uuid4().hex[:8]}",
                state={},
                status=NEW_STATUS,
                stop_reason="paused_for_external_wait",
                waiting_external_since=datetime.now(UTC),
                external_wait_reason="supplier_delivery",
                prompt_version="optimize_product.v1",
                prompt_sha256="f" * 64,
            )
        )
        session.commit()

    with pytest.raises(RuntimeError, match="Drain or reap those runs"):
        command.downgrade(cfg, DOWN_REVISION)

    # Clear the obstruction and the downgrade/upgrade round trip is clean.
    with Session(postgres_at_head) as session:
        session.execute(
            text("DELETE FROM public.workflow_runs WHERE status = :status"),
            {"status": NEW_STATUS},
        )
        session.commit()

    command.downgrade(cfg, DOWN_REVISION)
    remaining = {c["name"] for c in inspect(postgres_at_head).get_columns("workflow_runs")}
    assert not remaining & set(NEW_COLUMNS)
    assert NEW_STATUS not in _quoted_values(_check_sqltext(postgres_at_head, STATUS_CONSTRAINT))
    command.upgrade(cfg, "head")
    assert NEW_STATUS in _quoted_values(_check_sqltext(postgres_at_head, STATUS_CONSTRAINT))
