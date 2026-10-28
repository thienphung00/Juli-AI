"""P71: a product is never "Unknown" on a seller-facing card.

Production 2026-10-28, sandbox shop: BN-500 (created in Seller Center the day before,
already with delivered orders) showed on Quyết định as "Tạo khuyến mãi giảm giá cho
Unknown". Its PRODUCT_STATUS_CHANGE webhook (product id, status, update time -- no title)
went through the ETL product transform, which filled the snapshot defaults: title and name
"Unknown", revenue 0. The poll's Search Products read carries the title, but the upsert
refused it (same ``update_time`` = stale), and the incremental cursor never fetched the
product again.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.models import ActionCard, InventoryItem, Product, Shop, User
from juli_backend.repositories.repos import ProductsRepo
from juli_backend.services.demo_decisions.card_view import CardContext, build_card_block
from juli_backend.services.demo_decisions.read import _mask_recommendation_payload
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.etl.transform import transform_for_channel
from juli_backend.services.product_name import known_product_name, short_product_name
from juli_backend.services.reviewer import create_promotion_card as card_module
from juli_backend.workers.services.polling.orchestrate import _reread_products_when_unnamed
from tests.support.api import build_app, client_for
from tests.unit import test_reviewer_sandbox_create_product as p64
from tests.unit import test_reviewer_sandbox_create_promotion as p65
from tests.unit.test_reviewer_sandbox_create_product import _headers

reviewer_env = p64.reviewer_env
world = p64.world
card_tiktok = p65.card_tiktok
frozen_clock = p65.frozen_clock

NUMERIC_SHOP_ID = "7000000000000071"
PRODUCT_ID = "1738221500563949187"
TITLE = "Bình Nước Thép Không Gỉ 500ml Nắp Bật Tiện Lợi"
CREATED = 1_761_541_740
ACTIVATED = 1_761_541_860
WEBHOOK_CHANNEL = "tiktok.product_status_change"
POLL_CHANNEL = "tiktok.products.raw"


def _naive(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC).replace(tzinfo=None)


def _webhook(status: str = "ACTIVATE", *, update_time: int = ACTIVATED) -> dict[str, Any]:
    return {
        "type": 5,
        "tts_notification_id": f"n-{uuid.uuid4().hex[:8]}",
        "shop_id": NUMERIC_SHOP_ID,
        "timestamp": update_time + 5,
        "data": {"product_id": PRODUCT_ID, "status": status, "update_time": update_time},
    }


def _poll_product(*, update_time: int = ACTIVATED) -> dict[str, Any]:
    """Search Products' product, as ``sync_products`` hands it off (normalized)."""
    return {
        "id": PRODUCT_ID,
        "product_id": PRODUCT_ID,
        "title": TITLE,
        "name": TITLE,
        "status": "ACTIVATE",
        "create_time": CREATED,
        "update_time": update_time,
        "price": "99000",
        "price_currency": "VND",
    }


@pytest_asyncio.fixture
async def shop(session):
    user = User(id=uuid.uuid4(), phone="+84907000071")
    session.add(user)
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="P71", tiktok_shop_id=NUMERIC_SHOP_ID)
    session.add(shop)
    await session.commit()
    return shop


async def _ingest(session, channel: str, payload: dict, **kwargs) -> ProcessOutcome:
    async def _dlq(channel: str, key: str, value: bytes) -> None:
        raise AssertionError(json.loads(value))

    consumer = EtlConsumer(session=session, dlq_handoff=_dlq, **kwargs)
    outcome = await consumer.ingest(
        IngestRecord(channel=channel, shop_key=NUMERIC_SHOP_ID, value=json.dumps(payload).encode())
    )
    await session.commit()
    return outcome


