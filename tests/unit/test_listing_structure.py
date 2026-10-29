"""Description skeleton and edit operations (fast track P76-3, D78).

Property-style checks over synthetic fixtures (``tests/support/listing_descriptions``):
the skeleton round-trips, keeps text and order, and rendering is stable. Table-driven
checks for every rejection code, and for determinism / idempotence.
"""

from __future__ import annotations

import html
import re

import pytest

from juli_backend.services.shop_rules.listing_edits import DESCRIPTION_MAX_CHARS, TITLE_MAX_CHARS
from juli_backend.services.shop_rules.listing_structure import (
    AppendSection,
    EditRejection,
    EditResult,
    InsertAfter,
    ListingEditOps,
    RejectionCode,
    ReplaceSpan,
    ReplaceTitleSpan,
    SectionKind,
    apply_ops,
    parse_description,
    render_description,
    section_text,
)
from tests.support.listing_descriptions import DESCRIPTIONS

TITLE = "Bình giữ nhiệt inox 500ml"
DESC = DESCRIPTIONS["headings_and_bullets"]
DESC_CODE = "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"
TITLE_CODE = "TITLE_LESS_THAN_40_CHARACTERS"


def _words(text: str) -> list[str]:
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).split()


def _skeleton_words(html_text: str) -> list[str]:
    words: list[str] = []
    for section in parse_description(html_text):
        if section.kind is not SectionKind.RAW:
            words.extend(section_text(section).split())
    return words


def _ops(title=(), desc=()) -> ListingEditOps:
    return ListingEditOps(title_ops=list(title), description_ops=list(desc))


def _replace(index, old, new, code=DESC_CODE) -> ReplaceSpan:
    return ReplaceSpan(op="replace_span", section_index=index, old=old, new=new, reason_code=code)


@pytest.mark.parametrize("name", DESCRIPTIONS)
class TestSkeletonProperties:
    def test_round_trip_keeps_sections(self, name):
        skeleton = parse_description(DESCRIPTIONS[name])

        assert parse_description(render_description(skeleton)) == skeleton

    def test_render_is_stable(self, name):
        once = render_description(parse_description(DESCRIPTIONS[name]))

        assert render_description(parse_description(once)) == once

    def test_text_and_order_are_preserved(self, name):
        assert _skeleton_words(DESCRIPTIONS[name]) == _words(DESCRIPTIONS[name])


class TestParse:
    def test_headings_lists_and_paragraphs_in_order(self):
        kinds = [s.kind for s in parse_description(DESCRIPTIONS["headings_and_bullets"])]

        assert kinds == [
            SectionKind.HEADING,
            SectionKind.PARAGRAPH,
            SectionKind.HEADING,
            SectionKind.LIST,
            SectionKind.HEADING,
            SectionKind.PARAGRAPH,
        ]

    def test_plain_text_splits_on_blank_lines_and_keeps_line_breaks(self):
        sections = parse_description(DESCRIPTIONS["plain_text_emoji"])

        assert [len(s.lines) for s in sections] == [3, 1, 1]

    def test_double_br_starts_a_new_paragraph(self):
        sections = parse_description(DESCRIPTIONS["br_only"])

        assert [s.lines for s in sections] == [
            ("Áo thun cotton mềm mịn", "Size M, L, XL"),
            ("Chất vải co giãn 4 chiều", "Giặt máy thoải mái"),
            ("Giao nhanh 2 ngày",),
        ]

    def test_nested_list_keeps_depth_and_ordering(self):
        lists = [s for s in parse_description(DESCRIPTIONS["nested_lists"]) if s.items]

        assert [(i.text, i.depth, i.ordered) for i in lists[0].items] == [
            ("Kích thước", 0, False),
            ("Dài 20cm", 1, False),
            ("Rộng 10cm", 1, False),
            ("Chất liệu", 0, False),
            ("Nhựa ABS", 1, True),
            ("Silicone", 1, True),
        ]
        assert lists[1].items[0].ordered is True

    def test_bold_only_line_is_a_heading_even_inside_a_br_chunk(self):
        sections = parse_description(DESCRIPTIONS["bold_headings"])

        assert [(s.kind, s.heading_style) for s in sections[:3]] == [
            (SectionKind.HEADING, "bold"),
            (SectionKind.PARAGRAPH, None),
            (SectionKind.HEADING, "bold"),
        ]
        assert sections[3].lines == ("Thoa đều lên da mặt.", "Rửa lại bằng nước sạch.")

    def test_image_is_kept_verbatim_as_raw(self):
        raw = [
            s for s in parse_description(DESCRIPTIONS["with_image"]) if s.kind is SectionKind.RAW
        ]

        assert [s.lines[0] for s in raw] == [
            '<img src="https://example.invalid/a.jpg" width="400">'
        ]

    @pytest.mark.parametrize("name", ["empty", "whitespace_only"])
    def test_empty_description_has_no_sections(self, name):
        assert parse_description(DESCRIPTIONS[name]) == ()
        assert render_description(()) == ""

    def test_render_writes_the_html_juli_writes_today(self):
        rendered = render_description(parse_description(DESCRIPTIONS["bold_headings"]))

        assert rendered.startswith(
            "<p><strong>Công dụng</strong></p><p>Làm sạch sâu, dưỡng ẩm.</p>"
        )
        assert "<p>Thoa đều lên da mặt.<br>Rửa lại bằng nước sạch.</p>" in rendered

    def test_special_characters_are_escaped_on_render(self):
        assert (
            render_description(parse_description("<p>A &amp; B &lt; C</p>"))
            == "<p>A &amp; B &lt; C</p>"
        )


