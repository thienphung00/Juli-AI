"""`ToolExecutionLedger` — ADR-073 decision 3, issue #1121 / AGT-W3A.

Covers the idempotent WRITE-path machinery `ToolExecutor` (`tool_executor.py`,
#1119) routes WRITE-classified tool calls through: stored-result replay with
zero vendor calls, verify-then-decide on an `in_flight`/`failed` row found on
retry (applied -> retroactive success; not applied -> exactly one
re-execution; unverifiable -> fail closed), the fresh-dispatch
SELECT->INSERT->vendor->UPDATE ordering, and the unique-index race.

**Dual-backend matrix.** Every DB-backed test class below runs against both
a SQLite in-memory engine (always) and a real Postgres instance (only when
`DATABASE_URL` resolves to one reachable, mirroring
`tests/integration/test_migrations.py`'s `requires_postgres` convention) via
the module-scoped, parametrized `sync_engine` fixture. The unique-index race
specifically is the one behaviour the issue's own text says cannot be proven
on SQLite ("constraint and concurrency semantics differ") — it still runs
there for cheap coverage, but its authoritative proof is the Postgres
parametrization. `ledger.py`'s module docstring explains why this module's
DB access is a synchronous `sqlalchemy.orm.Session` (`psycopg2`/`sqlite3`),
not the `AsyncSession` the rest of the codebase uses.

**Disposable Postgres database, not the shared `DATABASE_URL` database
directly.** `DATABASE_URL` in this repo names a database other suites in
the same pytest session also own outright — `tests/unit/test_workflow_runs_schema.py`
and friends run a full Alembic `downgrade("base")` / `upgrade("head")`
round trip directly against it (via `tests/integration/test_migrations.py`'s
`postgres_at_head`), which conflicts with (and is corrupted by) this
module's tables if this module ran `Base.metadata.create_all` against that
same database — a `DuplicateTable` once the migration tests try to
recreate a table this module already created outside Alembic's tracking.
So the Postgres backend below instead spins up a throwaway database of its
own — created from `DATABASE_URL`'s connection parameters (same host, port,
credentials) but its own name — via the module-scoped
`_disposable_postgres_url` fixture, and drops it at module teardown. This
is what the issue calls "disposable database, dropped afterwards": this
module's Postgres tests never touch `DATABASE_URL`'s own database at all.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.integrations.tiktok.factories import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.models.models import Product, Shop, ToolExecution, User, WorkflowRun
from juli_backend.orm_base import Base
from juli_backend.services.agent.runner.ledger import (
    LedgerStatus,
    ToolExecutionLedger,
    ToolExecutionUnrecoverableError,
    VerifyOutcome,
    VerifyReadBack,
)
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import (
    GetProductInformationInput,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.product_write import (
    UpdateProductPriceInput,
    register_product_write_tools,
)

# --- dual-backend engine matrix -------------------------------------------


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    """Mirrors `tests/integration/test_migrations.py::_postgres_reachable`."""
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


_BACKEND_PARAMS = [
    "sqlite",
    pytest.param(
        "postgres",
        marks=pytest.mark.skipif(
            not _postgres_reachable(),
            reason=(
                "DATABASE_URL is not set to a reachable Postgres instance — the "
                "ADR-073 decision-3 unique-index race is not authoritatively "
                "provable on SQLite (see ledger.py's module docstring)."
            ),
        ),
    ),
]


_SQLITE_SCHEMA_TRANSLATE_MAP = {"ops": None, "bronze": None, "gold": None, "silver": None}


@pytest.fixture(scope="module")
def _disposable_postgres_url():
    """Create a throwaway Postgres database from `DATABASE_URL`'s connection
    parameters (own name, same server/credentials) and drop it at module
    teardown — see the module docstring for why this module never runs DDL
    against `DATABASE_URL`'s own database. A no-op (`None`) when
    `DATABASE_URL` is unset/non-Postgres; nothing in this module reaches
    this fixture's body in that case (the "postgres" backend param is
    skipped before any fixture in its chain executes).
    """
    base_url = _database_url()
    if not base_url.startswith("postgresql"):
        yield None
        return

    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")
    db_name = f"juli_ledger_test_{uuid.uuid4().hex[:12]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    disposable_url = make_url(sync_database_url(base_url)).set(database=db_name)
    try:
        yield str(disposable_url)
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


@pytest.fixture(params=_BACKEND_PARAMS)
def sync_engine(request, _disposable_postgres_url):
    if request.param == "sqlite":
        # `models/models.py` schema-qualifies some tables (bronze/silver/
        # gold/ops); SQLite has no such schemas, so fold them onto the
        # default database — mirrors tests/unit/conftest.py's async engine
        # fixture.
        engine = create_engine(
            "sqlite:///:memory:",
            execution_options={"schema_translate_map": _SQLITE_SCHEMA_TRANSLATE_MAP},
        )
    else:
        engine = create_engine(_disposable_postgres_url, pool_pre_ping=True)
        # `models/models.py` schema-qualifies some tables (bronze/silver/
        # gold/ops) that only exist in a fully Alembic-migrated database —
        # this disposable database is bare, so create them directly; a
        # fresh CREATE DATABASE never has them.
        with engine.begin() as conn:
            for schema_name in ("bronze", "silver", "gold", "ops"):
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
    Base.metadata.create_all(engine, checkfirst=True)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(sync_engine):
    return sessionmaker(bind=sync_engine)


@pytest.fixture
def session(session_factory):
    sess = session_factory()
    yield sess
    sess.close()


# --- seed helpers -----------------------------------------------------------


def _seed_run(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a minimal valid User -> Shop -> Product -> WorkflowRun chain
    (real FK parents — required for the Postgres backend to accept a
    `ToolExecution.workflow_run_id` FK) and return `(shop_id, workflow_run_id)`.
    """
    shop_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session.add(User(id=user_id, phone=f"+{uuid.uuid4().int % 10**14:014d}"))
    session.add(Shop(id=shop_id, user_id=user_id, shop_name="Ledger Test Shop"))
    session.flush()

    product_id = uuid.uuid4()
    session.add(
        Product(
            id=product_id,
            shop_id=shop_id,
            tiktok_product_id=f"tt-{uuid.uuid4().hex[:12]}",
            name="Ledger Test Product",
            status="ACTIVE",
            # Naive UTC: asyncpg rejects tz-aware datetimes for naive `DateTime`
            # columns where SQLite silently tolerates them (sibling-slice note).
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.flush()

    run_id = uuid.uuid4()
    session.add(
        WorkflowRun(
            id=run_id,
            shop_id=shop_id,
            product_id=product_id,
            state={},
            status="running",
            prompt_version="v1",
            prompt_sha256="0" * 64,
        )
    )
    session.flush()
    session.commit()
    return shop_id, run_id


def _seed_ledger_row(
    session: Session,
    *,
    shop_id: uuid.UUID,
    workflow_run_id: uuid.UUID,
    tool_call_id: str,
    operation: str,
    status: str,
) -> ToolExecution:
    """Directly seed a ledger row in a given state, simulating a prior
    attempt (e.g. a crash mid-flight) without going through
    `ToolExecutionLedger` itself."""
    row = ToolExecution(
        shop_id=shop_id,
        approval_id=f"seed:{tool_call_id}",
        tool_name=operation,
        status=status,
        workflow_run_id=workflow_run_id,
        tool_call_id=tool_call_id,
        operation=operation,
    )
    session.add(row)
    session.flush()
    session.commit()
    return row


def _fresh_tool_call_id() -> str:
    return f"call-{uuid.uuid4().hex[:12]}"


class _CallSpy:
    """Records how many times it was invoked; returns a fixed result or
    raises a fixed exception."""

    def __init__(self, result: dict | None = None, exc: BaseException | None = None) -> None:
        self.calls = 0
        self._result = {} if result is None else result
        self._exc = exc

    def __call__(self) -> dict:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


def _spy_method(obj: object, name: str, log: list[str]) -> None:
    """Wrap the bound method `name` on `obj` so every call appends `name`
    to `log` before delegating to the original — the "ledger's DB access
    boundary" the acceptance criteria ask to spy on."""
    original = getattr(obj, name)

    def wrapper(*args, **kwargs):
        log.append(name)
        return original(*args, **kwargs)

    object.__setattr__(obj, name, wrapper)


# --- AC: WRITE dispatch ordering (SELECT first, INSERT before vendor call,
# UPDATE strictly after) --------------------------------------------------


class TestFreshDispatchOrdering:
    def test_select_then_insert_then_vendor_then_update(self, session):
        shop_id, run_id = _seed_run(session)
        ledger = ToolExecutionLedger(session, shop_id=shop_id)
        log: list[str] = []
        _spy_method(ledger, "_select", log)
        _spy_method(ledger, "_insert_in_flight", log)
        _spy_method(ledger, "_mark_succeeded", log)

        def _perform():
            log.append("vendor_call")
            return {"title": "New Title"}

        result = ledger.execute_write(
            workflow_run_id=run_id,
            tool_call_id=_fresh_tool_call_id(),
            operation="update_product_listing",
            perform=_perform,
        )

        assert log == ["_select", "_insert_in_flight", "vendor_call", "_mark_succeeded"]
        assert result == {"title": "New Title"}

    def test_select_is_the_first_db_access_even_when_a_row_already_exists(self, session):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        _seed_ledger_row(
            session,
            shop_id=shop_id,
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            status=LedgerStatus.SUCCEEDED.value,
        )
        # Seeded row has no outcome_json — exercise the empty-payload path.
        ledger = ToolExecutionLedger(session, shop_id=shop_id)
        log: list[str] = []
        _spy_method(ledger, "_select", log)

        perform = _CallSpy()
        ledger.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            perform=perform,
        )

        assert log == ["_select"]
        assert perform.calls == 0


# --- AC: succeeded row replays stored result, zero vendor calls -----------


class TestSucceededReplay:
    def test_stored_result_replays_with_zero_vendor_calls(self, session):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        ledger = ToolExecutionLedger(session, shop_id=shop_id)

        first_perform = _CallSpy(result={"price": "10000"})
        first = ledger.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            perform=first_perform,
        )
        assert first_perform.calls == 1
        assert first == {"price": "10000"}

        # A different result on the second perform proves it is never even
        # glanced at, not merely uncounted.
        second_perform = _CallSpy(result={"price": "DIFFERENT-WOULD-BE-WRONG"})
        second = ledger.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            perform=second_perform,
        )

        assert second_perform.calls == 0
        assert second == {"price": "10000"}

    def test_redelivery_from_a_fresh_ledger_instance_also_replays(self, session_factory):
        """Simulates a Celery at-least-once redelivery landing on a fresh
        worker process (a new `Session`/`ToolExecutionLedger`), not just a
        second call on the same instance."""
        session1 = session_factory()
        shop_id, run_id = _seed_run(session1)
        tool_call_id = _fresh_tool_call_id()
        ledger1 = ToolExecutionLedger(session1, shop_id=shop_id)
        perform1 = _CallSpy(result={"done": True})
        ledger1.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_listing",
            perform=perform1,
        )
        session1.close()

        session2 = session_factory()
        try:
            ledger2 = ToolExecutionLedger(session2, shop_id=shop_id)
            perform2 = _CallSpy(result={"done": "WOULD-BE-WRONG"})
            result = ledger2.execute_write(
                workflow_run_id=run_id,
                tool_call_id=tool_call_id,
                operation="update_product_listing",
                perform=perform2,
            )
            assert perform2.calls == 0
            assert result == {"done": True}
        finally:
            session2.close()


