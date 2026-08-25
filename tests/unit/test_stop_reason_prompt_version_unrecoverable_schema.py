"""Schema/migration checks for #1359 (migration
`042_stop_reason_prompt_pin`) -- ties directly to the
issue's acceptance criteria: revision id length, `down_revision` chained on
`041_stop_reason_diverged`, single migration head, that the migration touches
nothing beyond `ck_workflow_runs_stop_reason`, that
`INSERT ... stop_reason='prompt_version_unrecoverable'` actually succeeds
against the migrated schema (not merely that the constraint text contains the
string), that a bogus value still raises `CheckViolation`, that the
constraint's value list is derived programmatically from `StopReason` rather
than duplicated as a second hardcoded list, and a clean upgrade/downgrade
round trip.

Class of bug (issue #1359): model constraint edited without migration causes
production IntegrityError on the fail-closed code path that writes the value.
Unit tests pass because the test database is built from models.py directly;
production uses Alembic migrations. This whole test file is invisible to issue
tier by necessity -- it needs a real Postgres database and Alembic's upgrade/
downgrade machinery, so tests are Postgres-backed and individually marked
`@pytest.mark.migration_heavy`. File-content assertions still run at issue
tier (no database needed).
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
MIGRATION_042_PATH = MIGRATIONS_DIR / "042_stop_reason_prompt_pin.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

#: The exact value #1359 needs the constraint to accept -- named explicitly
#: because it is the single fact this whole issue exists to assert, the same
#: way the issue's own acceptance criteria name it literally. Unioned with
#: the *live* `StopReason` enum below.
_PROMPT_VERSION_UNRECOVERABLE = "prompt_version_unrecoverable"


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
    """Refuse to downgrade against anything but a local, disposable Postgres."""
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

    user = m.User(phone="+15550001359")
    session.add(user)
    session.flush()
    shop = m.Shop(user_id=user.id, shop_name="AGT-W5A-PROMPTPIN #1359 Test Shop")
    session.add(shop)
    session.flush()
    product = m.Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-w5a-promptpin-1359-{uuid.uuid4().hex[:8]}",
        name="Test Widget 1359",
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
    """Postgres rewrites `col IN (...)` into an ANY(ARRAY[...]) form."""
    return set(re.findall(r"'([^']*)'::character varying", sqltext))


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_xxx_revision_equals_filename_stem():
    assert MIGRATION_042_PATH.exists(), f"missing {MIGRATION_042_PATH}"
    body = MIGRATION_042_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration XXX has no `revision: str = ...` line"
    assert rev.group(1) == MIGRATION_042_PATH.stem, (
        f"revision id {rev.group(1)!r} must match filename {MIGRATION_042_PATH.stem!r}"
    )
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32), a longer id fails only "
        "at upgrade time with StringDataRightTruncation"
    )


def test_migration_xxx_down_revision_is_041():
    body = MIGRATION_042_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration XXX has no string `down_revision`"
    assert down.group(1) == "041_stop_reason_diverged"


def test_migration_xxx_touches_only_stop_reason_constraint():
    """The issue's "touch no other column, table or constraint" lock."""
    body = MIGRATION_042_PATH.read_text(encoding="utf-8")
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
            f"migration XXX must only touch ck_workflow_runs_stop_reason, found op.{op_name}"
        )

    constraint_names = set(re.findall(r'"(ck_[a-z_]+)"', body))
    assert constraint_names == {"ck_workflow_runs_stop_reason"}, (
        f"migration XXX references unexpected constraint(s): "
        f"{constraint_names - {'ck_workflow_runs_stop_reason'}}"
    )


# ---------------------------------------------------------------------------
# Postgres-backed schema assertions.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.migration_heavy
def test_prompt_version_unrecoverable_insert_succeeds_at_head(postgres_at_head: Engine):
    """Proof by insertion: `INSERT ... stop_reason='prompt_version_unrecoverable'`
    must succeed against a database migrated through XXX."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)

        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            state={},
            status="failed",
            stop_reason="prompt_version_unrecoverable",
            prompt_version="optimize_product.v1",
            prompt_sha256="e" * 64,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        assert run.stop_reason == "prompt_version_unrecoverable"

        # Clean up: this row's `stop_reason` value only fits the migrated
        # constraint. Shared disposable database -- downgrade elsewhere fails on stale data.
        session.delete(run)
        session.commit()


@requires_postgres
@pytest.mark.migration_heavy
def test_bogus_stop_reason_insert_raises_check_violation_at_head(postgres_at_head: Engine):
    """The flip side: widening the constraint must not accept anything."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    bogus = "not_a_real_stop_reason"
    assert len(bogus) <= 32
    assert bogus not in {reason.value for reason in StopReason}

    with Session(postgres_at_head) as session:
        shop, product = _seed_shop_and_product(session)

        run = m.WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            state={},
            status="failed",
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
def test_stop_reason_constraint_matches_enum_plus_prompt_version_unrecoverable(
    postgres_at_head: Engine,
):
    """Drift-guard: the migrated constraint's value list must equal
    `StopReason`'s members plus `prompt_version_unrecoverable`, derived
    programmatically from the enum."""
    sqltext = _stop_reason_check_sqltext(postgres_at_head)
    actual = _values_in_check_sqltext(sqltext)

    expected = {reason.value for reason in StopReason} | {_PROMPT_VERSION_UNRECOVERABLE}

    assert actual == expected, (
        f"ck_workflow_runs_stop_reason drifted from StopReason: "
        f"db-only={actual - expected} enum-only={expected - actual}"
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_migration_xxx_upgrade_and_downgrade_round_trip_cleanly():
    """Migration XXX's `downgrade()` actually works: at XXX,
    `prompt_version_unrecoverable` is accepted; after downgrading to 041, it
    is rejected again."""
    from sqlalchemy.orm import Session

    from juli_backend.models import models as m

    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        # Upgrade to the migration before XXX exists
        _reset_to_revision(cfg, "041_stop_reason_diverged")

        with Session(engine) as session:
            shop, product = _seed_shop_and_product(session)
            shop_id, product_id = shop.id, product.id

        # Now upgrade to XXX and verify the value works
        command.upgrade(cfg, MIGRATION_042_PATH.stem)

        with Session(engine) as session:
            run = m.WorkflowRun(
                shop_id=shop_id,
                product_id=product_id,
                state={},
                status="failed",
                stop_reason="prompt_version_unrecoverable",
                prompt_version="optimize_product.v1",
                prompt_sha256="1" * 64,
            )
            session.add(run)
            session.commit()

            # Clean up before downgrade
            session.delete(run)
            session.commit()

        # Downgrade back to 041
        command.downgrade(cfg, "041_stop_reason_diverged")

        with Session(engine) as session:
            run = m.WorkflowRun(
                shop_id=shop_id,
                product_id=product_id,
                state={},
                status="failed",
                stop_reason="prompt_version_unrecoverable",
                prompt_version="optimize_product.v1",
                prompt_sha256="2" * 64,
            )
            session.add(run)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        # Upgrade back to XXX
        command.upgrade(cfg, MIGRATION_042_PATH.stem)

        with Session(engine) as session:
            run = m.WorkflowRun(
                shop_id=shop_id,
                product_id=product_id,
                state={},
                status="failed",
                stop_reason="prompt_version_unrecoverable",
                prompt_version="optimize_product.v1",
                prompt_sha256="3" * 64,
            )
            session.add(run)
            session.commit()

            # Clean up
            session.delete(run)
            session.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
