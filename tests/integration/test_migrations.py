"""Alembic migration integration tests — Issue #365.

Exercises downgrade/upgrade round trips against Postgres with seeded data
assertions. Skips when DATABASE_URL is not a reachable Postgres instance.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from juli_backend.core.config.runtime import sync_database_url

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
LATEST_REVISION = "011_workflow_webhook_signals"
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


def _table_exists(engine: Engine, table: str) -> bool:
    return table in inspect(engine).get_table_names()


def _seed_representative_rows(engine: Engine) -> dict[str, uuid.UUID]:
    """Insert rows touching migrations 009 (sync state) and 010 (order/product fields)."""
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    order_id = uuid.uuid4()
    product_id = uuid.uuid4()
    sync_state_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

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
            text(
                "SELECT shop_name, tiktok_shop_id FROM shops WHERE id = :id"
            ),
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
def test_latest_downgrade_drops_only_revision_011_table(postgres_at_head: Engine):
    """Downgrading the head revision removes the workflow_webhook_signals table."""
    _seed_representative_rows(postgres_at_head)
    cfg = _alembic_config()

    assert _table_exists(postgres_at_head, REVISION_011_TABLE)

    command.downgrade(cfg, "-1")

    assert not _table_exists(postgres_at_head, REVISION_011_TABLE)
    for table, columns in REVISION_010_COLUMNS.items():
        for column in columns:
            assert _table_has_column(postgres_at_head, table, column)

    with postgres_at_head.connect() as conn:
        order_count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one()
        product_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar_one()
        sync_state_count = conn.execute(
            text("SELECT COUNT(*) FROM tiktok_sync_state")
        ).scalar_one()

    assert order_count == 1
    assert product_count == 1
    assert sync_state_count == 1

    command.upgrade(cfg, "head")
    assert _table_exists(postgres_at_head, REVISION_011_TABLE)


@requires_postgres
def test_unique_constraints_enforced_after_migration_round_trip(postgres_at_head: Engine):
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
                    "update_time": datetime.now(timezone.utc).replace(tzinfo=None),
                },
            )

    revision = postgres_at_head.connect().execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    assert revision == LATEST_REVISION