# --- AC: verify-then-decide, in_flight/failed rows -------------------------


class TestVerifyThenDecideApplied:
    @pytest.mark.parametrize(
        "seeded_status", [LedgerStatus.IN_FLIGHT.value, LedgerStatus.FAILED.value]
    )
    def test_confirmed_applied_marks_succeeded_without_reexecuting(self, session, seeded_status):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        _seed_ledger_row(
            session,
            shop_id=shop_id,
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_listing",
            status=seeded_status,
        )
        ledger = ToolExecutionLedger(session, shop_id=shop_id)
        perform = _CallSpy(result={"should": "never-be-called"})

        def _verify():
            return VerifyReadBack(outcome=VerifyOutcome.APPLIED, result={"title": "Already live"})

        result = ledger.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_listing",
            perform=perform,
            verify_applied=_verify,
        )

        assert perform.calls == 0
        assert result == {"title": "Already live"}
        row = ledger._select(run_id, tool_call_id, "update_product_listing")
        assert row.status == LedgerStatus.SUCCEEDED.value

        # A later replay of this now-succeeded row also makes zero vendor calls.
        later_perform = _CallSpy(result={"title": "WOULD-BE-WRONG"})
        later = ledger.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_listing",
            perform=later_perform,
        )
        assert later_perform.calls == 0
        assert later == {"title": "Already live"}


