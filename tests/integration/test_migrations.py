"""Alembic migration integration tests — Issue #365.

Exercises downgrade/upgrade round trips against Postgres with seeded data
assertions. Skips when DATABASE_URL is not a reachable Postgres instance.

GUARD: Issue #734 — Destructive migration tests refuse non-local database URLs.
Tests will error loudly (not skip silently) if DATABASE_URL points to a remote host.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
LATEST_REVISION = "029_close_public_schema_defaults"

sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
from check_public_schema_privileges import (  # noqa: E402
    GOLD_ALLOWLIST,
    find_privilege_violations,
    find_reachable_tables,
)
from ensure_postgrest_client_roles import (  # noqa: E402
    ensure_roles,
    seed_supabase_bootstrap_grants,
)


def _validate_destructive_db_url(url: str) -> None:
    """Validate DATABASE_URL before running destructive migration operations.

    Raises RuntimeError if the URL points to a non-local database, unless
    ALLOW_DESTRUCTIVE_MIGRATION_TESTS=1 is set in the environment.

    This guard sits BEFORE any command.downgrade() call or engine-creating fixture
    to prevent accidental data loss when tests are pointed at production.

    Acceptance criteria: Issue #734 AC1-AC5.
    """
    if not url.strip():
        # Empty URL: will be caught later when Postgres is checked; allow here
        return

    # Check explicit opt-in environment variable
    allow_destructive = os.environ.get("ALLOW_DESTRUCTIVE_MIGRATION_TESTS", "").strip()
    if allow_destructive == "1":
        # Explicitly opt-in: allow any target
        return

    # Parse the URL using urllib.parse to robustly extract the host.
    # parsed.hostname handles credentials, ports, IPv6 brackets, and case-folding.
    parsed = urlparse(url)
    hostname = parsed.hostname

    if hostname is None:
        # Unix socket path (local): e.g., postgresql:///var/run/postgresql/socket/db
        # parsed.hostname returns None when there is no netloc (unix sockets).
        # These are always safe because they are file system paths.
        return

    # Normalize to lowercase for comparison
    hostname = hostname.lower()

    # Allowed local hosts
    local_hosts = {"localhost", "127.0.0.1", "::1"}  # IPv6 localhost

    if hostname not in local_hosts:
        # Non-local host detected: raise error
        raise RuntimeError(
            f"Destructive migration tests refuse non-local hosts. "
            f"Detected host: {hostname}. "
            f"This suite runs 'alembic downgrade base' which drops all tables. "
            f"If you want to run this suite against a disposable remote database, "
            f"set ALLOW_DESTRUCTIVE_MIGRATION_TESTS=1 in the environment."
        )


REVISION_024_GOLD_TABLE = "kpi_envelopes"
REVISION_024_COMPAT_VIEW = "analytics_kpi_envelopes_compat"
REVISION_025_SILVER_TABLES = ("orders", "returns")
REVISION_028_DEMO_EXECUTION_TABLE = "demo_execution_records"
REVISION_010_COLUMNS = {
    "orders": (
        "order_value",
        "payment_time",
        "ship_time",
        "delivery_time",
        "tiktok_created_at",
        "cancel_reason",
        "is_seller_fault",
    ),
    "products": (
        "title",
        "category",
        "category_id",
        "price",
        "price_currency",
        "inventory",
        "audit_status",
        "tiktok_created_at",
    ),
}
REVISION_011_TABLE = "workflow_webhook_signals"
REVISION_012_TABLE = "tool_executions"
REVISION_013_TABLE = "workflow_outcome_records"
REVISION_014_TABLE = "action_cards"
REVISION_015_COLUMNS = ("idempotency_key", "error_category")
REVISION_016_TABLE = "webhook_raw_events"
REVISION_017_TABLE = "analytics_performance_intervals"
REVISION_018_COLUMNS = (
    "live_hours",
    "live_sessions",
    "active_products",
    "new_products",
)
REVISION_019_TABLE = "analytics_backfill_partitions"
REVISION_020_TABLE = "analytics_kpi_envelopes"
REVISION_021_TABLE = "ml_feature_snapshots"
REVISION_022_SCHEMA = "ops"
REVISION_023_BRONZE_TABLES = ("order_raw_payloads", "return_raw_payloads")
MEDALLION_SCHEMAS = ("bronze", "silver", "gold", "ops")
CLIENT_ISOLATED_SCHEMAS = ("bronze", "silver", "ops")
POSTGREST_CLIENT_ROLES = ("anon", "authenticated")


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
    reason="Migration integration tests require a reachable Postgres DATABASE_URL",
)


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location",
        str(REPO_ROOT / "backend/src/juli_backend/database/migrations"),
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


def _sync_engine() -> Engine:
    return create_engine(sync_database_url(_database_url()), pool_pre_ping=True)


def _reset_to_head() -> None:
    """Downgrade to base, then upgrade to head against a CI-representative substrate.

    #929: roles + the Supabase-equivalent bootstrap grant are seeded HERE — after
    reaching base, before any migration in the upgrade path runs — mirroring the
    real migration-check job's ordering (`ensure_postgrest_client_roles.py` runs
    before `alembic upgrade`). Without this, a fresh Postgres 16 substrate never
    auto-grants table privileges to non-owner roles, so migration 029's
    `ALTER DEFAULT PRIVILEGES ... REVOKE ALL` clause has nothing to counteract and
    every "born closed" assertion below would pass whether or not that clause ran.
    """
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    database_url = _database_url()
    ensure_roles(database_url)
    seed_supabase_bootstrap_grants(database_url)
    command.upgrade(cfg, "head")


def _table_has_column(engine: Engine, table: str, column: str) -> bool:
    return column in {col["name"] for col in inspect(engine).get_columns(table)}


def _table_has_column_in_schema(engine: Engine, schema: str, table: str, column: str) -> bool:
    return column in {col["name"] for col in inspect(engine).get_columns(table, schema=schema)}


def _table_exists(engine: Engine, table: str) -> bool:
    return table in inspect(engine).get_table_names()


def _schema_exists(engine: Engine, schema: str) -> bool:
    return schema in inspect(engine).get_schema_names()


def _table_exists_in_schema(engine: Engine, schema: str, table: str) -> bool:
    return table in inspect(engine).get_table_names(schema=schema)


def _view_exists(engine: Engine, view: str, *, schema: str = "public") -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.views
                WHERE table_schema = :schema AND table_name = :view
                """
            ),
            {"schema": schema, "view": view},
        ).first()
    return row is not None


