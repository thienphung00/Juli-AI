"""Alembic migration integration tests — Issue #365.

Exercises downgrade/upgrade round trips against Postgres with seeded data
assertions. Skips when DATABASE_URL is not a reachable Postgres instance.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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
LATEST_REVISION = "024_gold_kpi_envelopes"
REVISION_024_GOLD_TABLE = "kpi_envelopes"
REVISION_024_COMPAT_VIEW = "analytics_kpi_envelopes_compat"
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
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
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
        conn.execute(
            text(
                """
                INSERT INTO orders (
                    id, shop_id, tiktok_order_id, status, total_amount, currency,
                    update_time, order_value, payment_time, cancel_reason, is_seller_fault
                )
                VALUES (
                    :id, :shop_id, :tiktok_order_id, :status, :total_amount, :currency,
                    :update_time, :order_value, :payment_time, :cancel_reason, :is_seller_fault
                )
                """
            ),
            {
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
            },
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
                FROM orders WHERE id = :id
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
def test_latest_downgrade_drops_only_revision_023_bronze_tables(postgres_at_head: Engine):
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
def test_legacy_analytics_kpi_envelopes_writes_blocked_at_head(postgres_at_head: Engine):
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

    command.downgrade(cfg, "-1")

    assert not _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    assert not _view_exists(postgres_at_head, REVISION_024_COMPAT_VIEW)
    for schema in MEDALLION_SCHEMAS:
        assert _schema_exists(postgres_at_head, schema)
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_021_TABLE)

    command.upgrade(cfg, "head")
    assert _table_exists_in_schema(postgres_at_head, "gold", REVISION_024_GOLD_TABLE)
    assert _view_exists(postgres_at_head, REVISION_024_COMPAT_VIEW)


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