class TestVerifyThenDecideNotApplied:
    @pytest.mark.parametrize(
        "seeded_status", [LedgerStatus.IN_FLIGHT.value, LedgerStatus.FAILED.value]
    )
    def test_confirmed_not_applied_reexecutes_exactly_once(self, session, seeded_status):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        _seed_ledger_row(
            session,
            shop_id=shop_id,
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            status=seeded_status,
        )
        ledger = ToolExecutionLedger(session, shop_id=shop_id)
        perform = _CallSpy(result={"price": "5000"})

        def _verify():
            return VerifyReadBack(outcome=VerifyOutcome.NOT_APPLIED)

        result = ledger.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            perform=perform,
            verify_applied=_verify,
        )

        assert perform.calls == 1
        assert result == {"price": "5000"}
        row = ledger._select(run_id, tool_call_id, "update_product_price")
        assert row.status == LedgerStatus.SUCCEEDED.value


def _verify_raises(exc: BaseException):
    def _verify():
        raise exc

    return _verify


def _verify_ambiguous():
    return VerifyReadBack(outcome=VerifyOutcome.UNVERIFIABLE)


class TestFailClosedOnUnverifiable:
    """ADR-073 decision 3's single most important behaviour: a
    non-verifiable in_flight/failed row never re-executes and never
    silently resolves as success — it fails closed, every time."""

    @pytest.mark.parametrize(
        "verify_applied",
        [
            pytest.param(None, id="no_verify_supplied"),
            pytest.param(_verify_raises(RuntimeError("read-back failed")), id="errors"),
            pytest.param(_verify_raises(TimeoutError("read-back timed out")), id="times_out"),
            pytest.param(_verify_ambiguous, id="ambiguous_outcome"),
        ],
    )
    @pytest.mark.parametrize(
        "seeded_status", [LedgerStatus.IN_FLIGHT.value, LedgerStatus.FAILED.value]
    )
    def test_unverifiable_fails_closed_never_reexecutes_never_succeeds(
        self, session, seeded_status, verify_applied
    ):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        _seed_ledger_row(
            session,
            shop_id=shop_id,
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_listing",
            status=seeded_status,
        )
        ledger = ToolExecutionLedger(session, shop_id=shop_id)
        perform = _CallSpy(result={"should": "never-be-returned"})

        with pytest.raises(ToolExecutionUnrecoverableError) as exc_info:
            ledger.execute_write(
                workflow_run_id=run_id,
                tool_call_id=tool_call_id,
                operation="update_product_listing",
                perform=perform,
                verify_applied=verify_applied,
            )

        assert perform.calls == 0
        assert exc_info.value.workflow_run_id == run_id
        assert exc_info.value.tool_call_id == tool_call_id
        assert exc_info.value.operation == "update_product_listing"

        row = ledger._select(run_id, tool_call_id, "update_product_listing")
        assert row.status == LedgerStatus.FAILED.value


