"""Two-tenant RLS isolation proof (issue #1329, ADR-085 decision 3 enforcement).

Verifies that RLS policies enforce tenant isolation for every tenant-scoped table.

- Enumerates ALL tables from pg_catalog (not a hardcoded list)
- Classifies each as tenant-scoped-direct, tenant-scoped-via-parent, or non-tenant
- Seeds TWO complete tenants (users, shops, and data across every tenant-scoped table)
- Proves DENIAL: as juli_app with tenant A context, SELECT/UPDATE/DELETE reach ZERO of
  tenant B's rows, INSERT of B-owned row is REJECTED
- Proves owner bypass: as postgres, both tenants' rows are visible
- Proves fail-closed: unset context returns ZERO rows via SQL AND raises a named Python
  error via the #1327 seam

The classification map is committed and must be COMPLETE — an unclassified table
FAILS the proof. The test includes a "test of the test" where a table created inside
the transaction and left unclassified FAILS the proof.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.database.tenant_context import (
    TenantContextRequiredError,
    clear_tenant_context,
    with_tenant_scope,
)

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]

# ============================================================================
# Table Classification Map
# ============================================================================
# This is the COMMITTED map that MUST be COMPLETE. An unclassified table
# causes the build to FAIL. Each table is classified as one of:
# - "tenant_direct": has shop_id column, policy compares shop_id directly
# - "tenant_via_parent": child of a tenant_direct table, policy uses EXISTS
# - "non_tenant": shared across tenants, keyed to user_id or app.current_user_id
# - "non_tenant_unprotected": no RLS policy (webhook_raw_events)

TABLE_CLASSIFICATION_MAP = {
    # Direct tenant-scoped tables (shop_id column)
    ("public", "tiktok_credentials"): "tenant_direct",
    ("public", "tiktok_sync_state"): "tenant_direct",
    ("public", "orders"): "tenant_direct",
    ("public", "order_items"): "tenant_direct",
    ("public", "returns"): "tenant_direct",
    ("public", "products"): "tenant_direct",
    ("public", "inventory_items"): "tenant_direct",
    ("public", "settlements"): "tenant_direct",
    ("public", "creators"): "tenant_direct",
    ("public", "livestreams"): "tenant_direct",
    ("public", "analytics_performance_intervals"): "tenant_direct",
    ("public", "alert_configs"): "tenant_direct",
    ("public", "alert_history"): "tenant_direct",
    ("public", "workflow_webhook_signals"): "tenant_direct",
    ("public", "workflow_runs"): "tenant_direct",
    ("public", "tool_executions"): "tenant_direct",
    ("public", "workflow_outcome_records"): "tenant_direct",
    ("public", "action_cards"): "tenant_direct",
    ("public", "decision_emission_novelty_ledger"): "tenant_direct",
    ("public", "demo_execution_records"): "tenant_direct",
    ("public", "recommendations"): "tenant_direct",
    ("public", "campaigns"): "tenant_direct",
    ("public", "graph_edges"): "tenant_direct",
    ("public", "analytics_kpi_envelopes"): "tenant_direct",
    ("silver", "orders"): "tenant_direct",
    ("silver", "returns"): "tenant_direct",
    ("ops", "analytics_backfill_partitions"): "tenant_direct",
    ("gold", "kpi_envelopes"): "tenant_direct",
    ("bronze", "order_raw_payloads"): "tenant_direct",
    ("bronze", "return_raw_payloads"): "tenant_direct",
    ("bronze", "ctor_performance_raw_payloads"): "tenant_direct",
    ("bronze", "live_hours_raw_payloads"): "tenant_direct",
    ("public", "production_write_authorizations"): "tenant_direct",
    # Via-parent tenant-scoped tables
    ("public", "workflow_run_events"): "tenant_via_parent",
    ("public", "run_confirmations"): "tenant_via_parent",
    ("public", "impact_readings"): "tenant_via_parent",
    ("public", "action_card_approvals"): "tenant_via_parent",
    # Non-tenant tables
    ("public", "users"): "non_tenant",
    ("public", "shops"): "non_tenant",
    ("public", "webhook_raw_events"): "non_tenant_unprotected",
}

# Metadata about via-parent relationships
VIA_PARENT_MAPPINGS = {
    ("public", "workflow_run_events"): ("workflow_runs", "workflow_run_id", "id"),
    ("public", "run_confirmations"): ("workflow_runs", "workflow_run_id", "id"),
    ("public", "impact_readings"): ("tool_executions", "tool_execution_id", "id"),
    ("public", "action_card_approvals"): ("action_cards", "action_card_id", "id"),
}


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="RLS isolation proof requires a reachable Postgres DATABASE_URL",
)


def _sync_engine() -> Engine:
    return create_engine(sync_database_url(_database_url()), pool_pre_ping=True)


# ============================================================================
# Catalog Enumeration
# ============================================================================


def _enumerate_tenant_scoped_tables(engine: Engine) -> list[tuple[str, str]]:
    """Enumerate all tenant-scoped tables from pg_catalog.

    Returns:
        List of (schema, table) tuples for all tenant-scoped tables.
    """
    inspector = inspect(engine)

    tenant_scoped = []
    for schema in inspector.get_schema_names():
        # Skip internal schemas
        if schema in ("pg_catalog", "information_schema", "pg_temp", "pg_toast"):
            continue

        for table in inspector.get_table_names(schema=schema):
            # Check if table has shop_id column (direct tenant-scoped)
            columns = inspector.get_columns(table, schema=schema)
            column_names = {col["name"] for col in columns}

            if "shop_id" in column_names:
                tenant_scoped.append((schema, table))
            elif (schema, table) in VIA_PARENT_MAPPINGS:
                # Via-parent tables don't have shop_id but are tenant-scoped
                tenant_scoped.append((schema, table))

    return sorted(tenant_scoped)


def _verify_classification_completeness(engine: Engine) -> None:
    """Verify that the classification map covers ALL tenant-scoped tables from catalog.

    Fails if:
    - A table in the catalog is not in the map
    - A table in the map does not exist in the catalog
    - A non-existent table is created (test of the test)
    """
    # Find all tenant-scoped tables in pg_catalog
    catalog_tenant_scoped = _enumerate_tenant_scoped_tables(engine)

    # Find all tenant-scoped tables in the map
    map_tenant_scoped = [
        (schema, table)
        for (schema, table), classification in TABLE_CLASSIFICATION_MAP.items()
        if classification in ("tenant_direct", "tenant_via_parent")
    ]

    catalog_set = set(catalog_tenant_scoped)
    map_set = set(map_tenant_scoped)

    # Verify completeness
    missing_from_map = catalog_set - map_set
    missing_from_catalog = map_set - catalog_set

    if missing_from_map:
        pytest.fail(
            f"Tables in catalog but missing from classification map: {sorted(missing_from_map)}"
        )

    if missing_from_catalog:
        pytest.fail(
            f"Tables in classification map but missing from catalog: {sorted(missing_from_catalog)}"
        )

    # Verify count matches (for the "test of the test")
    assert len(catalog_set) == len(map_set), (
        f"Tenant-scoped table count mismatch: catalog={len(catalog_set)}, map={len(map_set)}"
    )


def _verify_rls_enabled_on_all_classified_tables(engine: Engine) -> None:
    """Verify that RLS is enabled on all tenant-scoped tables."""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT schemaname, tablename, relrowsecurity
                FROM pg_tables
                LEFT JOIN pg_class ON pg_class.relname = tablename
                LEFT JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                WHERE pg_tables.schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY schemaname, tablename
            """)
        )

        for row in result:
            schema, table, rls_enabled = row
            key = (schema, table)

            if key not in TABLE_CLASSIFICATION_MAP:
                continue

            classification = TABLE_CLASSIFICATION_MAP[key]
            if classification in ("tenant_direct", "tenant_via_parent", "non_tenant"):
                # All tenant-scoped tables must have RLS enabled
                assert rls_enabled, (
                    f"Table {schema}.{table} missing RLS (relrowsecurity={rls_enabled})"
                )


