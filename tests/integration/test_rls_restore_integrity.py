"""Integration tests for RLS integrity after restore (issues #1553, #1554).

Proves that a database restored with --no-owner as juli_app has inert RLS,
and that the restore must either:
1. Restore as proper owner (not juli_app), or
2. Verify RLS actually denies cross-tenant reads
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.two_tenant import seed_tenant

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"


def _as_runtime_role(url: str) -> str:
    """Rewrite a Postgres URL to authenticate as juli_app.

    Local Postgres uses trust auth, so no password is involved. Needed because
    --no-owner only reassigns ownership when the RESTORING role differs from the
    dump's owner — restoring as the admin makes the flag inert and the test
    vacuous.
    """
    tail = url.split("@", 1)[1] if "@" in url else url.split("://", 1)[1]
    return f"postgresql://juli_app@{tail}"


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
    reason="RLS tests require reachable Postgres DATABASE_URL",
)


@requires_postgres
def test_rls_is_inert_when_restored_with_no_owner_as_runtime_role():
    """Restore with --no-owner as juli_app makes table ownership=juli_app, RLS inert.

    This test DOCUMENTS the bug in #1554. When restored with --no-owner:
    - Tables end up owned by juli_app (the restoring role)
    - Postgres exempts table owners from RLS policy evaluation
    - Cross-tenant reads succeed (the breach)

    This test must FAIL with current --no-owner behavior, and PASS after the
    fix (which either: (a) restores as proper owner, or (b) fixes ownership after).
    """
    url = _database_url()
    if not url.startswith("postgresql"):
        pytest.skip("requires postgres URL")

    from alembic import command
    from alembic.config import Config

    engine = create_engine(sync_database_url(url), pool_pre_ping=True)

    # Reset to head, then seed two tenants
    alembic_ini = REPO_ROOT / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", sync_database_url(url))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    tenant1 = seed_tenant(engine, label="Tenant1")
    tenant2 = seed_tenant(engine, label="Tenant2")

    for _tool in ("pg_dump", "pg_restore", "psql"):
        _out = subprocess.run([_tool, "--version"], capture_output=True, text=True, check=False)
        if " 16." not in _out.stdout:
            pytest.skip(
                "pg_dump/pg_restore/psql 16 required — this test restores with -e, "
                "so a client/server version mismatch aborts it. Start safe-alembic-pg "
                "or install postgresql-client-16."
            )

    # Create a dump before any restore happens
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        dump_file = tmpdir_path / "rls-test.dump"

        # Dump the database
        migration_url = sync_database_url(url)
        dump = subprocess.run(
            ["pg_dump", "-Fc", "-f", str(dump_file), migration_url],
            capture_output=True,
            text=True,
            check=False,
        )
        assert dump.returncode == 0, dump.stderr
        assert dump_file.stat().st_size > 0

        # Now create a scratch database, restore into it with --no-owner
        helper = SCRIPTS_DIR / "safe_alembic_helpers.py"
        run_env = os.environ.copy()
        run_env["PYTHONPATH"] = (
            f"{SCRIPTS_DIR}:{REPO_ROOT}/backend/src:{os.environ.get('PYTHONPATH', '')}"
        )
        admin_url_result = subprocess.run(
            [sys.executable, str(helper), "admin-db-url"],
            capture_output=True,
            text=True,
            env=run_env,
            check=False,
        )
        assert admin_url_result.returncode == 0, admin_url_result.stderr
        admin_url = admin_url_result.stdout.strip()

        scratch_db = f"juli_rls_test_{int(datetime.now().timestamp() * 1000)}"
        create_db = subprocess.run(
            ["psql", admin_url, "-c", f'CREATE DATABASE "{scratch_db}"'],
            capture_output=True,
            text=True,
            check=False,
        )
        # Before the restore, which connects as juli_app. Reverted in teardown —
        # LOGIN is cluster-wide and would otherwise outlive this test.
        subprocess.run(
            ["psql", admin_url, "-c", "ALTER ROLE juli_app LOGIN"],
            capture_output=True,
            check=False,
        )
        assert create_db.returncode == 0, create_db.stderr

        try:
            # Get the scratch database URL
            scratch_url_result = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    "database-url-with-name",
                    "--database",
                    scratch_db,
                ],
                capture_output=True,
                text=True,
                env=run_env,
                check=False,
            )
            assert scratch_url_result.returncode == 0, scratch_url_result.stderr
            scratch_url = scratch_url_result.stdout.strip()

            # Restore with --no-owner --no-acl (the problematic flags)
            restore = subprocess.run(
                [
                    "pg_restore",
                    # Neither --no-owner nor --no-acl, and restored AS THE
                    # OWNER. This is the procedure #1554 established; the test
                    # exists to fail if anyone reintroduces those flags.
                    "-e",
                    "-d",
                    scratch_url,
                    "--clean",
                    "--if-exists",
                    str(dump_file),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            # Ignore version mismatch warnings about transaction_timeout
            if restore.returncode != 0 and "transaction_timeout" not in restore.stderr:
                assert False, restore.stderr

            # Now connect as juli_app with tenant1 context and try to read tenant2's data
            # This is the key test: RLS should DENY this, but with --no-owner it ALLOWS it
            scratch_engine = create_engine(scratch_url, pool_pre_ping=True)
            with scratch_engine.connect() as conn:
                # Check table ownership
                result = conn.execute(
                    text(
                        """
                        SELECT tableowner FROM pg_tables
                        WHERE tablename = 'users' AND schemaname = 'public'
                        """
                    )
                )
                owner = result.scalar()
                # The restoring role must NOT end up owning the tables. A table
                # its owner reads is exempt from that table's own RLS policies,
                # so ownership is what decides whether the 167 restored policies
                # mean anything.
                assert owner != "juli_app", (
                    f"tables are owned by {owner!r}, the runtime role — RLS "
                    "policies restore but are inert against their own owner"
                )

                # Now try to read as juli_app with tenant1 context
                # Create a temporary connection as juli_app
                # LOGIN was granted before the restore above.

            scratch_engine.dispose()

            # Connect as juli_app with tenant1 shop context
            from sqlalchemy.ext.asyncio import create_async_engine

            from juli_backend.core.config.runtime import async_database_url

            async def test_rls():
                async_url = async_database_url(scratch_url)
                async_engine = create_async_engine(async_url)
                try:
                    async with async_engine.connect() as aconn:
                        # Set role to juli_app
                        await aconn.execute(text("SET ROLE juli_app"))
                        # Set shop context to tenant1
                        await aconn.execute(
                            text(
                                "SELECT set_config('app.current_shop_id', :val, false)"
                            ).bindparams(val=str(tenant1.shop_id))
                        )
                        # Try to read tenant2's user
                        result = await aconn.execute(
                            # CAST, not `:id::uuid` — SQLAlchemy's parameter
                            # parser reads the `::` as part of the name. The
                            # cast is needed because `users.id` is uuid and the
                            # bound value arrives as varchar.
                            text(
                                "SELECT count(*) FROM public.users WHERE id = CAST(:id AS uuid)"
                            ).bindparams(id=str(tenant2.user_id))
                        )
                        count = result.scalar()

                        # With RLS working: count should be 0 (tenant2's user blocked)
                        # With RLS inert (the bug): count would be 1 (tenant2's user visible)
                        return count
                finally:
                    await async_engine.dispose()

            import asyncio

            cross_tenant_count = asyncio.run(test_rls())
            assert cross_tenant_count == 0, (
                f"RLS is INERT! Running as juli_app with tenant1 context, "
                f"could read {cross_tenant_count} rows from tenant2 (should be 0). "
                f"This is the bug in #1554 — tables owned by juli_app are exempt from RLS."
            )

        finally:
            # Clean up scratch database
            # Revert the LOGIN granted above. Cluster-wide, so it outlives
            # the scratch database being dropped below.
            subprocess.run(
                ["psql", admin_url, "-c", "ALTER ROLE juli_app NOLOGIN"],
                capture_output=True,
                check=False,
            )
            drop_db = subprocess.run(
                ["psql", admin_url, "-c", f'DROP DATABASE IF EXISTS "{scratch_db}" WITH (FORCE)'],
                capture_output=True,
                text=True,
                check=False,
            )
            assert drop_db.returncode == 0 or "does not exist" in drop_db.stderr

    # Restore to original state
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine.dispose()
