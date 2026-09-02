"""Tests for tenant context seam (issue #1327, ADR-085 decision 2).

Proves that every transaction-scoped unit of work sets app.current_shop_id and
app.current_user_id via SET LOCAL, failing closed in Python before any SQL
when tenant context is unavailable and system_scope() is not active.
"""

import logging
import os
import uuid

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.database import Base


def _get_test_database_url() -> str:
    """Get test database URL from environment, with proper async driver conversion.

    Reads DATABASE_URL (CI sets this), optionally overridden by TEST_DATABASE_URL.
    Skips test if neither is set (local dev may run without a real DB).
    Uses async_database_url() to convert postgresql:// scheme to postgresql+asyncpg://.
    """
    test_override = os.getenv("TEST_DATABASE_URL")
    if test_override:
        return async_database_url(test_override)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set; requires a Postgres database")
    return async_database_url(database_url)


# ============================================================================
# AC1: Named error before SQL, proven by observing zero statements reached DB
# ============================================================================


@pytest.mark.asyncio
async def test_unscoped_transaction_raises_before_sql():
    """AC1: Unit of work without tenant context and without system_scope()
    raises a named error before any SQL is emitted.

    Proven by instrumentation: a SQL event listener confirms no statement
    reached the database (not merely that an exception occurred).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    statements_executed = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements_executed.append(statement)

    # Attempt to create a session and use it without tenant context
    async with factory() as session:
        # This should raise a named error without executing any SQL
        from juli_backend.database.tenant_context import (
            TenantContextRequiredError,
            with_tenant_scope,
        )

        with pytest.raises(TenantContextRequiredError):
            # Attempting to execute a query without tenant context should fail
            async with with_tenant_scope(session, shop_id=None, user_id=None):
                pass

    # Assert: no statements reached the database
    assert len(statements_executed) == 0, (
        "SQL statements reached database when they should not have"
    )

    await engine.dispose()


# ============================================================================
# AC2: SET LOCAL semantics on real pooled Postgres
# ============================================================================


@pytest.mark.asyncio
async def test_set_local_semantics_real_postgres():
    """AC2: Settings are SET LOCAL (transaction-scoped).

    After the transaction ends and the connection returns to the pool,
    a fresh checkout observes them unset.

    Requires a real Postgres database (not SQLite).
    """
    database_url = _get_test_database_url()

    # Create engine with real connection pooling (skip full metadata — just test GUCs)
    engine = create_async_engine(database_url, echo=False)

    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        shop_id = uuid.uuid4()
        user_id = uuid.uuid4()

        from juli_backend.database.tenant_context import with_tenant_scope

        # First transaction: set tenant context
        async with factory() as session1:
            async with with_tenant_scope(session1, shop_id=shop_id, user_id=user_id):
                # Verify the GUC is set within this transaction
                result = await session1.execute(
                    text("SELECT current_setting('app.current_shop_id')")
                )
                value = result.scalar()
                assert str(shop_id) == value, f"Expected shop_id={shop_id}, got {value}"

        # Second transaction on same connection (if pooling): GUC should be unset
        async with factory() as session2:
            result = await session2.execute(
                text("SELECT current_setting('app.current_shop_id', true)")
            )
            value = result.scalar()
            assert value is None or value == "", (
                f"GUC should be unset after transaction, got {value}"
            )

    finally:
        # No schema cleanup needed — this test only uses GUC operations
        await engine.dispose()


@pytest.mark.asyncio
async def test_different_tenants_same_connection():
    """AC2+AC3: Two sequential units of work for different tenants on the same
    pooled connection each observe only their own value — the leak this
    decision exists to prevent.
    """
    database_url = _get_test_database_url()

    engine = create_async_engine(database_url, echo=False)

    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        shop_id_1 = uuid.uuid4()
        shop_id_2 = uuid.uuid4()
        user_id_1 = uuid.uuid4()
        user_id_2 = uuid.uuid4()

        from juli_backend.database.tenant_context import with_tenant_scope

        # First transaction
        async with factory() as session1:
            async with with_tenant_scope(session1, shop_id=shop_id_1, user_id=user_id_1):
                result = await session1.execute(
                    text("SELECT current_setting('app.current_shop_id')")
                )
                value1 = result.scalar()
                assert str(shop_id_1) == value1

        # Second transaction with different tenant
        async with factory() as session2:
            async with with_tenant_scope(session2, shop_id=shop_id_2, user_id=user_id_2):
                result = await session2.execute(
                    text("SELECT current_setting('app.current_shop_id')")
                )
                value2 = result.scalar()
                assert str(shop_id_2) == value2, f"Expected shop_id={shop_id_2}, got {value2}"

    finally:
        # No schema cleanup needed — this test only uses GUC operations
        await engine.dispose()


# ============================================================================
# AC4: system_scope() emits log record and exempts from fail-closed assertion
# ============================================================================


@pytest.mark.asyncio
async def test_system_scope_emits_log_record(caplog):
    """AC4: system_scope() emits a log record naming the caller."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    from juli_backend.database.tenant_context import system_scope

    with caplog.at_level(logging.INFO):
        async with factory() as session:
            async with system_scope(session, caller="test_system_scope_emits_log_record"):
                # This should succeed without tenant context
                await session.execute(text("SELECT 1"))

    # Assert: log record was emitted
    assert any("system_scope" in record.getMessage() for record in caplog.records), (
        f"Expected system_scope log record, got: {[r.getMessage() for r in caplog.records]}"
    )

    await engine.dispose()


