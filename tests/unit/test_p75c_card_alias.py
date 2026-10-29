"""P75c: a card's product alias is its own product's, never a namesake's.

Live 29/10 on the masked pin: duplicate listings of one item (identical title, the same
seller SKU codes in a different order) all read one "Sản phẩm NNN" on their Quyết định
content cards, while Phân tích -- keyed on each product's TikTok id -- gave each its own.
The card named its product only by seller SKU and title, and the catalog mapped a shared
SKU code / title to the first listing. Synthetic shop and products only.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from juli_backend.models.models import ActionCard, InventoryItem, Product
from juli_backend.services.content_cards import emission
from juli_backend.services.demo_decisions.card_view import load_card_contexts
from juli_backend.services.demo_decisions.read import mask_decision_payload
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer.masking import MaskDictionary, mask_payload, title_alias
from tests.support.lever_flows import seed_shop

NOW = datetime.now(UTC)
SHARED_TITLE = "Bình giữ nhiệt Sao Mai inox 750ml"
SHARED_SKUS = ("SM750-A", "SM750-B", "SM750-C")
#: Three listings of one item: same title, same SKU codes, each starting from another code.
PRODUCTS = {
    "1729000000000000201": ("SM750-A", "SM750-B", "SM750-C"),
    "1729000000000000202": ("SM750-B", "SM750-C", "SM750-A"),
    "1729000000000000203": ("SM750-C", "SM750-A", "SM750-B"),
}


def _row(rid: str, product: str, gmv: float) -> dict:
    return {
        "id": rid,
        "name": f"Clip {rid}",
        "gmv_per_day": gmv,
        "last": 0.019,
        "prior": 0.032,
        "quantity_last": 2249,
        "date": "2026-10-02",
        "product_ids": [product],
    }


async def _seed(session):
    shop, _ = await seed_shop(session)
    for tiktok_id, skus in PRODUCTS.items():
        session.add(
            Product(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id=tiktok_id,
                title=SHARED_TITLE,
                name=SHARED_TITLE,
                status="ACTIVATE",
                update_time=datetime(2026, 10, 1),
            )
        )
        for i, sku in enumerate(skus):
            session.add(
                InventoryItem(
                    shop_id=shop.id,
                    tiktok_product_id=tiktok_id,
                    tiktok_sku_id=f"{tiktok_id}{i}",
                    quantity=10,
                    seller_sku=sku,
                    update_time=datetime(2026, 10, 1),
                )
            )
    await session.flush()
    return shop


async def test_namesake_listings_read_their_own_alias_on_cards_and_in_phan_tich(session):
    shop = await _seed(session)
    rows = [_row(f"v{i}", pid, -50_000 - i) for i, pid in enumerate(PRODUCTS)]
    table = {
        "stream": "seller_video",
        "metric": "ctr",
        "stream_prior": 0.032,
        "down": rows,
        "up": [],
    }
    await emission.emit_content_cards(session, shop.id, now=NOW, rankings={"video": table})
    cards = list(
        (await session.execute(select(ActionCard).where(ActionCard.shop_id == shop.id))).scalars()
    )
    assert len(cards) == len(PRODUCTS)
    contexts = await load_card_contexts(session, shop.id, cards)
    items = [mask_decision_payload(card, card_context=contexts[card.id]) for card in cards]
    raw_cards = [item["recommendation"]["card"] for item in items]
    # Each card names its own product, and the listings really do collide on title and SKU.
    assert sorted(c["tiktok_product_id"] for c in raw_cards) == sorted(PRODUCTS)
    assert {c["product_title"] for c in raw_cards} == {SHARED_TITLE}
    assert {c["seller_sku"] for c in raw_cards} == set(SHARED_SKUS)

    reviewer_catalog.forget_cached()
    dictionary = await reviewer_catalog.load_dictionary(session, shop)
    reviewer_catalog.forget_cached()
    masked = mask_payload({"data": json.loads(json.dumps(items))}, dictionary)
    analysis = mask_payload({"titles": dict.fromkeys(PRODUCTS, SHARED_TITLE)}, dictionary)
    on_cards = {}
    for raw, item in zip(raw_cards, masked["data"], strict=True):
        card = item["recommendation"]["card"]
        on_cards[card["tiktok_product_id"]] = card["product_title"]
        assert card["product_title"] == title_alias("product", raw["tiktok_product_id"])
    # Phân tích's map is keyed by the same masked product id: the same alias per product.
    assert on_cards == analysis["titles"]
    assert len(set(on_cards.values())) == len(PRODUCTS)
    assert SHARED_TITLE not in json.dumps(masked, ensure_ascii=False)


async def test_catalog_drops_references_several_listings_share(session):
    shop = await _seed(session)
    reviewer_catalog.forget_cached()
    refs = (await reviewer_catalog.load_dictionary(session, shop)).product_refs
    reviewer_catalog.forget_cached()
    assert SHARED_TITLE not in refs
    assert not set(SHARED_SKUS) & set(refs)
    # A TikTok SKU id is unique to its listing and still resolves.
    assert refs["17290000000000002011"] == "1729000000000000201"


def test_free_text_of_a_shared_title_names_no_single_listing():
    shop_id = uuid.uuid4()
    dictionary = MaskDictionary(shop_id=shop_id, alias_id=uuid.uuid4(), shop_name="Shop Thử")
    pids = list(PRODUCTS)
    payload = {
        "data": [
            {"title": f"Kịch bản video mới · {SHARED_TITLE}", "card": {
                "tiktok_product_id": pid, "product_title": SHARED_TITLE}}
            for pid in pids
        ]
    }  # fmt: skip
    masked = mask_payload(payload, dictionary)
    headings = {item["title"] for item in masked["data"]}
    product_aliases = {title_alias("product", pid) for pid in pids}
    assert len(headings) == 1
    (heading,) = headings
    assert heading.split(" · ")[1] not in product_aliases
    assert {item["card"]["product_title"] for item in masked["data"]} == product_aliases