# --- AC: unique-index race --------------------------------------------------


class TestUniqueIndexRace:
    """True concurrency is not exercisable in a single unit-test process
    (the issue text names this limitation explicitly) — simulated here with
    two sequential attempts against the same key, from two independent
    `Session`s (standing in for two worker processes)."""

    def test_second_raw_insert_with_same_key_loses_on_unique_constraint(
        self, session, session_factory
    ):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        ledger1 = ToolExecutionLedger(session, shop_id=shop_id)
        ledger1._insert_in_flight(run_id, tool_call_id, "update_product_price")

        session2 = session_factory()
        try:
            ledger2 = ToolExecutionLedger(session2, shop_id=shop_id)
            with pytest.raises(IntegrityError):
                ledger2._insert_in_flight(run_id, tool_call_id, "update_product_price")
        finally:
            session2.rollback()
            session2.close()

    def test_two_sequential_execute_write_attempts_call_vendor_at_most_once(
        self, session, session_factory
    ):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        shared_perform = _CallSpy(result={"ok": True})

        ledger1 = ToolExecutionLedger(session, shop_id=shop_id)
        result1 = ledger1.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            perform=shared_perform,
        )

        session2 = session_factory()
        try:
            ledger2 = ToolExecutionLedger(session2, shop_id=shop_id)
            result2 = ledger2.execute_write(
                workflow_run_id=run_id,
                tool_call_id=tool_call_id,
                operation="update_product_price",
                perform=shared_perform,
            )
        finally:
            session2.close()

        assert shared_perform.calls == 1
        assert result1 == result2 == {"ok": True}


# --- AC: redelivery resolves through existing branches, never a new key ---