def _seed_legacy_analytics_envelope(engine: Engine, shop_id: uuid.UUID) -> None:
    """Insert legacy envelope row (pre-024) for migration cutover tests."""
    now = datetime.now(UTC).replace(tzinfo=None)
    payload = {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": now.isoformat(),
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "label": "GMV (TikTok)",
                "series": [{"t": "2026-07-01", "v": 100.0}],
            }
        },
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analytics_kpi_envelopes (
                    id, shop_id, kind, envelope_version, payload, computed_at
                )
                VALUES (:id, :shop_id, 'analytics', 1, CAST(:payload AS jsonb), :computed_at)
                """
            ),
            {
                "id": uuid.uuid4(),
                "shop_id": shop_id,
                "payload": json.dumps(payload),
                "computed_at": now,
            },
        )


def _seed_representative_rows(engine: Engine) -> dict[str, uuid.UUID]:
    """Insert rows touching migrations 009 (sync state) and 010 (order/product fields)."""
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    order_id = uuid.uuid4()
    product_id = uuid.uuid4()
    sync_state_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, phone, display_name)
                VALUES (:id, :phone, :display_name)
                """
            ),
            {
                "id": user_id,
                "phone": "+84936500001",
                "display_name": "Migration Test User",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO shops (id, user_id, shop_name, tiktok_shop_id, is_active)
                VALUES (:id, :user_id, :shop_name, :tiktok_shop_id, :is_active)
                """
            ),
            {
                "id": shop_id,
                "user_id": user_id,
                "shop_name": "Migration Test Shop",
                "tiktok_shop_id": "migration_shop_365",
                "is_active": True,
            },
        )
        order_params = {
            "id": order_id,
            "shop_id": shop_id,
            "tiktok_order_id": "migration_order_365",
            "status": "COMPLETED",
            "total_amount": Decimal("42.50"),
            "currency": "USD",
            "update_time": now,
            "order_value": Decimal("42.50"),
            "payment_time": now,
            "cancel_reason": None,
            "is_seller_fault": False,
        }
        order_insert = """
                INSERT INTO {table} (
                    id, shop_id, tiktok_order_id, status, total_amount, currency,
                    update_time, order_value, payment_time, cancel_reason, is_seller_fault
                )
                VALUES (
                    :id, :shop_id, :tiktok_order_id, :status, :total_amount, :currency,
                    :update_time, :order_value, :payment_time, :cancel_reason, :is_seller_fault
                )
                """
        if _table_exists_in_schema(engine, "silver", "orders"):
            conn.execute(
                text(order_insert.format(table="silver.orders")),
                order_params,
            )
            # Mirror into public.orders so downgrade/upgrade round-trips repopulate silver.
            conn.execute(text("SET LOCAL session_replication_role = 'replica'"))
            conn.execute(
                text(order_insert.format(table="orders")),
                order_params,
            )
            conn.execute(text("SET LOCAL session_replication_role = 'origin'"))
        else:
            conn.execute(
                text(order_insert.format(table="orders")),
                order_params,
            )
        conn.execute(
            text(
                """
                INSERT INTO products (
                    id, shop_id, tiktok_product_id, name, status, update_time,
                    title, category, price, price_currency, inventory, audit_status
                )
                VALUES (
                    :id, :shop_id, :tiktok_product_id, :name, :status, :update_time,
                    :title, :category, :price, :price_currency, :inventory, :audit_status
                )
                """
            ),
            {
                "id": product_id,
                "shop_id": shop_id,
                "tiktok_product_id": "migration_product_365",
                "name": "Migration Test Product",
                "status": "ACTIVE",
                "update_time": now,
                "title": "Canonical Title",
                "category": "Apparel",
                "price": Decimal("19.99"),
                "price_currency": "USD",
                "inventory": 12,
                "audit_status": "APPROVED",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO tiktok_sync_state (
                    id, shop_id, endpoint, last_update_time
                )
                VALUES (:id, :shop_id, :endpoint, :last_update_time)
                """
            ),
            {
                "id": sync_state_id,
                "shop_id": shop_id,
                "endpoint": "orders",
                "last_update_time": 1_700_000_000,
            },
        )

    return {
        "user_id": user_id,
        "shop_id": shop_id,
        "order_id": order_id,
        "product_id": product_id,
        "sync_state_id": sync_state_id,
    }