async def _the_product(session, shop) -> Product:
    stmt = (
        select(Product).where(Product.shop_id == shop.id).execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one()


# --- the transform: a status webhook carries no name --------------------------------------


def test_a_status_webhook_is_a_partial_product_write():
    kind, kwargs = transform_for_channel(WEBHOOK_CHANNEL, _webhook())
    assert kind == "product"
    assert kwargs == {
        "tiktok_product_id": PRODUCT_ID,
        "update_time": _naive(ACTIVATED),
        "audit_status": "activate",
        "status": "ACTIVATE",
    }


def test_the_poll_product_is_still_a_whole_snapshot():
    kind, kwargs = transform_for_channel(POLL_CHANNEL, _poll_product())
    assert kind == "product"
    assert kwargs["title"] == kwargs["name"] == TITLE
    assert kwargs["price"] == Decimal("99000")


# --- the merge: webhook first, then the poll --------------------------------------------


async def test_webhook_first_then_poll_with_the_same_update_time_names_the_product(session, shop):
    """The production sequence for a product created in Seller Center."""
    outcome = await _ingest(session, WEBHOOK_CHANNEL, _webhook(), scope_to_resolved_shop=True)
    assert outcome is ProcessOutcome.PROCESSED
    created = await _the_product(session, shop)
    assert known_product_name(created.title, created.name) is None  # not named yet
    assert created.status == "ACTIVATE"

    await _ingest(session, POLL_CHANNEL, _poll_product())

    product = await _the_product(session, shop)
    assert product.title == product.name == TITLE
    assert product.price == Decimal("99000")
    assert product.tiktok_created_at == _naive(CREATED)


async def test_a_stale_poll_still_fills_an_unknown_name(session, shop):
    """A row stored as "Unknown" before P71 is named by the next poll, whatever its time."""
    session.add(
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=PRODUCT_ID,
            title="Unknown",
            name="Unknown",
            status="ACTIVATE",
            update_time=_naive(ACTIVATED),
        )
    )
    await session.commit()

    await _ingest(session, POLL_CHANNEL, _poll_product(update_time=ACTIVATED - 60))

    product = await _the_product(session, shop)
    assert product.title == product.name == TITLE
    assert product.update_time == _naive(ACTIVATED)


async def test_a_newer_status_webhook_changes_the_status_and_keeps_name_and_sales(session, shop):
    await _ingest(session, POLL_CHANNEL, _poll_product(update_time=CREATED))
    product = await _the_product(session, shop)
    product.revenue, product.units_sold = Decimal("297000"), 3
    await session.commit()

    await _ingest(
        session, WEBHOOK_CHANNEL, _webhook("SELLER_DEACTIVATED"), scope_to_resolved_shop=True
    )

    product = await _the_product(session, shop)
    assert product.status == "SELLER_DEACTIVATED"
    assert product.title == product.name == TITLE
    assert product.price == Decimal("99000")
    assert (product.revenue, product.units_sold) == (Decimal("297000"), 3)


# --- the poll re-reads the catalog while a product has no name ---------------------------


async def test_the_poll_drops_its_products_cursor_while_a_product_is_unnamed(session, shop):
    session.add(
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=PRODUCT_ID,
            title="Unknown",
            name="Unknown",
            status="ACTIVATE",
            update_time=_naive(ACTIVATED),
        )
    )
    await session.commit()
    state: dict[str, Any] = {"products_last_update_time": ACTIVATED, "orders_last": 1}

    assert await ProductsRepo(session).has_unnamed_products(shop.id) is True
    await _reread_products_when_unnamed(session, shop.id, state)

    assert state == {"orders_last": 1}


async def test_the_poll_keeps_its_cursor_when_every_product_is_named(session, shop):
    await _ingest(session, POLL_CHANNEL, _poll_product())
    state: dict[str, Any] = {"products_last_update_time": ACTIVATED}

    assert await ProductsRepo(session).has_unnamed_products(shop.id) is False
    await _reread_products_when_unnamed(session, shop.id, state)

    assert state == {"products_last_update_time": ACTIVATED}


# --- the guard: never "Unknown" in a seller-facing title -----------------------------------


async def _name_product(session, product_id: uuid.UUID, name: str) -> None:
    product = await session.get(Product, product_id)
    product.title = product.name = name
    await session.commit()


async def _promo(session, ids, reviewer_id) -> dict[str, Any] | None:
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
    assert listed.status_code == 200, listed.text
    return p65._promo_card(listed.json()["data"])


