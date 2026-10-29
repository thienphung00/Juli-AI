"""P69: the deterministic filter on the model's new-listing title / description."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm.blocks import ToolCallBlock
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.agent.tools.catalog_create import (
    CreateProductInput,
    precheck_create_product,
)
from juli_backend.services.agent.tools.listing_text_filter import (
    DESCRIPTION_MAX_CHARS,
    DESCRIPTION_MIN_CHARS,
    ERROR_LISTING_TEXT_REJECTED,
    FILTERED_DESCRIPTION_MIN_CHARS,
    REASON_DUPLICATE,
    REASON_FILLER,
    REASON_META,
    ListingTextRejected,
    clean_listing_draft,
    normalize_create_product,
    screen_listing_draft,
)
from juli_backend.services.shop_rules.listing_edits import TITLE_MAX_CHARS, TITLE_MIN_CHARS
from tests.unit.test_p64_create_product_walkthrough import (
    MANUFACTURER_ATTRS,
    SOURCE_ID,
    BrandedProducts,
    InMemoryStore,
    ScriptedLLM,
    _runner,
)
from tests.unit.test_reviewer_sandbox_create_product import CONTEXT, FakeProducts, _sandbox

TITLE = "Bình nước thép không gỉ 750ml nắp xoay chống tràn"
GENERIC = (
    "Bình nước thép không gỉ 750ml phù hợp cho nhu cầu sử dụng hằng ngày. "
    "Thiết kế chắc chắn, tiện mang theo khi đi học, đi làm hoặc hoạt động năng động. "
    "Dung tích 750ml giúp đáp ứng lượng nước cần thiết trong ngày."
)
GOOD = (
    "Bình giữ nhiệt inox 304 dung tích 750ml, thân hai lớp giữ nóng khoảng 12 giờ, nắp xoay "
    "chống tràn.\n\n"
    "Trong hộp có 1 bình và 1 dây đeo. Thân bình dày 0,5 mm, có thể rửa bằng nước ấm."
)


def test_the_generic_description_is_rejected_for_one_redraft_not_shipped() -> None:
    # filtered down to its two facts ("... 750ml. Dung tích 750ml.", 47 chars): too thin
    with pytest.raises(ListingTextRejected) as caught:
        clean_listing_draft(TITLE, GENERIC)
    assert len(caught.value.dropped) == 3
    assert {d.reason for d in caught.value.dropped} == {REASON_FILLER}
    hint = screen_listing_draft(TITLE, GENERIC)
    assert hint is not None and ERROR_LISTING_TEXT_REJECTED in hint
    assert (
        normalize_create_product(
            CreateProductInput(category_id="1", title=TITLE, description=GENERIC, reason_vi="Bình")
        )
        is None
    )
    # at the write guard the lower tool-input floor applies, the facts are what is kept
    kept = clean_listing_draft(TITLE, GENERIC, description_floor=DESCRIPTION_MIN_CHARS)
    assert kept.description == "Bình nước thép không gỉ 750ml. Dung tích 750ml."
    pure = "Thiết kế chắc chắn, tiện mang theo khi đi học, đi làm hoặc hoạt động năng động."
    with pytest.raises(ListingTextRejected):
        clean_listing_draft(TITLE, pure)


def test_a_filtered_result_under_the_floor_is_refused_and_at_the_floor_passes() -> None:
    assert FILTERED_DESCRIPTION_MIN_CHARS == 120
    stock = "Thân bình inox 304 dày 0,5 mm, dung tích 750ml, nắp xoay chống tràn, kèm dây đeo" + (
        ", trong hộp có 1 bình và 1 dây đeo" * 5
    )

    def of_length(n: int) -> str:
        text = stock[: n - 1].rstrip(" ,") + "."
        assert len(text) == n
        return text

    under, exact = of_length(119), of_length(120)
    assert screen_listing_draft(TITLE, under) is not None
    with pytest.raises(ListingTextRejected):
        clean_listing_draft(TITLE, under)
    assert screen_listing_draft(TITLE, exact) is None
    assert clean_listing_draft(TITLE, exact).description == exact


def test_a_filler_phrase_inside_a_sentence_with_real_content_is_kept_whole() -> None:
    keep = (
        "Bình giữ nhiệt inox 304 dung tích 750ml, giữ nóng 12 giờ, phù hợp cho nhu cầu "
        "sử dụng hằng ngày của gia đình và văn phòng. Trong hộp có 1 bình và 1 dây đeo."
    )
    cleaned = clean_listing_draft(TITLE, keep)
    assert cleaned.description == keep and cleaned.dropped == ()


def test_the_filter_is_idempotent() -> None:
    for description in (
        GOOD,
        GOOD + "\nJuli kiểm tra độ dài và từ cấm.",
        GOOD + " " + GOOD.split("\n")[0],
        GENERIC + " " + GOOD,
    ):
        once = clean_listing_draft(TITLE, description)
        twice = clean_listing_draft(once.title, once.description)
        assert (twice.title, twice.description) == (once.title, once.description)
        assert twice.dropped == ()


def test_meta_text_about_juli_and_rules_is_stripped() -> None:
    dirty = GOOD + "\nJuli kiểm tra độ dài và từ cấm theo quy tắc của bạn trước khi cho lưu."
    cleaned = clean_listing_draft(TITLE, dirty)
    assert "Juli" not in cleaned.description and "quy tắc" not in cleaned.description
    assert [d.reason for d in cleaned.dropped] == [REASON_META]
    assert cleaned.description.startswith("Bình giữ nhiệt inox 304")
    # the remaining text still meets the minimums: replaced, never refused
    assert screen_listing_draft(TITLE, dirty) is None
    normalized = normalize_create_product(
        CreateProductInput(category_id="1", title=TITLE, description=dirty, reason_vi="Bình")
    )
    assert normalized is not None and normalized.description == cleaned.description


def test_a_meta_preamble_and_ai_talk_are_dropped_but_the_word_ai_alone_is_not_meta() -> None:
    dirty = "Dưới đây là mô tả sản phẩm. " + GOOD + " Mô tả do AI viết."
    assert {d.reason for d in clean_listing_draft(TITLE, dirty).dropped} == {REASON_META}
    kept = clean_listing_draft(TITLE, "Ai dùng bình này cũng thấy nhẹ. " + GOOD)
    assert kept.dropped == ()


def test_repeated_sentences_are_dropped_accent_and_case_insensitive() -> None:
    dirty = "Thân bình inox 304 dung tích 750ml. Thân bình INOX 304 dung tích 750ml! " + GOOD
    cleaned = clean_listing_draft(TITLE, dirty)
    assert [d.reason for d in cleaned.dropped] == [REASON_DUPLICATE]
    assert cleaned.description.startswith("Thân bình inox 304 dung tích 750ml. Bình giữ nhiệt")


def test_whitespace_markup_and_emoji_are_tidied_silently() -> None:
    cleaned = clean_listing_draft(
        '  "Bình   nước thép không gỉ  750ml nắp xoay chống tràn."  ',
        "**Thân bình** inox 304   dung tích 750ml 🔥.\n\n\n<p>"
        + GOOD.replace("\n\n", "\n")
        + "</p>",
    )
    assert cleaned.title == "Bình nước thép không gỉ 750ml nắp xoay chống tràn"
    assert cleaned.description.startswith("Thân bình inox 304 dung tích 750ml .\nBình giữ nhiệt")
    assert "<" not in cleaned.description and "🔥" not in cleaned.description
    assert cleaned.dropped == ()
    assert (
        screen_listing_draft("  Bình   nước thép không gỉ 750ml nắp xoay chống tràn ", GOOD) is None
    )


def test_title_bounds_follow_the_tiktok_limits_in_the_code() -> None:
    with pytest.raises(ListingTextRejected):
        clean_listing_draft("Bình nước 750ml", GOOD)
    assert TITLE_MIN_CHARS == 40  # D78.1
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


def test_the_precheck_refuses_only_a_draft_with_nothing_left() -> None:
    products = FakeProducts()
    bad = CreateProductInput(
        category_id="1",
        title=TITLE,
        description=(
            "Thiết kế chắc chắn, tiện mang theo khi đi học, đi làm hoặc hoạt động năng động."
        ),
        reason_vi="Bình",
    )
    refusal = precheck_create_product(_sandbox(products), CONTEXT, bad)
    assert refusal is not None and refusal.error_code == ERROR_LISTING_TEXT_REJECTED
    good = CreateProductInput(category_id="1", title=TITLE, description=GOOD, reason_vi="Bình")
    assert precheck_create_product(_sandbox(products), CONTEXT, good) is None


# -- the runner: the seller confirms the filtered text; refusals are capped ----------------


class _DescribingLLM(ScriptedLLM):
    def __init__(self, descriptions: list[str]) -> None:
        super().__init__([TITLE] * len(descriptions))
        self.descriptions = list(descriptions)

    async def complete(self, **kwargs: Any):
        turn = await super().complete(**kwargs)
        for block in turn.blocks:
            if isinstance(block, ToolCallBlock):
                block.arguments["description"] = self.descriptions.pop(0)
        return turn


async def test_the_reviewer_is_shown_the_filtered_text_with_no_redraft() -> None:
    products, store, sink = (
        BrandedProducts(attributes=MANUFACTURER_ATTRS[:1]),
        InMemoryStore(),
        InMemoryEventSink(),
    )
    dirty = GOOD + "\nJuli kiểm tra độ dài và từ cấm theo quy tắc của bạn."
    run_id = uuid.uuid4()
    paused = await _runner(products, store, sink, _DescribingLLM([dirty])).run(
        run_id, product_ref=SOURCE_ID
    )
    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL
    arguments = store.states[run_id].pending_confirmation["arguments"]
    assert arguments["description"] == clean_listing_draft(TITLE, dirty).description
    assert "Juli" not in str(arguments)
    approval = [e.payload for e in sink.events if e.event_type == "workflow.approval_required"]
    assert approval and "Juli kiểm tra" not in str(approval)
    assert not [e for e in sink.events if e.event_type == "tool.completed"]  # no refusal round
    assert products.created == []


async def test_two_empty_drafts_in_a_row_end_the_run_instead_of_looping() -> None:
    products, store, sink = (
        BrandedProducts(attributes=MANUFACTURER_ATTRS[:1]),
        InMemoryStore(),
        InMemoryEventSink(),
    )
    filler = "Thiết kế chắc chắn, tiện mang theo khi đi học, đi làm hoặc hoạt động năng động."
    result = await _runner(products, store, sink, _DescribingLLM([filler, filler, filler])).run(
        uuid.uuid4(), product_ref=SOURCE_ID
    )
    assert result.status != WorkflowRunStatus.WAITING_APPROVAL
    assert not [e for e in sink.events if e.event_type == "workflow.approval_required"]
    assert len([e for e in sink.events if e.event_type == "tool.completed"]) == 2  # one redraft
    assert [e for e in sink.events if e.event_type == "workflow.failed"]
    assert products.created == []