@pytest.fixture
def postgres_at_head():
    _reset_to_head()
    engine = _sync_engine()
    yield engine
    engine.dispose()


@requires_postgres
def test_seeded_rows_survive_latest_migration_round_trip(postgres_at_head: Engine):
    """Core rows and sync-state cursors survive downgrade -1 / upgrade head."""
    ids = _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")

    with postgres_at_head.connect() as conn:
        user = conn.execute(
            text("SELECT phone, display_name FROM users WHERE id = :id"),
            {"id": ids["user_id"]},
        ).one()
        shop = conn.execute(
            text("SELECT shop_name, tiktok_shop_id FROM shops WHERE id = :id"),
            {"id": ids["shop_id"]},
        ).one()
        order = conn.execute(
            text(
                """
                SELECT tiktok_order_id, total_amount, currency
                FROM silver.orders WHERE id = :id
                """
            ),
            {"id": ids["order_id"]},
        ).one()
        product = conn.execute(
            text(
                """
                SELECT tiktok_product_id, name, status
                FROM products WHERE id = :id
                """
            ),
            {"id": ids["product_id"]},
        ).one()
        sync_state = conn.execute(
            text(
                """
                SELECT endpoint, last_update_time
                FROM tiktok_sync_state WHERE id = :id
                """
            ),
            {"id": ids["sync_state_id"]},
        ).one()

    assert user.phone == "+84936500001"
    assert user.display_name == "Migration Test User"
    assert shop.shop_name == "Migration Test Shop"
    assert shop.tiktok_shop_id == "migration_shop_365"
    assert order.tiktok_order_id == "migration_order_365"
    assert order.total_amount == Decimal("42.50")
    assert order.currency == "USD"
    assert product.tiktok_product_id == "migration_product_365"
    assert product.name == "Migration Test Product"
    assert product.status == "ACTIVE"
    assert sync_state.endpoint == "orders"
    assert sync_state.last_update_time == 1_700_000_000


@requires_postgres
def test_analytics_interval_backfill_columns_exist_at_head(postgres_at_head: Engine):
    """Revision 018 adds nullable live/catalog rollup columns (#463)."""
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)


@requires_postgres
def test_backfill_partitions_table_exists_at_head(postgres_at_head: Engine):
    """Revision 022 moves analytics_backfill_partitions to ops (#604)."""
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)


@requires_postgres
def test_ops_backfill_partitions_data_migrated_at_head(postgres_at_head: Engine):
    """Revision 022 preserves rows when moving public → ops (#604)."""
    ids = _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()
    partition_id = uuid.uuid4()
    partition_date = "2026-01-20"

    command.downgrade(cfg, "021_medallion_schemas")

    with postgres_at_head.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analytics_backfill_partitions (
                    id, shop_id, bucket, partition_date, status
                )
                VALUES (:id, :shop_id, :bucket, :partition_date, :status)
                """
            ),
            {
                "id": partition_id,
                "shop_id": ids["shop_id"],
                "bucket": "revenue",
                "partition_date": partition_date,
                "status": "complete",
            },
        )

    command.upgrade(cfg, "head")

    with postgres_at_head.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, shop_id, bucket, partition_date, status
                FROM ops.analytics_backfill_partitions
                WHERE id = :id
                """
            ),
            {"id": partition_id},
        ).one()

    assert row.id == partition_id
    assert row.shop_id == ids["shop_id"]
    assert row.bucket == "revenue"
    assert row.status == "complete"
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)


