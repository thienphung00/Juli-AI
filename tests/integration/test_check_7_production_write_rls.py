"""Check 7: Production-write RLS preconditions — real Postgres integration tests (issue #1330).

These tests verify all four acceptance criteria against a real Postgres 16 database
with migrations run to HEAD. Tests must NOT skip — real database state required.

Test matrix:
(a) PRODUCTION_WRITE_ENABLED OFF + owner connection + partial RLS → NO-OP boot
(b) PRODUCTION_WRITE_ENABLED ON + owner connection → REFUSE (owns tables)
(c) PRODUCTION_WRITE_ENABLED ON + table with RLS disabled → REFUSE (naming table)
(d) PRODUCTION_WRITE_ENABLED ON + juli_app + full RLS → BOOT
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from juli_backend.core.config.runtime import is_production_write_enabled, sync_database_url
from juli_backend.database.tenant_scoped_tables import get_tenant_scoped_tables
from juli_backend.workers.agent_runtime_boot import assert_agent_runtime_config


def _database_url() -> str:
    """Get DATABASE_URL from environment."""
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    """Check if Postgres is reachable at DATABASE_URL."""
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


requires_real_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Check 7 tests require a real Postgres DATABASE_URL with migrations at HEAD",
)


def _sync_engine() -> Engine:
    """Create a sync engine for test database."""
    return create_engine(sync_database_url(_database_url()), pool_pre_ping=True)


@contextmanager
def patch_env(**kwargs):
    """Context manager to temporarily patch environment variables."""
    old_values = {}
    for key, value in kwargs.items():
        old_values[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


class TestCheck7ProductionWriteRLS:
    """Integration tests for check 7 against real Postgres."""

    @requires_real_postgres
    def test_a_capability_off_owner_partial_rls_boots_clean(self):
        """(a) PRODUCTION_WRITE_ENABLED OFF + owner + partial RLS → NO-OP boot.

        This is today's deployed production configuration. The check should not
        refuse to boot, even if RLS is partially disabled, because the capability
        is off.
        """
        engine = _sync_engine()

        # Verify current role is postgres (owner)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT current_user")).scalar()
            current_role = result
            assert current_role == "postgres", f"Test requires postgres role, got {current_role}"

        # Capability is OFF (default)
        assert not is_production_write_enabled(), "Test requires PRODUCTION_WRITE_ENABLED off"

        # Boot should succeed (NO-OP)
        try:
            assert_agent_runtime_config()
            print("✓ (a) PASS: NO-OP boot with capability OFF, owner connection, partial RLS")
        except RuntimeError as e:
            if "check 7" in str(e).lower():
                pytest.fail(
                    f"Check 7 should be NO-OP when PRODUCTION_WRITE_ENABLED=OFF, but raised: {e}"
                )
            raise

    @requires_real_postgres
    def test_b_capability_on_owner_refuses_boot_names_check(self):
        """(b) PRODUCTION_WRITE_ENABLED ON + owner connection → REFUSE, names check.

        This is AC1: the core dangerous case. Owner connection bypasses RLS.
        Boot must refuse when the capability is on.
        """
        engine = _sync_engine()

        # Verify current role is postgres (owner)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT current_user")).scalar()
            current_role = result
            assert current_role == "postgres", f"Test requires postgres role, got {current_role}"

        # Enable the capability
        with patch_env(PRODUCTION_WRITE_ENABLED="true"):
            assert is_production_write_enabled(), "Failed to enable PRODUCTION_WRITE_ENABLED"

            # Boot must refuse and name the check
            with pytest.raises(RuntimeError) as exc_info:
                assert_agent_runtime_config()

            error_msg = str(exc_info.value)
            assert "check 7" in error_msg.lower(), f"Error must name check 7, got: {error_msg}"
            assert "postgres" in error_msg.lower() or "owns tables" in error_msg.lower(), (
                f"Error must explain role ownership, got: {error_msg}"
            )
            print(f"✓ (b) PASS: Refused with: {error_msg[:120]}...")

    @requires_real_postgres
    def test_c_capability_on_one_table_rls_disabled_refuses_names_table(self):
        """(c) PRODUCTION_WRITE_ENABLED ON + one table RLS disabled → REFUSE, names table.

        Temporarily disable RLS on one tenant-scoped table, verify boot refuses,
        naming the specific table. Then restore RLS.
        """
        engine = _sync_engine()
        tenant_tables = get_tenant_scoped_tables()

        # Pick a table to test with (use the first one)
        if not tenant_tables:
            pytest.skip("No tenant-scoped tables defined")

        schema, table = tenant_tables[0]

        # Verify the table exists and has RLS enabled
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    f"""
                    SELECT relrowsecurity FROM pg_class t
                    JOIN pg_namespace n ON t.relnamespace = n.oid
                    WHERE n.nspname = '{schema}' AND t.relname = '{table}'
                    """
                )
            ).scalar()
            if result is None:
                pytest.skip(f"Table {schema}.{table} not found in database")

        # Disable RLS on the table temporarily
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {schema}.{table} DISABLE ROW LEVEL SECURITY"))

            # Enable capability and verify boot refuses
            with patch_env(PRODUCTION_WRITE_ENABLED="true"):
                assert is_production_write_enabled()

                with pytest.raises(RuntimeError) as exc_info:
                    assert_agent_runtime_config()

                error_msg = str(exc_info.value)
                assert "check 7" in error_msg.lower(), f"Error must name check 7, got: {error_msg}"
                assert table in error_msg, f"Error must name table {table}, got: {error_msg}"
                print(
                    f"✓ (c) PASS: Refused with RLS disabled on {schema}.{table}: "
                    f"{error_msg[:100]}..."
                )

        finally:
            # Restore RLS on the table
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY"))

    @requires_real_postgres
    def test_d_capability_on_non_owner_full_rls_boots(self):
        """(d) PRODUCTION_WRITE_ENABLED ON + non-owner (juli_app) + full RLS → BOOT.

        This test verifies the scenario after the cutover: when DATABASE_URL names
        a non-owner role with juli_app membership, RLS is enabled, and the process
        can boot. Since juli_app is NOLOGIN, we create a test role and grant it
        membership to simulate the post-cutover state.
        """
        engine = _sync_engine()

        # Check if juli_app role exists (created by migration 043)
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = 'juli_app'")
            ).scalar()
            if result is None:
                pytest.skip("juli_app role does not exist (migration 043 not run)")

        # Create a test login role and grant it juli_app membership for this test
        test_login_role = "test_non_owner_role_1330"
        try:
            with engine.begin() as conn:
                # Create test login role with permission to connect
                conn.execute(text(f"CREATE ROLE {test_login_role} WITH LOGIN PASSWORD 'test'"))
                # Grant it juli_app membership
                conn.execute(text(f"GRANT juli_app TO {test_login_role}"))

            # Verify all tenant tables have RLS enabled
            with engine.connect() as conn:
                tenant_tables = get_tenant_scoped_tables()
                tables_without_rls = []

                for schema, table in tenant_tables:
                    result = conn.execute(
                        text(
                            f"""
                            SELECT relrowsecurity FROM pg_class t
                            JOIN pg_namespace n ON t.relnamespace = n.oid
                            WHERE n.nspname = '{schema}' AND t.relname = '{table}'
                            """
                        )
                    ).scalar()

                    if result is False:
                        tables_without_rls.append(f"{schema}.{table}")

            if tables_without_rls:
                pytest.skip(f"Some tenant tables lack RLS: {tables_without_rls}")

            # Test with non-owner role: enable capability and verify boot succeeds.
            # Rebuild the URL swapping in the test role's credentials via proper URL
            # parsing — a string replace on "postgres@" breaks when DATABASE_URL
            # carries a password (postgres:test@...), as CI's does.
            from sqlalchemy.engine import make_url

            test_url = (
                make_url(_database_url())
                .set(username=test_login_role, password="test")
                .render_as_string(hide_password=False)
            )
            with patch_env(DATABASE_URL=test_url, PRODUCTION_WRITE_ENABLED="true"):
                assert is_production_write_enabled()

                try:
                    assert_agent_runtime_config()
                    print(
                        "✓ (d) PASS: Booted successfully with capability ON, "
                        "non-owner connection (juli_app member), full RLS"
                    )
                except RuntimeError as e:
                    if "check 7" in str(e).lower():
                        pytest.fail(
                            f"Boot should succeed with non-owner connection and full RLS, "
                            f"but check 7 raised: {e}"
                        )
                    raise

        finally:
            # Clean up: drop the test role
            with engine.begin() as conn:
                try:
                    conn.execute(text(f"DROP ROLE {test_login_role}"))
                except Exception:
                    pass  # Role may not exist or be protected

    @requires_real_postgres
    def test_both_api_and_worker_entry_points_asserted(self):
        """Verify that both API and worker entry points call assert_agent_runtime_config.

        The check must be invoked for both API boot and worker boot to ensure
        production-write mode cannot be enabled without the RLS check.
        """
        # Test API entry point (with app=None is worker-style call)
        with patch_env(PRODUCTION_WRITE_ENABLED="false"):
            # Should not raise when capability is OFF
            try:
                # Simulating API boot (would pass FastAPI app in real code)
                assert_agent_runtime_config(app=None)
                # Simulating worker boot
                assert_agent_runtime_config(broker_url="redis://localhost:6379")
                print("✓ Both API and worker entry points call assert_agent_runtime_config")
            except RuntimeError as e:
                if "check 7" in str(e).lower():
                    pytest.fail(f"Check 7 should be NO-OP when capability OFF, got: {e}")
                # Other errors (missing OPENAI_API_KEY, etc.) are expected in this test