class TestApplyOps:
    def test_untouched_text_stays_word_for_word(self):
        ops = _ops(desc=[_replace(1, "giữ nóng 12 giờ", "giữ nóng 12 tiếng")])

        result = apply_ops(TITLE, DESC, ops, [])

        assert isinstance(result, EditResult)
        before, after = parse_description(DESC), result.skeleton
        assert [s for i, s in enumerate(after) if i != 1] == [
            s for i, s in enumerate(before) if i != 1
        ]
        assert "giữ nóng 12 tiếng" in section_text(after[1])
        assert section_text(after[1]).endswith("giữ lạnh 24 giờ.")

    def test_no_description_ops_returns_the_original_html_verbatim(self):
        messy = DESCRIPTIONS["messy_html"]

        result = apply_ops(TITLE, messy, _ops(), [])

        assert isinstance(result, EditResult)
        assert result.description_html == messy
        assert result.changed is False

    def test_title_span_is_replaced(self):
        ops = _ops(
            title=[
                ReplaceTitleSpan(
                    op="replace_title_span",
                    old="inox 500ml",
                    new="inox 304 500ml chính hãng",
                    reason_code=TITLE_CODE,
                )
            ]
        )

        result = apply_ops(TITLE, DESC, ops, [])

        assert isinstance(result, EditResult)
        assert result.title == "Bình giữ nhiệt inox 304 500ml chính hãng"
        assert result.changed is True

    def test_insert_after_adds_a_paragraph_after_the_section(self):
        ops = _ops(
            desc=[
                InsertAfter(
                    op="insert_after",
                    section_index=1,
                    text="Dùng được cho cả cà phê.",
                    reason_code=DESC_CODE,
                )
            ]
        )

        result = apply_ops(TITLE, DESC, ops, [])

        assert isinstance(result, EditResult)
        assert section_text(result.skeleton[2]) == "Dùng được cho cả cà phê."
        assert len(result.skeleton) == len(parse_description(DESC)) + 1

    def test_append_section_with_flagged_code_matches_last_heading_style(self):
        ops = _ops(
            desc=[
                AppendSection(
                    op="append_section",
                    heading="Hướng dẫn bảo quản",
                    body="Rửa sạch.\n\nPhơi khô.",
                    reason_code=DESC_CODE,
                )
            ]
        )

        result = apply_ops(TITLE, DESC, ops, [DESC_CODE])

        assert isinstance(result, EditResult)
        tail = result.skeleton[-3:]
        assert [s.kind for s in tail] == [
            SectionKind.HEADING,
            SectionKind.PARAGRAPH,
            SectionKind.PARAGRAPH,
        ]
        assert tail[0].heading_style == "bold"
        assert result.skeleton[:-3] == parse_description(DESC)

    def test_list_items_keep_depth_when_an_item_is_edited(self):
        nested = DESCRIPTIONS["nested_lists"]
        result = apply_ops(TITLE, nested, _ops(desc=[_replace(1, "Dài 20cm", "Dài 25cm")]), [])

        assert isinstance(result, EditResult)
        assert [(i.text, i.depth) for i in result.skeleton[1].items][:2] == [
            ("Kích thước", 0),
            ("Dài 25cm", 1),
        ]

    def test_deterministic_and_stable(self):
        ops = _ops(desc=[_replace(0, "sản phẩm", "sản phẩm này")])

        first = apply_ops(TITLE, DESC, ops, [DESC_CODE])
        second = apply_ops(TITLE, DESC, ops, [DESC_CODE])

        assert first == second
        assert isinstance(first, EditResult)
        assert (
            render_description(parse_description(first.description_html)) == first.description_html
        )

    def test_applying_to_the_result_changes_nothing_more_when_old_is_gone(self):
        ops = _ops(desc=[_replace(0, "Giới thiệu", "Giới thiệu chi tiết")])
        first = apply_ops(TITLE, DESC, ops, [])
        assert isinstance(first, EditResult)

        again = apply_ops(first.title, first.description_html, _ops(), [])

        assert isinstance(again, EditResult)
        assert again.description_html == first.description_html
        assert again.changed is False