@requires_postgres
def test_downgrade_022_restores_public_backfill_partitions(postgres_at_head: Engine):
    """Downgrading past 022 restores public table; ops copy removed (#604)."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)

    # Head may be past 022 (e.g. 023); target 021 so 022 downgrade runs explicitly.
    command.downgrade(cfg, "021_medallion_schemas")

    assert _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert not _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)

    command.upgrade(cfg, "head")
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)


@requires_postgres
def test_medallion_schemas_exist_at_head(postgres_at_head: Engine):
    """Revision 021 creates bronze/silver/gold/ops schemas (#603)."""
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)


@requires_postgres
def test_gold_ml_feature_snapshots_stub_exists_at_head(postgres_at_head: Engine):
    """Revision 021 adds empty-OK gold.ml_feature_snapshots stub (#603)."""
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_021_TABLE)


@requires_postgres
def test_bronze_orders_returns_tables_exist_at_head(postgres_at_head: Engine):
    """Revision 023 adds bronze order/return raw payload append tables (#605)."""
    for table in REVISION_023_BRONZE_TABLES:
        assert _table_exists_in_schema(postgres_at_head, "bronze", table)
    for column in (
        "id",
        "shop_id",
        "received_at",
        "ingest_source",
        "payload",
        "source_event_id",
    ):
        assert _table_has_column_in_schema(postgres_at_head, "bronze", "order_raw_payloads", column)
        assert _table_has_column_in_schema(
            postgres_at_head, "bronze", "return_raw_payloads", column
        )
    assert _table_has_column_in_schema(
        postgres_at_head, "bronze", "order_raw_payloads", "tiktok_order_id"
    )
    assert _table_has_column_in_schema(
        postgres_at_head, "bronze", "return_raw_payloads", "tiktok_return_id"
    )


