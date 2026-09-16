"""``uq_workflow_runs_active_shop_product``, re-keyed by migration
`062_workflow_and_subject` (#1701, ADR-087 d.1-d.2), from
``(shop_id, product_id)`` to
``(shop_id, workflow_key, subject_type, subject_ref)``.

Postgres-only throughout, on a disposable, per-module database created and
torn down here -- never the shared `DATABASE_URL` database, and never
SQLite. SQLAlchemy's ``postgresql_where`` DDL argument is a Postgres-only
kwarg the SQLite dialect silently ignores, so on SQLite this index is
unconditionally unique over its column list regardless of ``status`` --
exactly the case the "terminal run does not block" test exists to prove, and
exactly the case that would pass on SQLite for the wrong reason (verified by
hand while writing this module: pointing ``sync_engine`` at
``sqlite:///:memory:`` makes
``test_a_terminal_run_does_not_block_a_new_active_run_for_the_same_subject``
raise ``IntegrityError`` on the SECOND insert -- a false positive for "the
guard rejects a terminal run", when what actually rejected it was SQLite
ignoring the ``WHERE`` clause entirely).

Modeled on ``tests/unit/test_agent_runner_concurrency.py``'s
``_disposable_postgres_url`` / ``postgres_only_session`` pair (five sibling
modules already duplicate this fixture rather than share a private one);
skips cleanly, module-wide, when ``DATABASE_URL`` is not a reachable
Postgres.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.models.models import Product, Shop, User, WorkflowRun
from juli_backend.orm_base import Base


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="This module proves a Postgres-only partial index predicate; it "
    "skips cleanly without a reachable DATABASE_URL.",
)


@pytest.fixture(scope="module")
def _disposable_postgres_url():
    base_url = _database_url()
    if not base_url.startswith("postgresql"):
        yield None
        return

    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")
    db_name = f"juli_wr_subject_idx_{uuid.uuid4().hex[:12]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    disposable_url = make_url(sync_database_url(base_url)).set(database=db_name)
    try:
        # `str(URL)` masks the password as `***`; render_as_string(hide_password=False)
        # is what actually goes to `create_engine` (#1121/#1131's copies of this fixture).
        yield disposable_url.render_as_string(hide_password=False)
    finally:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


def _build_postgres_engine(url: str):
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        for schema_name in ("bronze", "silver", "gold", "ops"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
    Base.metadata.create_all(engine, checkfirst=True)
    return engine


@pytest.fixture
def session(_disposable_postgres_url) -> Session:
    engine = _build_postgres_engine(_disposable_postgres_url)
    factory = sessionmaker(bind=engine)
    sess = factory()
    yield sess
    sess.close()
    engine.dispose()


def _seed_shop_and_product(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    shop_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session.add(User(id=user_id, phone=f"+{uuid.uuid4().int % 10**14:014d}"))
    session.add(Shop(id=shop_id, user_id=user_id, shop_name="Subject Index Test Shop"))
    session.flush()

    product_id = uuid.uuid4()
    session.add(
        Product(
            id=product_id,
            shop_id=shop_id,
            tiktok_product_id=f"tt-{uuid.uuid4().hex[:12]}",
            name="Subject Index Test Product",
            status="ACTIVE",
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.flush()
    session.commit()
    return shop_id, product_id


def _new_run(
    shop_id: uuid.UUID,
    *,
    status: str,
    product_id: uuid.UUID | None = None,
    workflow_key: str | None = None,
    subject_type: str | None = None,
    subject_ref: str | None = None,
) -> WorkflowRun:
    """Build a run, passing through only the fields under test.

    ``workflow_key``/``subject_type``/``subject_ref`` are omitted (left to
    the model's own defaults) unless a test needs a specific value -- the
    same "old call site" shape ``approval.py`` uses today.
    """
    kwargs: dict = {
        "id": uuid.uuid4(),
        "shop_id": shop_id,
        "product_id": product_id,
        "state": {},
        "status": status,
        "prompt_version": "optimize_product.v1",
        "prompt_sha256": "0" * 64,
    }
    if workflow_key is not None:
        kwargs["workflow_key"] = workflow_key
    if subject_type is not None:
        kwargs["subject_type"] = subject_type
    if subject_ref is not None:
        kwargs["subject_ref"] = subject_ref
    return WorkflowRun(**kwargs)


class TestTwoWorkflowsOnOneProductDoNotCollide:
    """AC2 (#1701): the re-keyed index adds ``workflow_key`` to the tuple --
    it does not merely widen the old (shop_id, product_id) key. Two
    DIFFERENT workflows racing the SAME product must both insert; the
    cross-workflow lock is #1710's, deliberately not this index."""

    def test_two_workflows_on_one_product_do_not_collide_on_the_index(self, session):
        shop_id, product_id = _seed_shop_and_product(session)
        first = _new_run(
            shop_id, status="running", product_id=product_id, workflow_key="optimize_product_2"
        )
        session.add(first)
        session.commit()

        # A second, DIFFERENT workflow on the SAME product, also active.
        second = _new_run(
            shop_id, status="running", product_id=product_id, workflow_key="clear_excess_4"
        )
        session.add(second)
        session.commit()  # must not raise

        # Both rows genuinely persisted -- not merely "no exception was
        # raised" -- one per workflow_key, both still active for this shop.
        persisted = session.query(WorkflowRun).filter(WorkflowRun.shop_id == shop_id).all()
        assert {r.id for r in persisted} == {first.id, second.id}
        assert {r.workflow_key for r in persisted} == {"optimize_product_2", "clear_excess_4"}
        assert {r.status for r in persisted} == {"running"}

    def test_same_workflow_and_subject_still_collides(self, session):
        """The widening claim above is not vacuous: two runs sharing the
        FULL new tuple (same workflow_key, same product-derived subject)
        still raise IntegrityError on the second insert -- proving the index
        is still doing real work, not just "always allow"."""
        shop_id, product_id = _seed_shop_and_product(session)
        session.add(
            _new_run(
                shop_id, status="running", product_id=product_id, workflow_key="optimize_product_2"
            )
        )
        session.commit()

        session.add(
            _new_run(
                shop_id, status="queued", product_id=product_id, workflow_key="optimize_product_2"
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestNonProductSubjectPersists:
    """AC3 (#1701): a run with no product at all -- ``product_id`` is
    genuinely NULL, not merely unset -- must persist and list. Proves the
    NOT NULL drop on `product_id` is real, not just declared in the model."""

    def test_non_product_subject_persists(self, session):
        shop_id = uuid.uuid4()
        user_id = uuid.uuid4()
        session.add(User(id=user_id, phone=f"+{uuid.uuid4().int % 10**14:014d}"))
        session.add(Shop(id=shop_id, user_id=user_id, shop_name="Dispatch Window Shop"))
        session.commit()

        run = _new_run(
            shop_id,
            status="running",
            product_id=None,
            workflow_key="dispatch_window_sweep",
            subject_type="dispatch_window",
            subject_ref="2026-09-16T00:00:00Z",
        )
        session.add(run)
        session.commit()

        persisted = session.get(WorkflowRun, run.id)
        assert persisted is not None
        assert persisted.product_id is None
        assert persisted.subject_type == "dispatch_window"
        assert persisted.subject_ref == "2026-09-16T00:00:00Z"

        listed = session.query(WorkflowRun).filter(WorkflowRun.shop_id == shop_id).all()
        assert [r.id for r in listed] == [run.id]

    def test_subject_ref_default_raises_loudly_for_a_null_product_with_no_explicit_subject_ref(
        self, session
    ):
        """A caller that passes ``product_id=None`` but never names
        ``subject_ref`` gets a loud client-side ``ValueError``, never the
        literal string ``"None"`` silently written to the column."""
        shop_id = uuid.uuid4()
        user_id = uuid.uuid4()
        session.add(User(id=user_id, phone=f"+{uuid.uuid4().int % 10**14:014d}"))
        session.add(Shop(id=shop_id, user_id=user_id, shop_name="Missing Subject Shop"))
        session.commit()

        run = _new_run(shop_id, status="running", product_id=None)
        session.add(run)
        # SQLAlchemy wraps a raising client-side default in StatementError;
        # the original ValueError message survives in its text.
        with pytest.raises(StatementError, match="subject_ref has no default"):
            session.flush()
        session.rollback()


class TestPartialIndexStillOnlyCoversActiveStatuses:
    """Postgres-only proof (see module docstring) that the re-key preserved
    the ORIGINAL partial predicate -- a terminal run for a subject does not
    block a fresh active run for that same subject."""

    @pytest.mark.parametrize("terminal_status", ["completed", "cancelled", "timed_out", "failed"])
    def test_a_terminal_run_does_not_block_a_new_active_run_for_the_same_subject(
        self, session, terminal_status
    ):
        shop_id, product_id = _seed_shop_and_product(session)
        terminal_run = _new_run(
            shop_id,
            status=terminal_status,
            product_id=product_id,
            workflow_key="optimize_product_2",
        )
        session.add(terminal_run)
        session.commit()

        active_run = _new_run(
            shop_id, status="queued", product_id=product_id, workflow_key="optimize_product_2"
        )
        session.add(active_run)
        session.commit()  # must not raise

        # Both rows genuinely persisted, at their own distinct statuses --
        # the new active run did not silently fail to insert, and the
        # terminal row was not overwritten or removed to make room for it.
        persisted = {
            r.id: r.status
            for r in session.query(WorkflowRun).filter(WorkflowRun.shop_id == shop_id).all()
        }
        assert persisted == {terminal_run.id: terminal_status, active_run.id: "queued"}