def _title_op(old, new="x", code=TITLE_CODE):
    return ReplaceTitleSpan(op="replace_title_span", old=old, new=new, reason_code=code)


REJECTIONS = [
    pytest.param(
        TITLE,
        DESC,
        _ops(title=[_title_op("không có")]),
        [],
        RejectionCode.OLD_NOT_FOUND,
        "title",
        id="title-old-missing",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(title=[_title_op("")]),
        [],
        RejectionCode.OLD_EMPTY,
        "title",
        id="title-old-empty",
    ),
    pytest.param(
        "Áo thun thun",
        DESC,
        _ops(title=[_title_op("thun")]),
        [],
        RejectionCode.OLD_AMBIGUOUS,
        "title",
        id="title-ambiguous",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(title=[_title_op("Bình giữ", "A"), _title_op("giữ nhiệt", "B")]),
        [],
        RejectionCode.OPS_OVERLAP,
        "title",
        id="title-overlap",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(title=[_title_op("Bình", "B", DESC_CODE)]),
        [],
        RejectionCode.REASON_CODE_WRONG_FIELD,
        "title",
        id="title-wrong-code",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(title=[_title_op(TITLE, " ")]),
        [],
        RejectionCode.TITLE_EMPTIED,
        "title",
        id="title-emptied",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(title=[_title_op("Bình", "B" * 300)]),
        [],
        RejectionCode.RESULT_OVER_LIMITS,
        "title",
        id="title-too-long",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(1, "không có trong mô tả", "x")]),
        [],
        RejectionCode.OLD_NOT_FOUND,
        "description",
        id="desc-old-missing",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(1, "", "x")]),
        [],
        RejectionCode.OLD_EMPTY,
        "description",
        id="desc-old-empty",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(0, "i", "x")]),
        [],
        RejectionCode.OLD_AMBIGUOUS,
        "description",
        id="desc-ambiguous",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(99, "x", "y")]),
        [],
        RejectionCode.SECTION_INDEX_OUT_OF_RANGE,
        "description",
        id="index-high",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(-1, "x", "y")]),
        [],
        RejectionCode.SECTION_INDEX_OUT_OF_RANGE,
        "description",
        id="index-negative",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(
            desc=[InsertAfter(op="insert_after", section_index=6, text="x", reason_code=DESC_CODE)]
        ),
        [],
        RejectionCode.SECTION_INDEX_OUT_OF_RANGE,
        "description",
        id="insert-index",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(1, "Bình", "B", "TITLE_LESS_THAN_40_CHARACTERS")]),
        [],
        RejectionCode.REASON_CODE_WRONG_FIELD,
        "description",
        id="desc-wrong-code",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(
            desc=[AppendSection(op="append_section", heading="H", body="B", reason_code=DESC_CODE)]
        ),
        ["DESC_NO_NEW_LINE"],
        RejectionCode.APPEND_CODE_NOT_FLAGGED,
        "description",
        id="append-not-flagged",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(
            desc=[AppendSection(op="append_section", heading=" ", body="B", reason_code=DESC_CODE)]
        ),
        [DESC_CODE],
        RejectionCode.INSERT_TEXT_INVALID,
        "description",
        id="append-empty-heading",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(
            desc=[
                InsertAfter(
                    op="insert_after", section_index=1, text="a\n\nb", reason_code=DESC_CODE
                )
            ]
        ),
        [],
        RejectionCode.INSERT_TEXT_INVALID,
        "description",
        id="insert-two-paragraphs",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(
            desc=[
                _replace(1, "Bình giữ nhiệt dung tích 500ml, giữ nóng 12 giờ, giữ lạnh 24 giờ.", "")
            ]
        ),
        [],
        RejectionCode.SECTION_STRUCTURE_CHANGED,
        "description",
        id="section-emptied",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(0, "Giới thiệu sản phẩm", "A\nB")]),
        [],
        RejectionCode.SECTION_STRUCTURE_CHANGED,
        "description",
        id="heading-split",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(3, "Nắp kín chống rò rỉ\nDễ", "Nắp kín Dễ")]),
        [],
        RejectionCode.SECTION_DROPPED,
        "description",
        id="list-items-merged",
    ),
    pytest.param(
        TITLE,
        DESC,
        _ops(desc=[_replace(3, "Thép", "A"), _replace(3, "Thép không", "B")]),
        [],
        RejectionCode.OPS_OVERLAP,
        "description",
        id="desc-overlap",
    ),
    pytest.param(
        TITLE,
        DESCRIPTIONS["with_image"],
        _ops(desc=[_replace(1, "img", "x")]),
        [],
        RejectionCode.SECTION_NOT_EDITABLE,
        "description",
        id="raw-not-editable",
    ),
    pytest.param(
        TITLE,
        "<p>" + "a" * DESCRIPTION_MAX_CHARS + "</p>",
        _ops(),
        [],
        RejectionCode.LISTING_OVER_LIMITS,
        "description",
        id="listing-over-description",
    ),
    pytest.param(
        "t" * (TITLE_MAX_CHARS + 1),
        DESC,
        _ops(),
        [],
        RejectionCode.LISTING_OVER_LIMITS,
        "title",
        id="listing-over-title",
    ),
    pytest.param(
        TITLE,
        "<p>X" + "a" * (DESCRIPTION_MAX_CHARS - 30) + "</p>",
        _ops(desc=[_replace(0, "X", "b" * 100)]),
        [],
        RejectionCode.RESULT_OVER_LIMITS,
        "description",
        id="result-over-description",
    ),
]


@pytest.mark.parametrize(("title", "description", "ops", "flagged", "code", "field"), REJECTIONS)
def test_rejections(title, description, ops, flagged, code, field):
    result = apply_ops(title, description, ops, flagged)

    assert isinstance(result, EditRejection)
    assert (result.code, result.field) == (code, field)
    assert result.message.isascii()


def test_rejection_names_the_failing_op_index():
    ops = _ops(desc=[_replace(1, "giữ nóng", "giữ ấm"), _replace(1, "không có", "x")])

    result = apply_ops(TITLE, DESC, ops, [])

    assert isinstance(result, EditRejection)
    assert result.op_index == 1


def test_ops_schema_is_strict_friendly():
    schema = ListingEditOps.model_json_schema()
    defs = schema["$defs"]

    assert schema["additionalProperties"] is False
    for name, definition in defs.items():
        assert definition["additionalProperties"] is False, name
        assert set(definition["required"]) == set(definition["properties"]), name