class TestRedeliveryDoesNotAllocateANewKey:
    def test_two_attempts_same_key_leave_exactly_one_ledger_row(self, session, session_factory):
        shop_id, run_id = _seed_run(session)
        tool_call_id = _fresh_tool_call_id()
        perform = _CallSpy(result={"done": True})

        ledger1 = ToolExecutionLedger(session, shop_id=shop_id)
        ledger1.execute_write(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            operation="update_product_price",
            perform=perform,
        )

        session2 = session_factory()
        try:
            ledger2 = ToolExecutionLedger(session2, shop_id=shop_id)
            ledger2.execute_write(
                workflow_run_id=run_id,
                tool_call_id=tool_call_id,
                operation="update_product_price",
                perform=perform,
            )
            rows = (
                session2.execute(
                    select(ToolExecution).where(
                        ToolExecution.workflow_run_id == run_id,
                        ToolExecution.tool_call_id == tool_call_id,
                        ToolExecution.operation == "update_product_price",
                    )
                )
                .scalars()
                .all()
            )
        finally:
            session2.close()

        assert len(rows) == 1
        assert perform.calls == 1


# --- AC: READ never touches the ledger; WRITE routes through it only when
# the caller opts in with ledger + workflow_run_id + tool_call_id ----------


class _FakeProductsResource:
    def __init__(self) -> None:
        self.get_details_calls: list[str] = []
        self.update_prices_calls: list[tuple[str, dict]] = []

    def get_details(self, product_id: str) -> dict:
        self.get_details_calls.append(product_id)
        return {"title": "A widget", "status": "LIVE"}

    def update_prices(self, *, product_id: str, body: dict) -> dict:
        self.update_prices_calls.append((product_id, body))
        return {}


class _FakeLedger:
    """A minimal `execute_write`-shaped double — the ledger boundary the
    routing acceptance criteria spy on, independent of any real DB."""

    def __init__(self) -> None:
        self.execute_write_calls: list[dict] = []

    def execute_write(
        self, *, workflow_run_id, tool_call_id, operation, perform, verify_applied=None
    ):
        self.execute_write_calls.append(
            {
                "workflow_run_id": workflow_run_id,
                "tool_call_id": tool_call_id,
                "operation": operation,
                "verify_applied": verify_applied,
            }
        )
        return perform()


def _read_resources(products: _FakeProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _write_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        fulfillment=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


class TestToolExecutorLedgerRouting:
    def test_read_call_never_touches_the_ledger(self):
        products = _FakeProductsResource()
        ledger = _FakeLedger()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="p1",
            ledger=ledger,
            workflow_run_id=uuid.uuid4(),
        )

        result = executor.execute(
            tool_name="get_product_information",
            params=GetProductInformationInput(),
            tool_call_id="call-read-1",
        )

        assert ledger.execute_write_calls == []
        assert products.get_details_calls == ["p1"]
        assert result["status"] == "LIVE"

    def test_write_call_routes_through_the_ledger_when_configured(self):
        products = _FakeProductsResource()
        ledger = _FakeLedger()
        workflow_run_id = uuid.uuid4()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
            ledger=ledger,
            workflow_run_id=workflow_run_id,
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "1000"}]}
        )

        executor.execute(
            tool_name="update_product_price", params=params, tool_call_id="call-write-1"
        )

        assert len(ledger.execute_write_calls) == 1
        call = ledger.execute_write_calls[0]
        assert call["workflow_run_id"] == workflow_run_id
        assert call["tool_call_id"] == "call-write-1"
        assert call["operation"] == "update_product_price"
        assert products.update_prices_calls  # perform() ran, dispatched by the fake ledger

    def test_write_call_without_tool_call_id_bypasses_the_ledger(self):
        """`core.py`'s existing (pre-#1121) call site
        (`self._tool_executor.execute(tool_name=..., params=...)`) never
        passes `tool_call_id` — this must remain a direct dispatch, exactly
        as it behaved before this slice, so that call site keeps working
        unmodified."""
        products = _FakeProductsResource()
        ledger = _FakeLedger()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
            ledger=ledger,
            workflow_run_id=uuid.uuid4(),
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "1000"}]}
        )

        executor.execute(tool_name="update_product_price", params=params)

        assert ledger.execute_write_calls == []
        assert products.update_prices_calls

    def test_write_call_without_a_configured_ledger_dispatches_directly(self):
        products = _FakeProductsResource()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "1000"}]}
        )

        executor.execute(tool_name="update_product_price", params=params, tool_call_id="call-1")

        assert products.update_prices_calls
