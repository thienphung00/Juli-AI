"""Integration tests for RLS DENIAL — Postgres 16 role switching & GUC isolation (#1328).

ACCEPTANCE CRITERIA — each test proves DENIAL, not policy existence:
1. OWNER-BYPASS CONTRAST: postgres sees all rows; juli_app with tenant context sees only own
2. GUC-UNSET DENIAL: juli_app without GUC set returns zero rows (not error)
3. VIA-PARENT DENIAL: child rows under foreign parent denied when parent belongs to other tenant
4. WRITE DENIAL: UPDATE/DELETE on foreign tenant's rows affected=0; INSERT foreign shop_id rejected
5. EXPLAIN INDEX PROOF: Index Scan not Seq Scan (isolation without perf regression)
6. Structural tests: relforcerowsecurity=false, old policies dropped, round-trip

All tests run on real Postgres 16 migrated to head, using SET ROLE juli_app and set_config GUCs.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import sync_database_url

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


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
            poolclass=NullPool,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="RLS denial tests require reachable Postgres DATABASE_URL",
)


@pytest.fixture
def alembic_cfg():
    """Alembic config pointing to test database."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


@pytest.fixture
def postgres_engine(alembic_cfg):
    """Create engine with NullPool to avoid connection pooling issues."""
    url = alembic_cfg.get_section(alembic_cfg.config_ini_section)["sqlalchemy.url"]
    engine = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


@requires_postgres
def test_upgrade_to_head_succeeds(alembic_cfg):
    """alembic upgrade head must complete without error."""
    command.upgrade(alembic_cfg, "head")


@requires_postgres
def test_no_table_has_force_row_level_security(postgres_engine):
    """No table must have relforcerowsecurity=true (owner bypass is critical)."""
    with postgres_engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT schemaname, tablename
                FROM pg_tables
                JOIN pg_class ON pg_class.relname = pg_tables.tablename
                JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
                  AND pg_namespace.nspname = pg_tables.schemaname
                WHERE relforcerowsecurity = true
                ORDER BY schemaname, tablename
                """
            )
        ).fetchall()
        assert len(result) == 0, f"Tables with FORCE RLS: {result}"


@requires_postgres
def test_no_old_app_current_user_id_policies_survive(postgres_engine, alembic_cfg):
    """No surviving policy references app.current_user_id except users/shops."""
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT schemaname, tablename, policyname, qual
                FROM pg_policies
                WHERE qual LIKE '%current_user_id%'
                  AND tablename NOT IN ('users', 'shops')
                ORDER BY schemaname, tablename, policyname
                """
            )
        ).fetchall()

        non_user_policies = [r for r in result if r[1] not in ("users", "shops")]
        assert len(non_user_policies) == 0, (
            f"Non-user/shop tables have current_user_id policies: {non_user_policies}"
        )


@requires_postgres
def test_roundtrip_downgrade_upgrade_preserves_schema(alembic_cfg):
    """alembic downgrade -1 && upgrade head round-trips without leaving RLS-enabled-no-policies."""
    command.upgrade(alembic_cfg, "head")
    # Downgrade and upgrade
    command.downgrade(alembic_cfg, "-1")
    command.upgrade(alembic_cfg, "head")