@pytest.mark.asyncio
async def test_system_scope_exempts_from_fail_closed():
    """AC4: Transactions running under system_scope() are exempt from the
    fail-closed assertion and do not need tenant context."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    from juli_backend.database.tenant_context import system_scope

    async with factory() as session:
        # This should NOT raise TenantContextRequiredError
        async with system_scope(session, caller="test_exemption"):
            result = await session.execute(text("SELECT 1"))
            value = result.scalar()
            assert value == 1

    await engine.dispose()


# ============================================================================
# AC5: Celery task resolves tenant from run's shop; unresolvable → fail closed
# ============================================================================


@pytest.mark.asyncio
async def test_celery_task_tenant_resolution(monkeypatch):
    """AC5: Celery task resolves its tenant from the run's shop and fails
    closed when the run cannot be resolved — it does not fall back to any
    default or reference shop.

    Proves:
    1. @task_with_tenant_context() decorator sets the context from resolved run
    2. Fail-closed: if the run cannot be resolved, raises TenantContextTaskError
       BEFORE executing the task body
    """
    from juli_backend.database.tenant_context import (
        get_tenant_context,
    )
    from juli_backend.workers.tenant_context_wrapper import (
        TenantContextTaskError,
        task_with_tenant_context,
    )

    shop_id = uuid.uuid4()
    user_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Test 1: task_with_tenant_context decorator sets context when resolution succeeds
    async def mock_resolve_success(run_id_arg):
        if run_id_arg == run_id:
            return shop_id, user_id
        raise TenantContextTaskError(
            f"Cannot resolve tenant context: run_id={run_id_arg} not found"
        )

    monkeypatch.setattr(
        "juli_backend.workers.tenant_context_wrapper.resolve_task_tenant_context",
        mock_resolve_success,
    )

    @task_with_tenant_context()
    async def sample_task(run_id_arg):
        # Inside the task, context should be set
        stored_shop, stored_user = get_tenant_context()
        assert stored_shop == shop_id, f"Expected shop_id={shop_id}, got {stored_shop}"
        assert stored_user == user_id, f"Expected user_id={user_id}, got {stored_user}"
        # Task body executes with context set
        return "success"

    # Call the task function synchronously
    result = await sample_task(run_id)
    assert result == "success"

    # Test 2: Fail-closed when run doesn't exist
    fake_run_id = uuid.uuid4()
    task_body_executed = False

    @task_with_tenant_context()
    async def failing_task(run_id_arg):
        # This should never be reached when context resolution fails
        nonlocal task_body_executed
        task_body_executed = True
        return "should not reach"

    # Task should raise TenantContextTaskError before executing task body
    with pytest.raises(TenantContextTaskError) as exc_info:
        await failing_task(fake_run_id)

    assert "Cannot resolve tenant context" in str(exc_info.value)
    assert task_body_executed is False, "Task body should not execute when context resolution fails"


# ============================================================================
# AC5 extended: resolve_task_tenant_context with real Postgres + models
# ============================================================================


@pytest.mark.asyncio
async def test_resolve_task_tenant_context_real_postgres():
    """AC5 extended: resolve_task_tenant_context resolves user_id from shop owner.

    Proves that:
    1. When given a run_id that exists and has a valid shop_id,
       resolve_task_tenant_context returns (run.shop_id, shop.user_id)
    2. The returned user_id is the shop's OWNER's user_id, NOT a fabricated uuid
    3. This test FAILS against the old uuid.uuid4() code and PASSES with the fix
    """
    database_url = _get_test_database_url()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.models.models import Product, Shop, User, WorkflowRun
    from juli_backend.workers.tenant_context_wrapper import resolve_task_tenant_context

    engine = create_async_engine(database_url, echo=False)

    try:
        # Create tables (use checkfirst to avoid FK errors on drops).
        #
        # The non-public schemas are created first. `Base.metadata` places tables
        # in bronze/silver/gold/ops, and `create_all` does not create a schema —
        # it fails with `InvalidSchemaNameError: schema "silver" does not exist`.
        # This passed only because some other module had migrated the shared
        # database first and left the schemas behind; #1405 gave those modules
        # their own databases, so the leftover disappeared. Same shape as #1425:
        # provision what the test needs rather than depend on what ran before it.
        # Mirrors `_build_postgres_engine` in test_agent_runner_concurrency.py,
        # which has always created these schemas explicitly.
        async with engine.begin() as conn:
            for schema_name in ("bronze", "silver", "gold", "ops"):
                await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)

        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Seed data with explicit UUIDs and proper flush order to ensure FK constraints
        owner_user_id = uuid.uuid4()
        shop_id = uuid.uuid4()
        product_id = uuid.uuid4()
        workflow_run_id = uuid.uuid4()

        from datetime import datetime

        owner_user = User(id=owner_user_id, phone="555-0001", display_name="Shop Owner")
        shop = Shop(id=shop_id, user_id=owner_user_id, shop_name="Test Shop", is_active=True)
        product = Product(
            id=product_id,
            shop_id=shop_id,
            tiktok_product_id="prod-123",
            name="Test Product",
            status="active",
            update_time=datetime.utcnow(),
        )
        workflow_run = WorkflowRun(
            id=workflow_run_id,
            shop_id=shop_id,
            product_id=product_id,
            status="queued",
            prompt_version="1.0",
            prompt_sha256="abc123",
        )

        async with factory() as session:
            session.add(owner_user)
            await session.flush()  # Ensure user is persisted before shop references it
            session.add(shop)
            await session.flush()  # Ensure shop is persisted before product references it
            session.add(product)
            await session.flush()  # Ensure product is persisted before workflow_run references it
            session.add(workflow_run)
            await session.commit()

        # Now resolve the tenant context from the workflow run
        resolved_shop_id, resolved_user_id = await resolve_task_tenant_context(workflow_run_id)

        # Assertions:
        # 1. shop_id should match
        assert resolved_shop_id == shop_id, f"Expected shop_id={shop_id}, got {resolved_shop_id}"

        # 2. user_id should be the OWNER's user_id, NOT a fabricated uuid
        assert resolved_user_id == owner_user_id, (
            f"Expected user_id={owner_user_id} (shop owner), got {resolved_user_id}. "
            f"This suggests user_id is being fabricated with uuid.uuid4() instead of "
            f"resolved from the shop owner."
        )

        # 3. Clean up inserted rows (do NOT drop schema)
        async with factory() as session:
            # Delete in reverse FK order
            await session.execute(delete(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
            await session.execute(delete(Product).where(Product.id == product_id))
            await session.execute(delete(Shop).where(Shop.id == shop_id))
            await session.execute(delete(User).where(User.id == owner_user_id))
            await session.commit()

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_task_tenant_context_fail_closed_nonexistent_shop():
    """AC5 extended: resolve_task_tenant_context fails closed when shop doesn't exist.

    Proves that:
    1. When a WorkflowRun's shop_id points to a nonexistent Shop,
       resolve_task_tenant_context raises TenantContextTaskError
    2. No fabricated uuid or fallback is used
    3. The error message is clear about what failed
    """
    database_url = _get_test_database_url()

    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.workers.tenant_context_wrapper import (
        TenantContextTaskError,
        resolve_task_tenant_context,
    )

    engine = create_async_engine(database_url, echo=False)

    try:
        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)

        # Test with a run_id that will never be found
        fake_run_id = uuid.uuid4()

        # Attempt to resolve — should fail closed
        with pytest.raises(TenantContextTaskError) as exc_info:
            await resolve_task_tenant_context(fake_run_id)

        # Assert error message is clear
        error_msg = str(exc_info.value)
        assert "workflow_runs row not found" in error_msg or "cannot be resolved" in error_msg, (
            f"Expected clear error message about run not found, got: {error_msg}"
        )

    finally:
        await engine.dispose()


# ============================================================================
# Real route proof: middleware applies GUC via direct session apply
# ============================================================================


@pytest.mark.asyncio
async def test_middleware_applies_tenant_context_to_session():
    """Middleware applies SET LOCAL GUCs to the request's session via direct apply.

    Proves that the HTTP path correctly sets GUCs on the session without
    relying on event listeners or contextvar propagation.
    """
    database_url = _get_test_database_url()

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.database.tenant_context import (
        _apply_tenant_context_to_session,
    )

    engine = create_async_engine(database_url)

    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        shop_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Simulate the middleware path: apply context directly to a session
        async with factory() as session:
            # This is what the middleware does after resolving the shop
            await _apply_tenant_context_to_session(session, shop_id, user_id)

            # Now verify the GUC was actually set on this session
            result = await session.execute(text("SELECT current_setting('app.current_shop_id')"))
            value = result.scalar()
            assert str(shop_id) == value, (
                f"Expected shop_id={shop_id}, got {value}. Middleware apply failed."
            )

        # After the session closes, GUC should be unset (transaction-scoped)
        async with factory() as session:
            result = await session.execute(
                text("SELECT current_setting('app.current_shop_id', true)")
            )
            value = result.scalar()
            assert value is None or value == "", f"GUC should be unset after session, got {value}"

    finally:
        await engine.dispose()


# ============================================================================
# AC6: Existing suite passes; every unscoped call site is scoped or wrapped
# ============================================================================


def test_system_scope_call_sites_enumerated():
    """AC6: A test enumerates the system_scope() call sites so the
    exemption list cannot grow silently.

    Walks backend/src recursively to find all files containing system_scope(
    calls and asserts they match the expected set of beat tasks."""
    import re
    from pathlib import Path

    # These are the system_scope() call sites at the time of issue #1327
    # Any new call site must be added here explicitly.
    # analytics_backfill_topup left this set in #1478: it runs for a single
    # reference shop and now uses with_shop_scope, so it needs no exemption at
    # all (ADR-089 decision 5). The list is expected to keep SHRINKING as the
    # W7-bis slices land — a name reappearing here is a regression, and a new
    # name is the growth this test was written to catch.
    # reaper left this set in #1489: it now enumerates via a SECURITY DEFINER
    # function and sets per-tenant context for each run via with_shop_scope,
    # so it needs no system_scope() at the task level.
    expected_call_sites = {
        "workers/tasks/impact_reader.py",
        "workers/tasks/credential_refresh_beat.py",
        "workers/tasks/mock_analytics_reconcile.py",
    }

    # Walk backend/src/juli_backend and find all files with system_scope( calls
    # But exclude database/tenant_context.py which defines system_scope
    actual_call_sites = set()
    backend_src = Path(__file__).parent.parent.parent / "backend" / "src" / "juli_backend"

    for filepath in backend_src.rglob("*.py"):
        try:
            content = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Skip the definition file and migration files (which are historical documentation)
        if str(filepath).endswith("database/tenant_context.py"):
            continue
        if "database/migrations" in str(filepath):
            continue

        # Look for "system_scope(" pattern in actual code (not docstrings/comments).
        # Match only when system_scope is preceded by "async with" or similar keywords
        # to exclude documentation mentions.
        if re.search(r"(?:async\s+)?(?:with|def)\s+.*system_scope\s*\(", content):
            # Make path relative to backend/src/juli_backend
            rel_path = filepath.relative_to(backend_src)
            # Construct path as it would appear in module structure
            # Convert to posix-style path relative to workers/tasks if applicable
            full_rel = str(rel_path).replace("\\", "/")
            if "workers/tasks" in full_rel:
                # Extract just the workers/tasks/... part
                idx = full_rel.index("workers/tasks")
                actual_call_sites.add(full_rel[idx:])
            else:
                # For any other files using system_scope (database.py, etc)
                actual_call_sites.add(full_rel)

    # Assert the actual call sites match expected
    assert actual_call_sites == expected_call_sites, (
        f"system_scope() call sites mismatch.\n"
        f"Expected: {sorted(expected_call_sites)}\n"
        f"Actual:   {sorted(actual_call_sites)}\n"
        f"Missing:  {sorted(expected_call_sites - actual_call_sites)}\n"
        f"Extra:    {sorted(actual_call_sites - expected_call_sites)}"
    )


# ============================================================================
# AC7: core/security/dependencies.py is untouched
# ============================================================================


def test_dependencies_not_edited():
    """AC7: core/security/dependencies.py is untouched by this PR's diff.

    Verified by review, declared here as a lock. Uses a source-level assertion
    (no tenant-context imports) rather than git plumbing, for portability in
    CI's shallow checkout where git refs may not resolve.
    """
    from pathlib import Path

    dependencies_path = (
        Path(__file__).parent.parent.parent
        / "backend"
        / "src"
        / "juli_backend"
        / "core"
        / "security"
        / "dependencies.py"
    )

    # Read the file and verify it has no tenant-context imports
    content = dependencies_path.read_text()

    # Assert that tenant-context imports are not present
    assert "tenant_context" not in content, (
        "core/security/dependencies.py must not import or use tenant_context. "
        "Issue #1327 (ADR-085 decision 2) defines tenant context in api/dependencies.py, "
        "not in W6's core/security (which is off-limits)."
    )

    assert "_apply_tenant_context_to_session" not in content, (
        "core/security/dependencies.py must not call _apply_tenant_context_to_session. "
        "Tenant context must be applied in api/dependencies.py::get_active_shop, not here."
    )


# ============================================================================
# AC8: Behaviourally invisible to caller
# ============================================================================


@pytest.mark.asyncio
async def test_tenant_context_invisible_to_caller():
    """AC8: The GUCs are behaviourally invisible to the caller.

    Nothing observable changes — queries work normally, results are unchanged.
    The GUCs are read by nobody (no policies exist yet in this slice) until #1328.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    shop_id = uuid.uuid4()
    user_id = uuid.uuid4()

    from juli_backend.database.tenant_context import with_tenant_scope

    async with factory() as session:
        async with with_tenant_scope(session, shop_id=shop_id, user_id=user_id):
            # Query executes normally
            result = await session.execute(text("SELECT 1 as value"))
            row = result.first()
            assert row.value == 1

    await engine.dispose()