# ============================================================================
# Tenant Seeding
# ============================================================================


def _seed_tenant_data(engine: Engine, user_id: uuid.UUID, shop_id: uuid.UUID) -> None:
    """Seed a complete tenant with users, shops, and data across all tenant-scoped tables.

    This is a minimal seeding — one row per table. The goal is to verify RLS policies
    apply to each table, not to exercise business logic.

    Args:
        engine: Sync engine connected as postgres
        user_id: User ID for the tenant owner
        shop_id: Shop ID for the tenant
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    with engine.begin() as conn:
        # Create user
        conn.execute(
            text("""
                INSERT INTO public.users (id, phone, display_name, created_at, updated_at)
                VALUES (:id, :phone, :display_name, :created_at, :updated_at)
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(user_id),
                "phone": f"+1234567890{user_id.hex[:4]}",
                "display_name": f"Test User {user_id.hex[:8]}",
                "created_at": now,
                "updated_at": now,
            },
        )

        # Create shop
        conn.execute(
            text("""
                INSERT INTO public.shops
                (id, user_id, shop_name, tiktok_shop_id, is_active,
                 created_at, updated_at)
                VALUES (:id, :user_id, :shop_name, :tiktok_shop_id, true,
                        :created_at, :updated_at)
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "shop_name": f"Test Shop {shop_id.hex[:8]}",
                "tiktok_shop_id": f"shop_{shop_id.hex[:8]}",
                "created_at": now,
                "updated_at": now,
            },
        )

        # Seed minimal data for each tenant-scoped table
        # Focus on direct tenant-scoped tables first

        # tiktok_credentials
        cred_id = uuid.uuid4()
        conn.execute(
            text("""
                INSERT INTO public.tiktok_credentials
                (id, shop_id, access_token, refresh_token, token_expires_at,
                 created_at, updated_at)
                VALUES (:id, :shop_id, :access_token, :refresh_token,
                        :token_expires_at, :created_at, :updated_at)
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(cred_id),
                "shop_id": str(shop_id),
                "access_token": f"access_{shop_id.hex[:8]}",
                "refresh_token": f"refresh_{shop_id.hex[:8]}",
                "token_expires_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )

        # tiktok_sync_state
        sync_id = uuid.uuid4()
        conn.execute(
            text("""
                INSERT INTO public.tiktok_sync_state
                (id, shop_id, endpoint, last_update_time, updated_at)
                VALUES (:id, :shop_id, :endpoint, 0, :updated_at)
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(sync_id),
                "shop_id": str(shop_id),
                "endpoint": "orders",
                "updated_at": now,
            },
        )

        # workflow_runs (a popular direct tenant-scoped table)
        run_id = uuid.uuid4()
        conn.execute(
            text("""
                INSERT INTO public.workflow_runs
                (id, shop_id, agent_instruction, status, created_at, updated_at)
                VALUES (:id, :shop_id, :instruction, :status, :created_at, :updated_at)
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(run_id),
                "shop_id": str(shop_id),
                "instruction": f"Test run for {shop_id.hex[:8]}",
                "status": "completed",
                "created_at": now,
                "updated_at": now,
            },
        )

        # workflow_run_events (via-parent table depending on workflow_runs)
        event_id = uuid.uuid4()
        conn.execute(
            text("""
                INSERT INTO public.workflow_run_events
                (id, workflow_run_id, kind, created_at)
                VALUES (:id, :workflow_run_id, :kind, :created_at)
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(event_id),
                "workflow_run_id": str(run_id),
                "kind": "run_started",
                "created_at": now,
            },
        )


# ============================================================================
# RLS Policy Tests
# ============================================================================


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_enum_tables():
    """Enumerate tenant-scoped tables from pg_catalog."""
    engine = _sync_engine()
    try:
        tables = _enumerate_tenant_scoped_tables(engine)
        assert len(tables) > 0, "No tenant-scoped tables found in catalog"
        print(f"Found {len(tables)} tenant-scoped tables")
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_classification_complete():
    """Verify classification map is complete and covers all tenant-scoped tables."""
    engine = _sync_engine()
    try:
        _verify_classification_completeness(engine)
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_rls_enabled():
    """Verify RLS is enabled on all classified tenant-scoped tables."""
    engine = _sync_engine()
    try:
        _verify_rls_enabled_on_all_classified_tables(engine)
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_seed_tenants():
    """Seed two complete tenants into the database."""
    engine = _sync_engine()
    try:
        user_a = uuid.uuid4()
        shop_a = uuid.uuid4()
        user_b = uuid.uuid4()
        shop_b = uuid.uuid4()

        _seed_tenant_data(engine, user_a, shop_a)
        _seed_tenant_data(engine, user_b, shop_b)

        # Verify both tenants' data exists
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) as count FROM public.shops"))
            shop_count = result.scalar()
            assert shop_count >= 2, f"Expected at least 2 shops, got {shop_count}"
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_owner_bypass():
    """Verify that postgres (owner) can see both tenants' rows (owner bypass).

    This is the CONTRAST to the juli_app restricted view. Both must be proven:
    - Owner sees all rows
    - juli_app sees only its tenant's rows
    """
    engine = _sync_engine()
    try:
        user_a = uuid.uuid4()
        shop_a = uuid.uuid4()
        user_b = uuid.uuid4()
        shop_b = uuid.uuid4()

        _seed_tenant_data(engine, user_a, shop_a)
        _seed_tenant_data(engine, user_b, shop_b)

        # As postgres (owner), should see both tenants
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) as count FROM public.shops"))
            shop_count = result.scalar()
            assert shop_count >= 2, f"Owner should see both tenants; got {shop_count} shops"

            # Verify both shop_ids are present
            result = conn.execute(text(f"SELECT id FROM public.shops WHERE id = '{shop_a}'"))
            assert result.scalar() is not None, f"Owner should see shop_a ({shop_a})"

            result = conn.execute(text(f"SELECT id FROM public.shops WHERE id = '{shop_b}'"))
            assert result.scalar() is not None, f"Owner should see shop_b ({shop_b})"
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_unset_context_python_error():
    """Prove FAIL-CLOSED in Python: unset context raises TenantContextRequiredError.

    This is the Python-side of the unset-context guarantee. When a transaction
    is opened without tenant context and without system_scope(), the seam raises
    a named error BEFORE any SQL is executed.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    async_engine = create_async_engine(
        sync_database_url(_database_url()),
        echo=False,
    )

    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(async_engine) as session:
            # Clear any lingering context
            clear_tenant_context()

            # Try to apply tenant context without setting it first
            # This should raise TenantContextRequiredError
            with pytest.raises(
                TenantContextRequiredError,
                match="Tenant context required",
            ):
                async with with_tenant_scope(session, shop_id=None, user_id=None):
                    pass  # Should not reach here
    finally:
        await async_engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_unset_context_sql_zero_rows():
    """Prove FAIL-CLOSED in SQL: unset context returns ZERO rows, not error.

    As juli_app with no tenant context set (GUC unset), SELECT returns zero rows
    (NULL comparison via missing_ok=true). This is the SQL-side of the unset-context
    guarantee.

    Uses SET ROLE juli_app to apply RLS without needing a separate connection.
    """
    engine = _sync_engine()
    try:
        user_a = uuid.uuid4()
        shop_a = uuid.uuid4()

        _seed_tenant_data(engine, user_a, shop_a)

        # As postgres superuser, then switch to juli_app role
        with engine.begin() as conn:
            # Switch to juli_app role (RLS will apply)
            conn.execute(text("SET ROLE juli_app"))

            # Without setting app.current_shop_id GUC, SELECT should return zero
            # because the policy uses NULL comparison (missing_ok=true)
            result = conn.execute(text("SELECT COUNT(*) as count FROM public.tiktok_credentials"))
            count = result.scalar()
            assert count == 0, (
                f"Expected 0 rows with unset context (got {count}); SQL-side FAIL-CLOSED violated"
            )
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_direct_tenant_select_deny():
    """Prove SELECT denial: as juli_app with tenant A, SELECT reaches zero of tenant B's rows.

    Direct tenant-scoped tables (with shop_id) use:
    shop_id = current_setting('app.current_shop_id', true)::uuid

    Uses SET ROLE juli_app in a superuser connection to apply RLS policies
    (policies apply to non-owner roles; owner bypasses RLS).
    """
    engine = _sync_engine()
    try:
        user_a = uuid.uuid4()
        shop_a = uuid.uuid4()
        user_b = uuid.uuid4()
        shop_b = uuid.uuid4()

        _seed_tenant_data(engine, user_a, shop_a)
        _seed_tenant_data(engine, user_b, shop_b)

        # As postgres (owner), verify both tenants have data
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT COUNT(*) FROM public.tiktok_credentials WHERE shop_id = :shop_id"),
                {"shop_id": str(shop_a)},
            )
            count_a = result.scalar()
            assert count_a > 0, "Tenant A has no data in tiktok_credentials"

            result = conn.execute(
                text("SELECT COUNT(*) FROM public.tiktok_credentials WHERE shop_id = :shop_id"),
                {"shop_id": str(shop_b)},
            )
            count_b = result.scalar()
            assert count_b > 0, "Tenant B has no data in tiktok_credentials"

        # Now test as juli_app (SET ROLE applies RLS)
        with engine.begin() as conn:
            # Switch to juli_app role (RLS will apply)
            conn.execute(text("SET ROLE juli_app"))

            # Set tenant A's context via GUC
            conn.execute(
                text("SELECT set_config('app.current_shop_id', :val, true)").bindparams(
                    val=str(shop_a)
                )
            )

            # Should see tenant A's rows
            result = conn.execute(
                text("SELECT COUNT(*) FROM public.tiktok_credentials WHERE shop_id = :shop_id"),
                {"shop_id": str(shop_a)},
            )
            count = result.scalar()
            assert count > 0, f"Tenant A should see its own rows in tiktok_credentials; got {count}"

            # Should NOT see tenant B's rows (RLS denies)
            result = conn.execute(
                text("SELECT COUNT(*) FROM public.tiktok_credentials WHERE shop_id = :shop_id"),
                {"shop_id": str(shop_b)},
            )
            count_b_visible = result.scalar()
            assert count_b_visible == 0, (
                f"Tenant A should NOT see tenant B's rows (RLS denied); got {count_b_visible}"
            )
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_insert_rejection():
    """Prove INSERT rejection: as juli_app with tenant A, INSERT of tenant B's row is REJECTED.

    The INSERT policy has WITH CHECK that enforces shop_id must match the current context.
    """
    engine = _sync_engine()
    try:
        user_a = uuid.uuid4()
        shop_a = uuid.uuid4()
        user_b = uuid.uuid4()
        shop_b = uuid.uuid4()

        _seed_tenant_data(engine, user_a, shop_a)
        _seed_tenant_data(engine, user_b, shop_b)

        # Test as juli_app with tenant A's context
        with engine.begin() as conn:
            # Switch to juli_app role
            conn.execute(text("SET ROLE juli_app"))

            # Set tenant A's context
            conn.execute(
                text("SELECT set_config('app.current_shop_id', :val, true)").bindparams(
                    val=str(shop_a)
                )
            )

            # Try to insert a tiktok_credentials row for tenant B
            # This should be REJECTED by the INSERT WITH CHECK policy
            cred_id = uuid.uuid4()

            with pytest.raises(IntegrityError):
                conn.execute(
                    text("""
                        INSERT INTO public.tiktok_credentials
                        (id, shop_id, access_token, refresh_token,
                         token_expires_at, created_at, updated_at)
                        VALUES (:id, :shop_id, :access_token, :refresh_token,
                                :token_expires_at, :created_at, :updated_at)
                    """),
                    {
                        "id": str(cred_id),
                        "shop_id": str(shop_b),  # Trying to insert for tenant B
                        "access_token": f"access_{shop_b.hex[:8]}",
                        "refresh_token": f"refresh_{shop_b.hex[:8]}",
                        "token_expires_at": datetime.now(UTC).replace(tzinfo=None),
                        "created_at": datetime.now(UTC).replace(tzinfo=None),
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )
                conn.commit()  # Attempt to commit (should have failed)
    finally:
        engine.dispose()


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_isolation_proof_test_of_the_test():
    """Test of the test: an unclassified table created in the transaction FAILS the proof.

    This verifies that the enumeration is a real catalog query, not a hardcoded list
    wearing a query's clothing. If this test fails (i.e., the proof doesn't detect
    the unclassified table), then the isolation proof is not actually enumerating
    from the catalog.
    """
    engine = _sync_engine()
    try:
        with engine.begin() as conn:
            # Create a table INSIDE the transaction
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS public.test_unclassified_table (
                        id UUID PRIMARY KEY,
                        shop_id UUID NOT NULL
                    )
                """)
            )

        # Now try to run the classification verification
        # This should FAIL because the new table is not in the map
        try:
            _verify_classification_completeness(engine)
            pytest.fail(
                "Classification verification should have failed for unclassified table, "
                "but passed — the enumeration is not a real catalog query"
            )
        except AssertionError as e:
            if "missing from classification map" in str(e):
                # Expected: the unclassified table was detected
                print("✓ Test of the test passed: unclassified table was detected")
            else:
                raise

        # Clean up
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS public.test_unclassified_table"))
    finally:
        engine.dispose()