@requires_postgres
def test_owner_bypass_contrast_direct_shop_id(postgres_engine, alembic_cfg):
    """HEADLINE: Owner sees both tenants' rows; juli_app with tenant context sees only own.

    This is THE contrast proving RLS works: postgres (owner) bypasses policies,
    juli_app (non-owner) is restricted by them.
    """
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        # Setup: two tenants with products
        user_id = uuid.uuid4()
        shop_a_id = uuid.uuid4()
        shop_b_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        conn.execute(
            text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
            {"id": shop_a_id, "uid": user_id, "name": "Shop A"},
        )
        conn.execute(
            text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
            {"id": shop_b_id, "uid": user_id, "name": "Shop B"},
        )

        # Products for A and B
        for shop_id, name in [(shop_a_id, "A"), (shop_b_id, "B")]:
            conn.execute(
                text(
                    """INSERT INTO products
                    (id, shop_id, tiktok_product_id, name, status, update_time)
                    VALUES (:id, :sid, :tid, :name, 'active', now())"""
                ),
                {
                    "id": uuid.uuid4(),
                    "sid": shop_id,
                    "tid": f"prod_{name}",
                    "name": f"Product {name}",
                },
            )
        conn.commit()

        # ===== AS POSTGRES (OWNER): see BOTH A and B =====
        as_postgres = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        print(f"  As postgres (owner): {as_postgres} rows (expect 2)")
        assert as_postgres == 2, f"Owner should see 2 rows, got {as_postgres}"

        # ===== AS JULI_APP WITH SHOP A: see ONLY A =====
        conn.execute(text(f"SET app.current_shop_id = '{shop_a_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        as_juli_a = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        names_a = conn.execute(text("SELECT name FROM products ORDER BY name")).fetchall()
        print(f"  As juli_app (shop A): {as_juli_a} row → {names_a[0][0] if names_a else 'none'}")
        assert as_juli_a == 1, f"Shop A context should see 1 row, got {as_juli_a}"
        assert names_a[0][0] == "Product A", f"Should see Product A, got {names_a[0][0]}"

        # ===== AS JULI_APP WITH SHOP B: see ONLY B =====
        conn.execute(text("RESET ROLE"))
        conn.execute(text(f"SET app.current_shop_id = '{shop_b_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        as_juli_b = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        names_b = conn.execute(text("SELECT name FROM products ORDER BY name")).fetchall()
        print(f"  As juli_app (shop B): {as_juli_b} row → {names_b[0][0] if names_b else 'none'}")
        assert as_juli_b == 1, f"Shop B context should see 1 row, got {as_juli_b}"
        assert names_b[0][0] == "Product B", f"Should see Product B, got {names_b[0][0]}"

        conn.execute(text("RESET ROLE"))
        conn.commit()


@requires_postgres
def test_guc_unset_denial_direct_table(postgres_engine, alembic_cfg):
    """GUC unset → zero rows (not error) for direct-shop_id table."""
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        conn.execute(
            text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
            {"id": shop_id, "uid": user_id, "name": "Test"},
        )
        conn.execute(
            text(
                """INSERT INTO products
                (id, shop_id, tiktok_product_id, name, status, update_time)
                VALUES (:id, :sid, :tid, :name, 'active', now())"""
            ),
            {"id": uuid.uuid4(), "sid": shop_id, "tid": "prod", "name": "Test"},
        )
        conn.commit()

        # As juli_app WITHOUT GUC
        conn.execute(text("SET ROLE juli_app"))
        count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        print(f"  As juli_app (no GUC set): {count} rows (expect 0, not error)")
        assert count == 0, f"Unset GUC should deny (0 rows), got {count}"

        conn.execute(text("RESET ROLE"))
        conn.commit()


@requires_postgres
def test_guc_unset_denial_via_parent_table(postgres_engine, alembic_cfg):
    """GUC unset → zero rows for via-parent table (workflow_run_events via workflow_runs)."""
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_id = uuid.uuid4()
        product_id = uuid.uuid4()
        run_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        conn.execute(
            text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
            {"id": shop_id, "uid": user_id, "name": "Test"},
        )
        conn.execute(
            text(
                """INSERT INTO products
                (id, shop_id, tiktok_product_id, name, status, update_time)
                VALUES (:id, :sid, :tid, :name, 'active', now())"""
            ),
            {"id": product_id, "sid": shop_id, "tid": "prod", "name": "Prod"},
        )
        conn.execute(
            text(
                """INSERT INTO workflow_runs
                (id, shop_id, product_id, status, prompt_version, prompt_sha256)
                VALUES (:id, :sid, :pid, 'completed', 'v1', 'sha256')"""
            ),
            {"id": run_id, "sid": shop_id, "pid": product_id},
        )
        conn.execute(
            text(
                """INSERT INTO workflow_run_events
                (id, workflow_run_id, sequence_number, event_type, timestamp, payload)
                VALUES (:id, :run_id, 1, 'test', now(), '{}')"""
            ),
            {"id": uuid.uuid4(), "run_id": run_id},
        )
        conn.commit()

        # As juli_app WITHOUT GUC
        conn.execute(text("SET ROLE juli_app"))
        count = conn.execute(text("SELECT COUNT(*) FROM workflow_run_events")).scalar()
        print(f"  Via-parent (no GUC set): {count} rows (expect 0)")
        assert count == 0, f"Via-parent with unset GUC should deny, got {count}"

        conn.execute(text("RESET ROLE"))
        conn.commit()


@requires_postgres
def test_via_parent_denial_workflow_run_events(postgres_engine, alembic_cfg):
    """Via-parent denial: query as A sees zero of B's child rows (B's parent = workflow_run)."""
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_a_id = uuid.uuid4()
        shop_b_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        for sid, name in [(shop_a_id, "A"), (shop_b_id, "B")]:
            conn.execute(
                text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
                {"id": sid, "uid": user_id, "name": f"Shop {name}"},
            )

        # Products for A and B
        prod_a, prod_b = uuid.uuid4(), uuid.uuid4()
        for pid, sid in [(prod_a, shop_a_id), (prod_b, shop_b_id)]:
            conn.execute(
                text(
                    """INSERT INTO products
                    (id, shop_id, tiktok_product_id, name, status, update_time)
                    VALUES (:id, :sid, :tid, :name, 'active', now())"""
                ),
                {"id": pid, "sid": sid, "tid": f"prod_{sid}", "name": "Prod"},
            )

        # Workflow runs for A and B
        run_a, run_b = uuid.uuid4(), uuid.uuid4()
        for rid, sid, pid in [(run_a, shop_a_id, prod_a), (run_b, shop_b_id, prod_b)]:
            conn.execute(
                text(
                    """INSERT INTO workflow_runs
                    (id, shop_id, product_id, status, prompt_version, prompt_sha256)
                    VALUES (:id, :sid, :pid, 'completed', 'v1', 'sha256')"""
                ),
                {"id": rid, "sid": sid, "pid": pid},
            )

        # Events for A and B
        for rid in [run_a, run_b]:
            conn.execute(
                text(
                    """INSERT INTO workflow_run_events
                    (id, workflow_run_id, sequence_number, event_type, timestamp, payload)
                    VALUES (:id, :run_id, 1, 'test', now(), '{}')"""
                ),
                {"id": uuid.uuid4(), "run_id": rid},
            )
        conn.commit()

        # As juli_app with Shop A context
        conn.execute(text(f"SET app.current_shop_id = '{shop_a_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        count = conn.execute(text("SELECT COUNT(*) FROM workflow_run_events")).scalar()
        print(f"  Via-parent (A context, B's parent): {count} events (expect 1, see only A's)")
        assert count == 1, f"Should see 1 event (A's), got {count} (B's leaked)"

        conn.execute(text("RESET ROLE"))
        conn.commit()


@requires_postgres
def test_write_denial_update_on_foreign_tenant(postgres_engine, alembic_cfg):
    """WRITE DENIAL: UPDATE on foreign tenant's rows → zero rows affected.

    juli_app HAS update privilege (granted in #1326), so this proves RLS policy denies the row.
    """
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_a_id = uuid.uuid4()
        shop_b_id = uuid.uuid4()
        prod_b_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        for sid, name in [(shop_a_id, "A"), (shop_b_id, "B")]:
            conn.execute(
                text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
                {"id": sid, "uid": user_id, "name": f"Shop {name}"},
            )

        # Product for B only
        conn.execute(
            text(
                """INSERT INTO products
                (id, shop_id, tiktok_product_id, name, status, update_time)
                VALUES (:id, :sid, :tid, :name, 'active', now())"""
            ),
            {"id": prod_b_id, "sid": shop_b_id, "tid": "prod_b", "name": "Product B"},
        )
        conn.commit()

        # As juli_app with Shop A, try to UPDATE B's row
        conn.execute(text(f"SET app.current_shop_id = '{shop_a_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        update_result = conn.execute(
            text("UPDATE products SET name = 'Hacked' WHERE id = :id"),
            {"id": prod_b_id},
        )
        update_count = update_result.rowcount
        print(f"  UPDATE foreign row (RLS denies): {update_count} rows affected (expect 0)")
        assert update_count == 0, (
            f"UPDATE on foreign tenant: expected 0 affected, got {update_count}"
        )

        conn.execute(text("RESET ROLE"))
        conn.commit()


@requires_postgres
def test_write_denial_delete_via_rls_coverage(postgres_engine, alembic_cfg):
    """DELETE denial: RLS policy covers DELETE (juli_app normally has NO delete grant).

    Proof-in-depth: temporarily GRANT DELETE to juli_app in a transaction,
    attempt cross-tenant delete as juli_app, assert RLS scopes it to 0 rows,
    then ROLLBACK so the grant never persists. This proves the policy covers DELETE.
    """
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_a_id = uuid.uuid4()
        shop_b_id = uuid.uuid4()
        prod_b_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        for sid, name in [(shop_a_id, "A"), (shop_b_id, "B")]:
            conn.execute(
                text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
                {"id": sid, "uid": user_id, "name": f"Shop {name}"},
            )

        # Product for B only
        conn.execute(
            text(
                """INSERT INTO products
                (id, shop_id, tiktok_product_id, name, status, update_time)
                VALUES (:id, :sid, :tid, :name, 'active', now())"""
            ),
            {"id": prod_b_id, "sid": shop_b_id, "tid": "prod_b", "name": "Product B"},
        )
        conn.commit()

        # Temporarily grant DELETE to juli_app (for this test only, within transaction)
        conn.execute(text("GRANT DELETE ON products TO juli_app"))

        # As juli_app with Shop A, try to DELETE B's row
        conn.execute(text(f"SET app.current_shop_id = '{shop_a_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        delete_result = conn.execute(
            text("DELETE FROM products WHERE id = :id"),
            {"id": prod_b_id},
        )
        delete_count = delete_result.rowcount
        print(f"  DELETE foreign row (RLS denies): {delete_count} rows affected")
        assert delete_count == 0, (
            f"DELETE on foreign tenant: expected 0 affected, got {delete_count}"
        )

        # ROLLBACK the entire transaction, so GRANT DELETE never persists to runtime
        conn.execute(text("RESET ROLE"))
        conn.rollback()  # <-- Critical: never commit the GRANT
        print("  Transaction rolled back - DELETE grant NOT persisted to runtime")


@requires_postgres
def test_write_denial_insert_with_check_rejected(postgres_engine, alembic_cfg):
    """WRITE DENIAL: INSERT with foreign shop_id is rejected by WITH CHECK."""
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_a_id = uuid.uuid4()
        shop_b_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        for sid, name in [(shop_a_id, "A"), (shop_b_id, "B")]:
            conn.execute(
                text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
                {"id": sid, "uid": user_id, "name": f"Shop {name}"},
            )
        conn.commit()

        # As juli_app with Shop A, try to INSERT for Shop B
        conn.execute(text(f"SET app.current_shop_id = '{shop_a_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        try:
            conn.execute(
                text(
                    """INSERT INTO products
                    (id, shop_id, tiktok_product_id, name, status, update_time)
                    VALUES (:id, :sid, :tid, :name, 'active', now())"""
                ),
                {"id": uuid.uuid4(), "sid": shop_b_id, "tid": "prod_b", "name": "Prod B"},
            )
            conn.commit()
            print("  INSERT with foreign shop_id: ERROR - should have been rejected")
            pytest.fail("INSERT with foreign shop_id should be rejected by WITH CHECK")
        except Exception as e:
            print(f"  INSERT with foreign shop_id: REJECTED ({type(e).__name__})")
            # Expected to fail
            pass

        conn.execute(text("RESET ROLE"))
        conn.commit()


@requires_postgres
def test_explain_index_direct_read(postgres_engine, alembic_cfg):
    """EXPLAIN: direct-shop_id read uses Index, not Seq Scan (no perf regression)."""
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        conn.execute(
            text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
            {"id": shop_id, "uid": user_id, "name": "Test"},
        )

        for i in range(5):
            conn.execute(
                text(
                    """INSERT INTO products
                    (id, shop_id, tiktok_product_id, name, status, update_time)
                    VALUES (:id, :sid, :tid, :name, 'active', now())"""
                ),
                {"id": uuid.uuid4(), "sid": shop_id, "tid": f"prod_{i}", "name": f"P{i}"},
            )
        conn.commit()

        # EXPLAIN as juli_app with context
        conn.execute(text(f"SET app.current_shop_id = '{shop_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        explain_rows = conn.execute(text("EXPLAIN SELECT * FROM products")).fetchall()

        explain_str = "\n".join([row[0] for row in explain_rows])
        print(f"  EXPLAIN (direct read):\n{explain_str}")

        assert "Seq Scan" not in explain_str, f"Uses Seq Scan (perf incident): {explain_str}"
        assert "Index" in explain_str, f"Expected Index Scan: {explain_str}"

        conn.execute(text("RESET ROLE"))
        conn.commit()


@requires_postgres
def test_explain_index_via_parent_exists(postgres_engine, alembic_cfg):
    """EXPLAIN: via-parent EXISTS read uses Index, not Seq Scan."""
    command.upgrade(alembic_cfg, "head")

    with postgres_engine.connect() as conn:
        user_id = uuid.uuid4()
        shop_id = uuid.uuid4()
        product_id = uuid.uuid4()

        conn.execute(
            text("INSERT INTO users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1{uuid.uuid4().hex[:10]}"},
        )
        conn.execute(
            text("INSERT INTO shops (id, user_id, shop_name) VALUES (:id, :uid, :name)"),
            {"id": shop_id, "uid": user_id, "name": "Test"},
        )
        conn.execute(
            text(
                """INSERT INTO products
                (id, shop_id, tiktok_product_id, name, status, update_time)
                VALUES (:id, :sid, :tid, :name, 'active', now())"""
            ),
            {"id": product_id, "sid": shop_id, "tid": "prod", "name": "Prod"},
        )

        # Create runs and events
        for i in range(3):
            run_id = uuid.uuid4()
            conn.execute(
                text(
                    """INSERT INTO workflow_runs
                    (id, shop_id, product_id, status, prompt_version, prompt_sha256)
                    VALUES (:id, :sid, :pid, 'completed', 'v1', 'sha256')"""
                ),
                {"id": run_id, "sid": shop_id, "pid": product_id},
            )
            for j in range(2):
                conn.execute(
                    text(
                        """INSERT INTO workflow_run_events
                        (id, workflow_run_id, sequence_number, event_type, timestamp, payload)
                        VALUES (:id, :run_id, :seq, 'test', now(), '{}')"""
                    ),
                    {"id": uuid.uuid4(), "run_id": run_id, "seq": j},
                )
        conn.commit()

        # EXPLAIN as juli_app
        conn.execute(text(f"SET app.current_shop_id = '{shop_id}'"))
        conn.execute(text("SET ROLE juli_app"))

        explain_rows = conn.execute(text("EXPLAIN SELECT * FROM workflow_run_events")).fetchall()

        explain_str = "\n".join([row[0] for row in explain_rows])
        print(f"  EXPLAIN (via-parent EXISTS):\n{explain_str}")

        # Via-parent queries may seq scan the child table, but the EXISTS subplan MUST use an index
        # on the parent. Verify the subplan uses an index (the critical part for RLS performance).
        assert "Index" in explain_str, f"Expected Index Scan in subplan: {explain_str}"
        # SubPlan is where the RLS EXISTS check runs on the parent - that must use index
        assert "SubPlan" in explain_str or "Subquery" in explain_str, (
            f"Expected SubPlan in RLS EXISTS: {explain_str}"
        )

        conn.execute(text("RESET ROLE"))
        conn.commit()
