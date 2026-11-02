"""P86: brand / product-name scrub of free model text, behind the reviewer mask.

The dictionary misses a brand written another way or one that lives only inside product
titles. The catalog load derives brand words from the titles it already reads; the mask's
free-text pass scrubs them (case, diacritics, markup) and the operator's terms and a
payload's ``brand`` values too. Synthetic names only; the seller path is never masked.
"""

from __future__ import annotations

import json
import uuid

import pytest

from juli_backend.models.models import Product
from juli_backend.services.reviewer import brands
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer.config import shop_alias_id
from juli_backend.services.reviewer.masking import BRAND_REPLACEMENT, MaskDictionary, mask_payload
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for

TITLE_BRAND = "Lumiora"  # only inside product titles
FIELD_BRAND = "Ánh Dương"  # a ``brand.name`` field
OPERATOR_BRAND = "Zentavo"  # REVIEWER_MASK_TERMS
TITLES = (
    "Nồi chiên không dầu Lumiora LM-55 5.5L",
    "Bình giữ nhiệt Lumiora inox 750ml",
    "Ấm đun siêu tốc Lumiora 1.7L",
    "Thép không gỉ bình nước 750ml",
)
FREE_TEXT = [
    "Gợi ý: đổi tiêu đề sản phẩm lumiora để tăng CTR",
    "LUMIORA đang giảm CTR so với trung vị",
    "Lumióra vừa tăng đơn",
    "<b>Lumiora</b> và <i>ZENTAVO</i> trong bài viết",
    "Thử nghiệm zentavo, ANH DUONG, ánh dương.",
    "Ảnh <img alt='Lumiora'> cho (Zentavo)",
]
GENERIC = "Nồi Bình Thép 750ml inox chính hãng, Kích thước lớn"


def _dictionary() -> MaskDictionary:
    shop_id = uuid.uuid4()
    return MaskDictionary(
        shop_id=shop_id,
        alias_id=shop_alias_id(shop_id),
        shop_name="Cửa hàng Gốm Thử",
        extra_terms=(OPERATOR_BRAND,),
        catalog_brands=brands.derive_from_titles(TITLES),
    )


def _brand_payload() -> dict:
    return {"product": {"brand": {"name": FIELD_BRAND}, "tiktok_product_id": "1729000000000000999"}}


def _all_texts() -> list[dict]:
    return [
        {"narration": FREE_TEXT[0], "events": [{"type": "assistant.text", "text": t}]}
        for t in FREE_TEXT
    ]


def test_derivation_finds_a_brand_recurring_across_titles_only():
    assert brands.derive_from_titles(TITLES) == (TITLE_BRAND,)


def test_generic_words_are_never_derived_or_scrubbed():
    titles = ["Nồi Thép Bình 750ml", "Bình Nồi Thép 1L", "Thép Bình Nồi 2L", "Kích Thước Lớn"]
    assert brands.derive_from_titles(titles) == ()
    for word in ("Nồi", "Bình", "Thép", "750ml", "inox", "Kích thước"):
        assert brands.usable(word) is None
    out = mask_payload({"text": GENERIC}, _dictionary())
    assert out["text"] == GENERIC


def test_a_word_also_written_lowercase_in_titles_is_common():
    assert brands.derive_from_titles(["Gốm Kora sen", "Cốc Kora sen", "bộ kora"]) == ()
    assert brands.derive_from_titles(["Gốm Kora Tien", "Cốc Kora Tien"]) == ("Kora", "Tien")


@pytest.mark.parametrize("text", FREE_TEXT)
def test_free_text_is_scrubbed_in_every_casing_diacritic_and_markup(text):
    out = mask_payload(
        {
            "narration": text,
            "events": [{"type": "assistant.text", "text": text}],
            **_brand_payload(),
        },
        _dictionary(),
    )
    flat = json.dumps(out, ensure_ascii=False).lower()
    for brand in (TITLE_BRAND, OPERATOR_BRAND, "lumióra", "ánh dương", "anh duong"):
        assert brand.lower() not in flat
    assert BRAND_REPLACEMENT in flat.title() or BRAND_REPLACEMENT.lower() in flat


def test_card_reason_and_content_draft_are_scrubbed():
    payload = {
        "reason": "Tiêu đề Lumiora chưa có từ khóa",
        "recommendation": {"draft": "<p>Mua lumiora chính hãng</p>", "brand_name": FIELD_BRAND},
    }
    out = mask_payload(payload, _dictionary())
    text = json.dumps(out, ensure_ascii=False)
    assert "umiora" not in text and FIELD_BRAND not in text
    assert out["recommendation"]["draft"] == f"<p>Mua {BRAND_REPLACEMENT} chính hãng</p>"


def test_whole_word_only_and_idempotent():
    dictionary = _dictionary()
    once = mask_payload({"text": "Lumiorana và Lumiora."}, dictionary)
    assert once["text"] == f"Lumiorana và {BRAND_REPLACEMENT}."
    twice = mask_payload(once, dictionary)
    assert twice == once


def test_scrub_keeps_offsets_with_decomposed_diacritics():
    folded = brands.fold("Đường Ánh Dương")
    assert folded == "duong anh duong" and len(folded) == len("Đường Ánh Dương")


async def test_catalog_derives_brands_from_titles_it_already_reads(session):
    reviewer_catalog.forget_cached()
    ref = await rv.seed_reference_shop(session, title=TITLES[0], product_id="1729000000000000001")
    for index, title in enumerate(TITLES[1:], start=2):
        session.add(
            Product(
                id=uuid.uuid4(),
                shop_id=ref.shop.id,
                tiktok_product_id=f"172900000000000000{index}",
                title=title,
                name=title,
                status="ACTIVATE",
                update_time=rv.naive_now(),
            )
        )
    await session.commit()
    dictionary = await reviewer_catalog.load_dictionary(session, ref.shop)
    assert TITLE_BRAND in dictionary.catalog_brands
    assert "Nồi" not in dictionary.catalog_brands
    reviewer_catalog.forget_cached()


async def test_reviewer_is_scrubbed_and_the_seller_is_not(session, monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    rv.reset_caches()
    ref = await rv.seed_reference_shop(session, title=TITLES[0], product_id="1729000000000000001")
    for index, title in enumerate(TITLES[1:], start=2):
        session.add(
            Product(
                id=uuid.uuid4(),
                shop_id=ref.shop.id,
                tiktok_product_id=f"172900000000000000{index}",
                title=title,
                name=title,
                status="ACTIVATE",
                update_time=rv.naive_now(),
            )
        )
    ref.card.description = "Khách tìm lumiora nhiều hơn tuần trước, <b>LUMIORA</b> tăng"
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(ref.shop.id))
    user_id = await rv.make_reviewer(session)
    reviewer_headers = {
        "Authorization": f"Bearer {rv.token(user_id)}",
        "X-Shop-Id": str(shop_alias_id(ref.shop.id)),
    }
    seller_headers = {
        "Authorization": f"Bearer {rv.token(ref.owner.id, platform=None)}",
        "X-Shop-Id": str(ref.shop.id),
    }
    try:
        async with client_for(build_app(session)) as client:
            masked = await client.get("/v1/demo/decisions", headers=reviewer_headers)
            own = await client.get("/v1/demo/decisions", headers=seller_headers)
    finally:
        rv.reset_caches()
    assert masked.status_code == 200 and own.status_code == 200, (masked.text, own.text)
    assert "umiora" not in masked.text.lower()
    assert "umiora" in own.text.lower()