@requires_postgres
def test_latest_downgrade_drops_only_revision_023_bronze_tables(
    postgres_at_head: Engine,
):
    """Downgrading past 023 removes bronze raw tables; medallion schemas remain."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    for table in REVISION_023_BRONZE_TABLES:
        assert _table_exists_in_schema(postgres_at_head, "bronze", table)
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_021_TABLE)

    # Head may be past 023 (e.g. 024); target 022 so 023 downgrade runs explicitly.
    command.downgrade(cfg, "022_ops_backfill_partitions")

    for table in REVISION_023_BRONZE_TABLES:
        assert not _table_exists_in_schema(postgres_at_head, "bronze", table)
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_021_TABLE)

    command.upgrade(cfg, "head")
    for table in REVISION_023_BRONZE_TABLES:
        assert _table_exists_in_schema(postgres_at_head, "bronze", table)


@requires_postgres
def test_internal_medallion_layers_not_readable_by_postgrest_roles(
    postgres_at_head: Engine,
):
    """bronze/silver/ops must not grant USAGE to anon/authenticated (#603)."""
    with postgres_at_head.begin() as conn:
        for role in POSTGREST_CLIENT_ROLES:
            conn.execute(
                text(
                    f"""
DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    CREATE ROLE {role} NOLOGIN;
  END IF;
END
$role$;
"""
                )
            )
        # Prove REVOKE path: grant then revoke (roles absent at upgrade on plain CI).
        for schema in CLIENT_ISOLATED_SCHEMAS:
            for role in POSTGREST_CLIENT_ROLES:
                conn.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {role}"))
                conn.execute(text(f"REVOKE ALL ON SCHEMA {schema} FROM {role}"))

        for schema in CLIENT_ISOLATED_SCHEMAS:
            for role in POSTGREST_CLIENT_ROLES:
                has_usage = conn.execute(
                    text("SELECT has_schema_privilege(:role, :schema, 'USAGE')"),
                    {"role": role, "schema": schema},
                ).scalar_one()
                assert has_usage is False, f"{role} must not have USAGE on {schema}"


def _ensure_client_roles(engine: Engine) -> None:
    with engine.begin() as conn:
        for role in POSTGREST_CLIENT_ROLES:
            conn.execute(
                text(
                    f"""
DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    CREATE ROLE {role} NOLOGIN;
  END IF;
END
$role$;
"""
                )
            )


@requires_postgres
def test_public_schema_open_before_029(postgres_at_head: Engine):
    """Exit-gate assertion detects the problem: public is open at revision 028 (#897).

    Demonstrates the CI exit gate actually catches the pre-#897 state rather than
    trivially passing — the same property .github/workflows/pr.yml's migration-check
    job proves live by inverting this check's exit code against revision 028.
    """
    _ensure_client_roles(postgres_at_head)
    cfg = _alembic_config()
    command.downgrade(cfg, "028_demo_execution_records")

    violations = find_privilege_violations(_database_url())

    command.upgrade(cfg, "head")

    assert violations, (
        "expected at least one reachable table outside the gold allowlist at "
        "revision 028 (public never had ALTER DEFAULT PRIVILEGES applied)"
    )
    # public.analytics_kpi_envelopes_compat (024_gold_kpi_envelopes) is reachable
    # via public's default USAGE grant to PUBLIC plus its own explicit SELECT grant.
    all_offending = {pair for pairs in violations.values() for pair in pairs}
    assert ("public", "analytics_kpi_envelopes_compat") in all_offending


@requires_postgres
def test_public_schema_closed_at_head(postgres_at_head: Engine):
    """Exit-gate assertion passes after #897: nothing outside the gold allowlist
    is reachable, and the backend's own (non-anon/authenticated) access is untouched."""
    _ensure_client_roles(postgres_at_head)

    violations = find_privilege_violations(_database_url())

    assert violations == {}


@requires_postgres
def test_new_public_table_born_closed_then_flagged_if_granted(postgres_at_head: Engine):
    """ALTER DEFAULT PRIVILEGES closes future public tables automatically (#897 AC1);
    explicitly granting one back open makes the exit-gate assertion fail again (#897
    exit-gate AC3 — "adding a new unprotected table... makes the assertion fail")."""
    _ensure_client_roles(postgres_at_head)
    scratch_table = "scratch_897_unprotected_table"

    with postgres_at_head.begin() as conn:
        conn.execute(text(f"CREATE TABLE {scratch_table} (id uuid PRIMARY KEY)"))

    try:
        # Born closed: no explicit GRANT was issued, so default privileges apply.
        reachable_after_create = {
            table
            for role in POSTGREST_CLIENT_ROLES
            for table in find_reachable_tables(postgres_at_head, role)
        }
        assert ("public", scratch_table) not in reachable_after_create

        # Simulate the exact drift this migration exists to prevent: a future
        # table lands with an explicit (or bootstrap-inherited) client grant.
        with postgres_at_head.begin() as conn:
            conn.execute(text(f"GRANT SELECT ON {scratch_table} TO anon"))

        violations = find_privilege_violations(_database_url())
        assert ("public", scratch_table) in violations.get("anon", [])
    finally:
        with postgres_at_head.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {scratch_table}"))


@requires_postgres
def test_gold_allowlist_is_the_single_client_reachable_entry(postgres_at_head: Engine):
    """The gold serving surface stays the one allowlist entry (#897 AC5) — not a
    convenience USAGE grant on the whole gold schema (ADR-061 doNotInfer)."""
    assert GOLD_ALLOWLIST == frozenset({("gold", "kpi_envelopes")})
    _ensure_client_roles(postgres_at_head)
    for role in POSTGREST_CLIENT_ROLES:
        assert ("gold", "ml_feature_snapshots") not in find_reachable_tables(postgres_at_head, role)


@requires_postgres
def test_gold_kpi_envelopes_table_exists_at_head(postgres_at_head: Engine):
    """Revision 024 adds gold.kpi_envelopes serving contract (#606)."""
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    for column in ("shop_id", "computed_at", "envelope_version", "payload"):
        cols = {
            c["name"]
            for c in inspect(postgres_at_head).get_columns(REVISION_024_GOLD_TABLE, schema="gold")
        }
        assert column in cols


@requires_postgres
def test_gold_kpi_envelopes_compat_view_payload_kpis(postgres_at_head: Engine):
    """Compat view preserves payload.kpis shape for migrated legacy rows (#606)."""
    cfg = _alembic_config()
    command.downgrade(cfg, "021_medallion_schemas")
    ids = _seed_representative_rows(postgres_at_head)
    _seed_legacy_analytics_envelope(postgres_at_head, ids["shop_id"])
    command.upgrade(cfg, "head")

    assert _view_exists(postgres_at_head, REVISION_024_COMPAT_VIEW)
    with postgres_at_head.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT payload->'kpis' AS kpis, kind
                FROM analytics_kpi_envelopes_compat
                WHERE shop_id = :shop_id
                """
            ),
            {"shop_id": ids["shop_id"]},
        ).one()
        gold_row = conn.execute(
            text(
                """
                SELECT payload->'kpis' AS kpis
                FROM gold.kpi_envelopes
                WHERE shop_id = :shop_id
                """
            ),
            {"shop_id": ids["shop_id"]},
        ).one()

    assert row.kind == "analytics"
    assert row.kpis is not None
    assert row.kpis == gold_row.kpis
    assert "gmv_tiktok" in row.kpis


@requires_postgres
def test_legacy_analytics_kpi_envelopes_writes_blocked_at_head(
    postgres_at_head: Engine,
):
    """Legacy public table rejects writes after gold cutover (#606 AC4)."""
    ids = _seed_representative_rows(postgres_at_head)
    with postgres_at_head.begin() as conn:
        with pytest.raises(Exception, match="read-only after gold cutover"):
            conn.execute(
                text(
                    """
                    INSERT INTO analytics_kpi_envelopes (
                        id, shop_id, kind, envelope_version, payload, computed_at
                    )
                    VALUES (
                        :id, :shop_id, 'analytics', 1, '{}'::jsonb, now()
                    )
                    """
                ),
                {"id": uuid.uuid4(), "shop_id": ids["shop_id"]},
            )


@requires_postgres
def test_latest_downgrade_drops_only_revision_024_gold(postgres_at_head: Engine):
    """Downgrading head removes gold.kpi_envelopes; medallion schemas remain."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    assert _view_exists(postgres_at_head, REVISION_024_COMPAT_VIEW)

    # Head is 025; target 023 so 024 downgrade runs explicitly (not just 025 via -1).
    command.downgrade(cfg, "023_bronze_orders_returns")

    assert not _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    assert not _view_exists(postgres_at_head, REVISION_024_COMPAT_VIEW)
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_021_TABLE)

    command.upgrade(cfg, "head")
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    assert _view_exists(postgres_at_head, REVISION_024_COMPAT_VIEW)


@requires_postgres
def test_silver_orders_returns_tables_exist_at_head(postgres_at_head: Engine):
    """Revision 025 adds silver.orders / silver.returns with natural keys (#607)."""
    for table in REVISION_025_SILVER_TABLES:
        assert _table_exists_in_schema(postgres_at_head, "silver", table)
    assert _table_has_column_in_schema(postgres_at_head, "silver", "orders", "tiktok_order_id")
    assert _table_has_column_in_schema(postgres_at_head, "silver", "returns", "tiktok_return_id")


@requires_postgres
def test_silver_orders_returns_natural_key_unique(postgres_at_head: Engine):
    """silver.orders / silver.returns enforce (shop_id, tiktok_*_id) uniqueness (#607)."""
    ids = _seed_representative_rows(postgres_at_head)
    with postgres_at_head.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO silver.orders (
                        id, shop_id, tiktok_order_id, status, total_amount,
                        currency, update_time
                    )
                    VALUES (
                        :id, :shop_id, :tiktok_order_id, :status, :total_amount,
                        :currency, :update_time
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "shop_id": ids["shop_id"],
                    "tiktok_order_id": "migration_order_365",
                    "status": "COMPLETED",
                    "total_amount": Decimal("1.00"),
                    "currency": "USD",
                    "update_time": datetime.now(UTC).replace(tzinfo=None),
                },
            )


@requires_postgres
def test_legacy_public_orders_returns_writes_blocked_at_head(postgres_at_head: Engine):
    """Legacy public.orders / public.returns reject writes after silver cutover (#607)."""
    ids = _seed_representative_rows(postgres_at_head)
    now = datetime.now(UTC).replace(tzinfo=None)
    with postgres_at_head.begin() as conn:
        with pytest.raises(Exception, match="read-only after silver cutover"):
            conn.execute(
                text(
                    """
                    INSERT INTO orders (
                        id, shop_id, tiktok_order_id, status, total_amount,
                        currency, update_time
                    )
                    VALUES (
                        :id, :shop_id, :tiktok_order_id, :status, :total_amount,
                        :currency, :update_time
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "shop_id": ids["shop_id"],
                    "tiktok_order_id": "blocked_order_607",
                    "status": "COMPLETED",
                    "total_amount": Decimal("1.00"),
                    "currency": "USD",
                    "update_time": now,
                },
            )
    with postgres_at_head.begin() as conn:
        with pytest.raises(Exception, match="read-only after silver cutover"):
            conn.execute(
                text(
                    """
                    INSERT INTO returns (
                        id, shop_id, tiktok_return_id, tiktok_order_id,
                        return_type, refund_amount, status, update_time
                    )
                    VALUES (
                        :id, :shop_id, :tiktok_return_id, :tiktok_order_id,
                        :return_type, :refund_amount, :status, :update_time
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "shop_id": ids["shop_id"],
                    "tiktok_return_id": "blocked_return_607",
                    "tiktok_order_id": "migration_order_365",
                    "return_type": "other",
                    "refund_amount": Decimal("1.00"),
                    "status": "pending_review",
                    "update_time": now,
                },
            )


@requires_postgres
def test_bronze_to_silver_promotion_integration(postgres_at_head: Engine):
    """Bronze append → silver upsert without gold KPI or live Partner (#607)."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.repositories.repos import BronzeOrderRawPayloadsRepo
    from juli_backend.services.etl.silver_promotion import SilverOrdersReturnsPromoter

    ids = _seed_representative_rows(postgres_at_head)
    shop_id = ids["shop_id"]
    received_at = datetime(2026, 7, 30, 16, 0, tzinfo=UTC)

    async def _run() -> None:
        url = _database_url()
        engine = create_async_engine(async_database_url(url))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            bronze_repo = BronzeOrderRawPayloadsRepo(session)
            promoter = SilverOrdersReturnsPromoter(session)
            rows = await bronze_repo.append_batch(
                [
                    {
                        "shop_id": shop_id,
                        "ingest_source": "webhook",
                        "payload": {
                            "order_id": "607_integration_order",
                            "order_status": "AWAITING_SHIPMENT",
                            "total_amount": "55.00",
                            "currency": "VND",
                            "update_time": int(received_at.timestamp()),
                        },
                        "received_at": received_at,
                        "tiktok_order_id": "607_integration_order",
                        "source_event_id": "evt-607-integration",
                    },
                ]
            )
            order = await promoter.promote_order(rows[0])
            await session.commit()
            assert order.tiktok_order_id == "607_integration_order"

        await engine.dispose()

    asyncio.run(_run())

    with postgres_at_head.connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM silver.orders
                WHERE shop_id = :shop_id AND tiktok_order_id = :tiktok_order_id
                """
            ),
            {"shop_id": shop_id, "tiktok_order_id": "607_integration_order"},
        ).scalar_one()
    assert count == 1


@requires_postgres
def test_downgrade_to_024_drops_revision_025_silver(postgres_at_head: Engine):
    """Downgrading to 024 removes silver orders/returns; gold tables remain.

    Targets revision 024 explicitly rather than ``-1``: since #715/#716/#717 added
    026/027/028, silver is no longer the newest revision, so ``-1`` would step back
    through the Decision slices instead. The invariant under test is unchanged.
    """
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    for table in REVISION_025_SILVER_TABLES:
        assert _table_exists_in_schema(postgres_at_head, "silver", table)

    command.downgrade(cfg, "024_gold_kpi_envelopes")

    for table in REVISION_025_SILVER_TABLES:
        assert not _table_exists_in_schema(postgres_at_head, "silver", table)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)

    command.upgrade(cfg, "head")
    for table in REVISION_025_SILVER_TABLES:
        assert _table_exists_in_schema(postgres_at_head, "silver", table)


