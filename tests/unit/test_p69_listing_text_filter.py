"""P69: the deterministic filter on the model's new-listing title / description."""

from __future__ import annotations

import pytest

from juli_backend.services.agent.tools.catalog_create import (
    CreateProductInput,
    precheck_create_product,
)
from juli_backend.services.agent.tools.listing_text_filter import (
    DESCRIPTION_MAX_CHARS,
    ERROR_LISTING_TEXT_REJECTED,
    REASON_DUPLICATE,
    REASON_FILLER,
    REASON_META,
    ListingTextRejected,
    clean_listing_draft,
    screen_listing_draft,
)
from juli_backend.services.shop_rules.listing_edits import TITLE_MAX_CHARS, TITLE_MIN_CHARS
from tests.unit.test_reviewer_sandbox_create_product import CONTEXT, FakeProducts, _sandbox

TITLE = "Bình nước thép không gỉ 750ml nắp xoay chống tràn"
GENERIC = (
    "Bình nước thép không gỉ 750ml phù hợp cho nhu cầu sử dụng hằng ngày. "
    "Thiết kế chắc chắn, tiện mang theo khi đi học, đi làm hoặc hoạt động năng động. "
    "Dung tích 750ml giúp đáp ứng lượng nước cần thiết trong ngày."
)
GOOD = (
    "Bình giữ nhiệt inox 304 dung tích 750ml, nắp xoay chống tràn.\n\n"
    "Trong hộp có 1 bình và 1 dây đeo. Giữ nóng khoảng 12 giờ theo thông tin của sản phẩm gốc."
)


def test_the_generic_description_is_rejected_not_shipped() -> None:
    with pytest.raises(ListingTextRejected) as caught:
        clean_listing_draft(TITLE, GENERIC)
    assert {d.reason for d in caught.value.dropped} == {REASON_FILLER}
    assert len(caught.value.dropped) == 3
    hint = screen_listing_draft(TITLE, GENERIC)
    assert hint is not None and ERROR_LISTING_TEXT_REJECTED in hint


def test_meta_text_about_juli_and_rules_is_stripped() -> None:
    dirty = GOOD + "\nJuli kiểm tra độ dài và từ cấm theo quy tắc của bạn trước khi cho lưu."
    cleaned = clean_listing_draft(TITLE, dirty)
    assert "Juli" not in cleaned.description and "quy tắc" not in cleaned.description
    assert [d.reason for d in cleaned.dropped] == [REASON_META]
    assert cleaned.description.startswith("Bình giữ nhiệt inox 304")
    # a stripped sentence is not silent: the model is sent back to write it again
    assert screen_listing_draft(TITLE, dirty) is not None


def test_a_meta_preamble_and_ai_talk_are_dropped_but_the_word_ai_alone_is_not_meta() -> None:
    dirty = "Dưới đây là mô tả sản phẩm. " + GOOD + " Mô tả do AI viết."
    assert {d.reason for d in clean_listing_draft(TITLE, dirty).dropped} == {REASON_META}
    kept = clean_listing_draft(TITLE, "Ai dùng bình này cũng thấy nhẹ, thân inox 304 dày 0,5 mm.")
    assert kept.dropped == ()


def test_repeated_sentences_are_dropped_accent_and_case_insensitive() -> None:
    dirty = (
        "Thân bình inox 304 dung tích 750ml. Thân bình INOX 304 dung tích 750ml! "
        "Nắp xoay chống tràn."
    )
    cleaned = clean_listing_draft(TITLE, dirty)
    assert [d.reason for d in cleaned.dropped] == [REASON_DUPLICATE]
    assert cleaned.description.count("750ml") == 1


def test_whitespace_markup_and_emoji_are_tidied_silently() -> None:
    cleaned = clean_listing_draft(
        '  "Bình   nước thép không gỉ  750ml nắp xoay chống tràn."  ',
        "**Thân bình** inox 304   dung tích 750ml 🔥.\n\n\n<p>Nắp xoay chống tràn.</p>",
    )
    assert cleaned.title == "Bình nước thép không gỉ 750ml nắp xoay chống tràn"
    assert cleaned.description == "Thân bình inox 304 dung tích 750ml .\nNắp xoay chống tràn."
    assert cleaned.dropped == ()
    assert (
        screen_listing_draft("  Bình   nước thép không gỉ 750ml nắp xoay chống tràn ", GOOD) is None
    )


def test_title_bounds_follow_the_tiktok_limits_in_the_code() -> None:
    with pytest.raises(ListingTextRejected):
        clean_listing_draft("Bình nước 750ml", GOOD)
    assert TITLE_MIN_CHARS == 25
    long_title = ("Bình giữ nhiệt inox " * 20).strip()
    assert len(long_title) > TITLE_MAX_CHARS
    cleaned = clean_listing_draft(long_title, GOOD)
    assert TITLE_MIN_CHARS <= len(cleaned.title) <= TITLE_MAX_CHARS
    assert cleaned.truncated and not cleaned.title.endswith(" ")


def test_description_is_capped_and_empty_or_meta_only_is_rejected() -> None:
    sentence = "Thân bình inox 304 dung tích 750ml, số %d. "
    huge = "".join(sentence % i for i in range(400))
    assert len(huge) > DESCRIPTION_MAX_CHARS
    cleaned = clean_listing_draft(TITLE, huge)
    assert len(cleaned.description) <= DESCRIPTION_MAX_CHARS and cleaned.truncated
    for empty in ("", "   \n ", "Juli soạn mô tả này theo quy tắc của shop."):
        with pytest.raises(ListingTextRejected):
            clean_listing_draft(TITLE, empty)
    with pytest.raises(ListingTextRejected):
        clean_listing_draft("Juli viết tiêu đề này cho sản phẩm bình nước", GOOD)


def test_the_precheck_refuses_a_generic_draft_and_passes_a_specific_one() -> None:
    products = FakeProducts()
    bad = CreateProductInput(category_id="1", title=TITLE, description=GENERIC, reason_vi="Bình")
    refusal = precheck_create_product(_sandbox(products), CONTEXT, bad)
    assert refusal is not None and refusal.error_code == ERROR_LISTING_TEXT_REJECTED
    good = CreateProductInput(category_id="1", title=TITLE, description=GOOD, reason_vi="Bình")
    assert precheck_create_product(_sandbox(products), CONTEXT, good) is None