async def test_an_unnamed_product_gets_its_seller_sku_on_the_promotion_card(session, world):
    ids, reviewer_id = world
    await _name_product(session, ids["product"], "Unknown")

    item = await _promo(session, ids, reviewer_id)

    assert item is not None
    assert item["title"] == "Tạo khuyến mãi giảm giá cho SKU SBX-01"
    assert item["recommendation"]["card"]["product_title"] == (
        "Tạo khuyến mãi giảm giá cho SKU SBX-01"
    )
    assert "Unknown" not in json.dumps(item, ensure_ascii=False)


async def test_no_promotion_card_when_neither_a_name_nor_a_sku_is_known(session, world):
    ids, reviewer_id = world
    await _name_product(session, ids["product"], "Unknown")
    for row in (await session.execute(select(InventoryItem))).scalars():
        row.seller_sku = None
    await session.commit()

    assert await _promo(session, ids, reviewer_id) is None
    assert await p65._promo_rows(session, ids["sandbox"]) == []


async def test_a_card_made_as_unknown_is_remade_with_the_synced_name(session, world):
    ids, reviewer_id = world
    await _name_product(session, ids["product"], "Unknown")
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=ids["sandbox"],
        workflow_key="create_promotion",
        subject_type="product",
        subject_id=str(ids["product"]),
        revision=1,
        priority=0,
        severity="medium",
        title="Tạo khuyến mãi giảm giá cho Unknown",
        description="",
        recommendation_payload=json.dumps(
            {
                "workflow_key": "create_promotion",
                "diagnosis": {
                    "lever": {"code": "create_promotion"},
                    "product_title": "Unknown",
                    "tiktok_product_id": p64.SOURCE_ID,
                },
            }
        ),
        status="active",
        computed_at=datetime.now(UTC),
        surfaced_at=datetime.now(UTC),
    )
    session.add(card)
    await session.commit()
    await _name_product(session, ids["product"], "Bình giữ nhiệt inox 750ml")
    card_module.reset_cache()

    item = await _promo(session, ids, reviewer_id)

    assert item is not None and item["id"] != str(card.id)
    assert item["title"] == "Tạo khuyến mãi giảm giá cho Bình giữ nhiệt inox 750ml"
    assert item["recommendation"]["diagnosis"]["product_title"] == "Bình giữ nhiệt inox 750ml"
    rows = {row.id: row.status for row in await p65._promo_rows(session, ids["sandbox"])}
    assert rows[card.id] == "expired"


def _listing_card(product_title: str) -> tuple[ActionCard, dict[str, Any]]:
    payload = {
        "diagnosis": {
            "lever": {"code": "create_promotion"},
            "stage": {"code": "promotion"},
            "main_kpi": {"key": "promotion", "label": "Khuyến mãi", "value": "+1"},
            "product_title": product_title,
            "tiktok_product_id": PRODUCT_ID,
        }
    }
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        workflow_key="create_promotion",
        subject_type="product",
        subject_id=str(uuid.uuid4()),
        title="t",
        status="active",
        computed_at=datetime.now(UTC),
        surfaced_at=datetime.now(UTC),
    )
    return card, payload


def _unknown_product() -> Product:
    return Product(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        tiktok_product_id=PRODUCT_ID,
        title="Unknown",
        name="Unknown",
        status="ACTIVATE",
        update_time=datetime(2026, 10, 27),
    )


def test_the_card_view_falls_back_to_the_seller_sku_never_unknown():
    card, payload = _listing_card("Unknown")
    context = CardContext(product=_unknown_product(), seller_skus=["BN-500"], sku_count=1)

    block = build_card_block(card, payload, context)

    assert block is not None
    assert block["product_title"] == "Tạo khuyến mãi giảm giá cho SKU BN-500"
    assert block["status"] == "pending"  # a placeholder is not a title change


def test_the_card_view_uses_the_pinned_name_while_the_product_is_unnamed():
    card, payload = _listing_card(TITLE)
    context = CardContext(product=_unknown_product(), seller_skus=["BN-500"], sku_count=1)

    block = build_card_block(card, payload, context)

    assert block is not None
    assert block["product_title"] == f"Tạo khuyến mãi giảm giá cho {short_product_name(TITLE)}"
    assert block["status"] == "pending"


def test_the_decisions_read_never_serves_an_unknown_product_title():
    _, payload = _listing_card("Unknown")
    assert _mask_recommendation_payload(payload)["diagnosis"]["product_title"] is None