@requires_postgres
def test_latest_downgrade_drops_only_revision_028_demo_execution(postgres_at_head: Engine):
    """Downgrading to 027 removes 028's table; 025/024 objects remain.

    Targets revision 027 explicitly rather than ``-1``: since #897 added
    029_close_public_schema_defaults, head is no longer 028, so ``-1`` would only
    undo 029's privilege revoke rather than 028's table. The invariant under test
    (028's downgrade drops only its own table) is unchanged.
    """
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists(postgres_at_head, REVISION_028_DEMO_EXECUTION_TABLE)

    command.downgrade(cfg, "027_decision_emission_budget")

    assert not _table_exists(postgres_at_head, REVISION_028_DEMO_EXECUTION_TABLE)
    for table in REVISION_025_SILVER_TABLES:
        assert _table_exists_in_schema(postgres_at_head, "silver", table)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)

    command.upgrade(cfg, "head")
    assert _table_exists(postgres_at_head, REVISION_028_DEMO_EXECUTION_TABLE)


@requires_postgres
def test_latest_downgrade_drops_only_revision_021_medallion(postgres_at_head: Engine):
    """Downgrading past 024 then 021 removes medallion schemas; 020 public tables remain."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_021_TABLE)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)

    command.downgrade(cfg, "020_analytics_kpi_envelopes")

    for schema in MEDALLION_SCHEMAS:
        assert not _schema_exists(postgres_at_head, schema)
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert not _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)

    command.upgrade(cfg, "head")
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_021_TABLE)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)


@requires_postgres
def test_analytics_kpi_envelopes_table_exists_at_head(postgres_at_head: Engine):
    """Revision 020 adds analytics_kpi_envelopes (#525)."""
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    for column in (
        "id",
        "shop_id",
        "kind",
        "envelope_version",
        "payload",
        "computed_at",
        "created_at",
        "updated_at",
    ):
        assert _table_has_column(postgres_at_head, REVISION_020_TABLE, column)


@requires_postgres
def test_latest_downgrade_drops_only_revision_020_table(postgres_at_head: Engine):
    """Downgrading past 020 removes analytics_kpi_envelopes; 019 table remains."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)

    command.downgrade(cfg, "019_backfill_partitions")

    assert not _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)

    command.upgrade(cfg, "head")
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)


@requires_postgres
def test_latest_downgrade_drops_only_revision_019_table(postgres_at_head: Engine):
    """Downgrading past 019 removes analytics_backfill_partitions; 018 columns remain."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)

    command.downgrade(cfg, "018_interval_backfill_cols")

    assert not _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)

    command.upgrade(cfg, "head")
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)


@requires_postgres
def test_latest_downgrade_drops_only_revision_017_table(postgres_at_head: Engine):
    """Downgrading past 017 removes analytics_performance_intervals; 016 table remains."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    assert _table_exists(postgres_at_head, REVISION_016_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)
    for column in REVISION_015_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_012_TABLE, column)

    command.downgrade(cfg, "016_webhook_raw_events")

    assert not _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert not _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_017_TABLE)
    assert _table_exists(postgres_at_head, REVISION_016_TABLE)
    assert _table_exists(postgres_at_head, REVISION_014_TABLE)
    for column in REVISION_015_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_012_TABLE, column)

    command.upgrade(cfg, "head")
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    assert _table_exists(postgres_at_head, REVISION_016_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)


@requires_postgres
def test_latest_downgrade_drops_only_revision_018_columns(postgres_at_head: Engine):
    """Downgrading to 017 removes 018 columns; analytics_performance_intervals remains."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)

    command.downgrade(cfg, "017_analytics_perf_intervals")

    assert not _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    for column in REVISION_018_COLUMNS:
        assert not _table_has_column(postgres_at_head, REVISION_017_TABLE, column)

    command.upgrade(cfg, "head")
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)


@requires_postgres
def test_latest_downgrade_drops_only_revision_015_columns(postgres_at_head: Engine):
    """Downgrading past 015 removes tool_execution columns; 014 table remains."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists(postgres_at_head, REVISION_014_TABLE)
    for column in REVISION_015_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_012_TABLE, column)

    command.downgrade(cfg, "014_action_cards")

    assert _table_exists(postgres_at_head, REVISION_014_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_016_TABLE)
    for column in REVISION_015_COLUMNS:
        assert not _table_has_column(postgres_at_head, REVISION_012_TABLE, column)
    for table, columns in REVISION_010_COLUMNS.items():
        for column in columns:
            assert _table_has_column(postgres_at_head, table, column)

    with postgres_at_head.connect() as conn:
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one()
        product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar_one()
        sync_state_count = conn.execute(text("SELECT COUNT(*) FROM tiktok_sync_state")).scalar_one()

    assert order_count == 1
    assert product_count == 1
    assert sync_state_count == 1

    command.upgrade(cfg, "head")
    for column in REVISION_015_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_012_TABLE, column)
    assert _table_exists(postgres_at_head, REVISION_016_TABLE)
    assert _table_exists(postgres_at_head, REVISION_017_TABLE)
    assert not _table_exists(postgres_at_head, REVISION_019_TABLE)
    assert _table_exists_in_schema(postgres_at_head, REVISION_022_SCHEMA, REVISION_019_TABLE)
    assert _table_exists(postgres_at_head, REVISION_020_TABLE)
    for column in REVISION_018_COLUMNS:
        assert _table_has_column(postgres_at_head, REVISION_017_TABLE, column)


@requires_postgres
def test_unique_constraints_enforced_after_migration_round_trip(
    postgres_at_head: Engine,
):
    """Unique indexes from earlier migrations remain enforced after a round trip."""
    ids = _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")

    with postgres_at_head.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO silver.orders (
                        id, shop_id, tiktok_order_id, status, total_amount,
                        currency, update_time
                    )
                    VALUES (
                        :id, :shop_id, :tiktok_order_id, :status, :total_amount,
                        :currency, :update_time
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "shop_id": ids["shop_id"],
                    "tiktok_order_id": "migration_order_365",
                    "status": "COMPLETED",
                    "total_amount": Decimal("1.00"),
                    "currency": "USD",
                    "update_time": datetime.now(UTC).replace(tzinfo=None),
                },
            )

    with postgres_at_head.connect() as conn:
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == LATEST_REVISION
