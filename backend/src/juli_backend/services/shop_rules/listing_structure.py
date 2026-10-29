"""Description skeleton and edit operations for a listing (fast track P76-3, D78).

Juli's Optimize Product run used to let the model write a whole new title and
description, which came back shorter than the seller's and lost their structure
and voice. This module is the deterministic half of the replacement: the model
returns *edit operations*, Juli applies them to the original text, and every
character the operations do not touch stays word for word. No model call, no
I/O; the runner and prompt are wired to it in later steps.

Skeleton
--------
:func:`parse_description` reads the seller's HTML (or plain text) into an ordered
tuple of :class:`Section`: ``heading`` (``<h1>``-``<h6>`` or a bold-only line),
``list`` (``<ul>``/``<ol>``, nested items carry a depth), ``paragraph`` (one or
more lines; ``<br>`` and newlines separate lines, a blank line separates
paragraphs) and ``raw`` (``<img>`` kept verbatim, never edited).
:func:`render_description` writes it back as the HTML Juli writes today: ``<p>``
with ``<br>``, ``<ul>/<ol>``, ``<hN>`` or ``<p><strong>``.

Normalisation (the round-trip is lossless for section text and order, not for
markup): every line has its whitespace runs collapsed to one space and is
stripped; inline tags other than ``<br>`` (``<b>``, ``<i>``, ``<span>``, ...) are
dropped, with a bold-only line becoming a ``bold`` heading; entities are
unescaped on parse and escaped on render; a double ``<br>`` or a blank line
starts a new paragraph. ``render(parse(render(parse(x)))) == render(parse(x))``.

Operations
----------
:class:`ListingEditOps` is the strict-schema model the LLM fills in (every field
required, ``extra="forbid"``). :func:`apply_ops` returns an :class:`EditResult`
or an :class:`EditRejection` carrying a machine-readable :class:`RejectionCode`
and an English message for the model's retry. Section indices always refer to the
*original* skeleton, so op order never shifts them. Rules (D78): a span is
replaced only when ``old`` occurs exactly once in its section; no section is
dropped, merged or split; a section is appended only to fix a TikTok-flagged
code present on the product; a listing already over TikTok's limits is refused.
Pure and deterministic. With no description ops the original HTML is returned
unchanged.
"""

from __future__ import annotations

import html
import re
from collections.abc import Collection
from dataclasses import dataclass, replace
from enum import Enum
from html.parser import HTMLParser
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from juli_backend.services.optimize_product.listing_signals import (
    is_description_code,
    is_title_code,
)
from juli_backend.services.shop_rules.listing_edits import (
    DESCRIPTION_MAX_CHARS,
    TITLE_MAX_CHARS,
)

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "blockquote", "pre", "center", "hr",
        "table", "thead", "tbody", "tr", "td", "th",
    }
)  # fmt: skip
_BOLD_TAGS = frozenset({"b", "strong"})
_MARKUP_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_SPACE_RE = re.compile(r"\s+")
_BOLD_HEADING = "bold"


class SectionKind(str, Enum):
    HEADING = "heading"
    LIST = "list"
    PARAGRAPH = "paragraph"
    RAW = "raw"


@dataclass(frozen=True)
class ListItem:
    text: str
    depth: int
    ordered: bool


@dataclass(frozen=True)
class Section:
    """One block of the description.

    ``lines`` holds the text of a heading (one line) or paragraph, or the verbatim
    tag of a raw section (one entry); ``items`` the list items. ``heading_style``
    is ``h1``..``h6`` or ``bold`` for headings.
    """

    kind: SectionKind
    lines: tuple[str, ...] = ()
    items: tuple[ListItem, ...] = ()
    heading_style: str | None = None


DescriptionSkeleton = tuple[Section, ...]


def section_text(section: Section) -> str:
    """The text a replace op addresses: lines (or list items) joined by newline."""
    if section.kind is SectionKind.LIST:
        return "\n".join(item.text for item in section.items)
    return "\n".join(section.lines)


def _collapse(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()


# --------------------------------------------------------------------------- parse


_Line = tuple[str, bool]  # (collapsed text, every non-blank piece was bold)


def _sections_from_lines(lines: list[_Line], *, forced_heading: str | None = None) -> list[Section]:
    """Group lines into sections: blank line = paragraph break, bold-only line = heading."""
    if forced_heading is not None:
        text = _collapse(" ".join(t for t, _ in lines))
        return [Section(SectionKind.HEADING, (text,), heading_style=forced_heading)] if text else []
    out: list[Section] = []
    para: list[str] = []

    def close_para() -> None:
        if para:
            out.append(Section(SectionKind.PARAGRAPH, tuple(para)))
            para.clear()

    for text, all_bold in lines:
        if not text:
            close_para()
        elif all_bold:
            close_para()
            out.append(Section(SectionKind.HEADING, (text,), heading_style=_BOLD_HEADING))
        else:
            para.append(text)
    close_para()
    return out


class _SkeletonBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[Section] = []
        self._lines: list[_Line] = []
        self._cur: list[tuple[str, bool]] = []
        self._bold = 0
        self._heading: str | None = None
        self._list_stack: list[bool] = []
        self._items: list[ListItem] = []
        self._item: list[str] | None = None
        self._item_meta = (0, False)
        self._pending_raw: list[Section] = []

    # text ------------------------------------------------------------------
    def _end_line(self, *, force: bool) -> None:
        if not self._cur and not force:
            return
        text = _collapse("".join(piece for piece, _ in self._cur))
        bold = bool(text) and all(b for piece, b in self._cur if piece.strip())
        self._lines.append((text, bold))
        self._cur = []

    def _flush_text(self, *, heading: str | None = None) -> None:
        self._end_line(force=False)
        self.sections.extend(_sections_from_lines(self._lines, forced_heading=heading))
        self._lines = []

    def _close_item(self) -> None:
        if self._item is None:
            return
        text = _collapse("".join(self._item))
        if text:
            depth, ordered = self._item_meta
            self._items.append(ListItem(text, depth, ordered))
        self._item = None

    def _open_item(self) -> None:
        self._close_item()
        self._item = []
        self._item_meta = (len(self._list_stack) - 1, self._list_stack[-1])

    # parser hooks ----------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HEADING_TAGS:
            self._flush_text()
            self._heading = tag
        elif tag in ("ul", "ol"):
            if not self._list_stack:
                self._flush_text()
            self._close_item()
            self._list_stack.append(tag == "ol")
        elif tag == "li":
            if not self._list_stack:
                self._flush_text()
                self._list_stack.append(False)
            self._open_item()
        elif tag == "br":
            if self._item is not None:
                self._item.append(" ")
            elif self._heading is not None:
                self._cur.append((" ", False))
            else:
                self._end_line(force=True)
        elif tag in _BOLD_TAGS:
            self._bold += 1
        elif tag == "img":
            raw = Section(SectionKind.RAW, (self.get_starttag_text() or "<img>",))
            if self._list_stack:
                self._pending_raw.append(raw)
            else:
                self._flush_text()
                self.sections.append(raw)
        elif tag in _BLOCK_TAGS:
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if tag in _HEADING_TAGS:
            if self._heading == tag:
                self._flush_text(heading=tag)
                self._heading = None
        elif tag in ("ul", "ol"):
            self._close_item()
            if self._list_stack:
                self._list_stack.pop()
            if not self._list_stack:
                if self._items:
                    self.sections.append(Section(SectionKind.LIST, items=tuple(self._items)))
                self._items = []
                self.sections.extend(self._pending_raw)
                self._pending_raw = []
        elif tag == "li":
            self._close_item()
        elif tag in _BOLD_TAGS:
            self._bold = max(0, self._bold - 1)
        elif tag in _BLOCK_TAGS:
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if self._list_stack:
            if self._item is None:
                if not data.strip():
                    return
                self._open_item()
            assert self._item is not None  # noqa: S101 -- narrowing for mypy
            self._item.append(data)
        else:
            self._cur.append((data, self._bold > 0))

    def finish(self) -> DescriptionSkeleton:
        self.close()
        while self._list_stack:  # unclosed list in messy HTML
            self.handle_endtag("ul")
        self._flush_text(heading=self._heading)
        self.sections.extend(self._pending_raw)
        return tuple(self.sections)


def parse_description(html_text: str) -> DescriptionSkeleton:
    """Read a seller's description (HTML or plain text) into ordered sections."""
    if not html_text or not html_text.strip():
        return ()
    if not _MARKUP_RE.search(html_text):
        lines = [(_collapse(html.unescape(line)), False) for line in html_text.splitlines()]
        return tuple(_sections_from_lines(lines))
    builder = _SkeletonBuilder()
    builder.feed(html_text)
    return builder.finish()


# -------------------------------------------------------------------------- render


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _render_list(items: tuple[ListItem, ...]) -> str:
    out: list[str] = []
    stack: list[str] = []
    for item in items:
        tag = "ol" if item.ordered else "ul"
        while len(stack) > item.depth + 1:
            out.append(f"</li></{stack.pop()}>")
        if len(stack) == item.depth + 1:
            out.append("</li>")
            if stack[-1] != tag:
                out.append(f"</{stack.pop()}><{tag}>")
                stack.append(tag)
        else:
            while len(stack) < item.depth + 1:
                out.append(f"<{tag}>")
                stack.append(tag)
                if len(stack) < item.depth + 1:
                    out.append("<li>")
        out.append(f"<li>{_esc(item.text)}")
    while stack:
        out.append(f"</li></{stack.pop()}>")
    return "".join(out)


def _render_section(section: Section) -> str:
    if section.kind is SectionKind.RAW:
        return section.lines[0]
    if section.kind is SectionKind.LIST:
        return _render_list(section.items)
    if section.kind is SectionKind.HEADING:
        text = _esc(section.lines[0])
        if section.heading_style in _HEADING_TAGS:
            return f"<{section.heading_style}>{text}</{section.heading_style}>"
        return f"<p><strong>{text}</strong></p>"
    return "<p>" + "<br>".join(_esc(line) for line in section.lines) + "</p>"


def render_description(skeleton: DescriptionSkeleton) -> str:
    """Write the skeleton back as HTML (``<p>``/``<br>``, lists, headings)."""
    return "".join(_render_section(section) for section in skeleton)


# ----------------------------------------------------------------------------- ops


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReplaceTitleSpan(_Strict):
    op: Literal["replace_title_span"]
    old: str
    new: str
    reason_code: str


class ReplaceSpan(_Strict):
    op: Literal["replace_span"]
    section_index: int
    old: str
    new: str
    reason_code: str


class InsertAfter(_Strict):
    op: Literal["insert_after"]
    section_index: int
    text: str
    reason_code: str


class AppendSection(_Strict):
    op: Literal["append_section"]
    heading: str
    body: str
    reason_code: str


DescriptionOp = Annotated[ReplaceSpan | InsertAfter | AppendSection, Field(discriminator="op")]


class ListingEditOps(_Strict):
    """What the model returns: edits to apply to the original title and description."""

    title_ops: list[ReplaceTitleSpan]
    description_ops: list[DescriptionOp]


class RejectionCode(str, Enum):
    LISTING_OVER_LIMITS = "listing_over_limits"
    RESULT_OVER_LIMITS = "result_over_limits"
    REASON_CODE_WRONG_FIELD = "reason_code_wrong_field"
    OLD_EMPTY = "old_empty"
    OLD_NOT_FOUND = "old_not_found"
    OLD_AMBIGUOUS = "old_ambiguous"
    SECTION_INDEX_OUT_OF_RANGE = "section_index_out_of_range"
    SECTION_NOT_EDITABLE = "section_not_editable"
    APPEND_CODE_NOT_FLAGGED = "append_code_not_flagged"
    SECTION_DROPPED = "section_dropped"
    SECTION_STRUCTURE_CHANGED = "section_structure_changed"
    TITLE_EMPTIED = "title_emptied"
    INSERT_TEXT_INVALID = "insert_text_invalid"
    OPS_OVERLAP = "ops_overlap"


@dataclass(frozen=True)
class EditRejection:
    code: RejectionCode
    field: Literal["title", "description"]
    op_index: int | None
    message: str


@dataclass(frozen=True)
class EditResult:
    title: str
    description_html: str
    skeleton: DescriptionSkeleton
    changed: bool


class _Reject(Exception):
    def __init__(self, rejection: EditRejection) -> None:
        super().__init__(rejection.message)
        self.rejection = rejection


def _reject(
    code: RejectionCode, field: Literal["title", "description"], index: int | None, message: str
) -> _Reject:
    return _Reject(EditRejection(code, field, index, message))


def _locate(
    text: str, old: str, field: Literal["title", "description"], index: int, where: str
) -> int:
    if not old:
        raise _reject(RejectionCode.OLD_EMPTY, field, index, "`old` must not be empty.")
    count = text.count(old)
    if count == 0:
        raise _reject(
            RejectionCode.OLD_NOT_FOUND, field, index,
            f"`old` was not found verbatim in {where}; copy it exactly from the original text.",
        )  # fmt: skip
    if count > 1:
        raise _reject(
            RejectionCode.OLD_AMBIGUOUS, field, index,
            f"`old` occurs {count} times in {where}; "
            "include more surrounding text so it is unique.",
        )  # fmt: skip
    return text.index(old)


def _splice(
    text: str, spans: list[tuple[int, int, str, int]], field: Literal["title", "description"]
) -> str:
    """Apply (start, end, new, op_index) spans; reject overlaps."""
    ordered = sorted(spans)
    for (_, prev_end, _, prev_idx), (start, _, _, idx) in zip(ordered, ordered[1:], strict=False):
        if start < prev_end:
            raise _reject(
                RejectionCode.OPS_OVERLAP, field, idx,
                f"Operation {idx} overlaps operation {prev_idx}; make their `old` spans disjoint.",
            )  # fmt: skip
    for start, end, new, _ in reversed(ordered):
        text = text[:start] + new + text[end:]
    return text


def _apply_title(title: str, ops: list[ReplaceTitleSpan]) -> str:
    spans: list[tuple[int, int, str, int]] = []
    for i, op in enumerate(ops):
        if not is_title_code(op.reason_code):
            raise _reject(
                RejectionCode.REASON_CODE_WRONG_FIELD, "title", i,
                f"reason_code {op.reason_code!r} is not a title diagnosis code.",
            )  # fmt: skip
        start = _locate(title, op.old, "title", i, "the title")
        spans.append((start, start + len(op.old), op.new, i))
    result = _collapse(_splice(title, spans, "title")) if spans else title
    if spans and not result:
        raise _reject(
            RejectionCode.TITLE_EMPTIED, "title", None, "The edits leave the title empty."
        )
    return result


def _rebuild_section(section: Section, new_text: str, index: int) -> Section:
    lines = [_collapse(line) for line in new_text.split("\n")]
    where = f"section {index}"
    if any(not line for line in lines):
        raise _reject(
            RejectionCode.SECTION_STRUCTURE_CHANGED, "description", None,
            f"The edit leaves an empty line in {where}; a section must not be split or emptied.",
        )  # fmt: skip
    if section.kind is SectionKind.HEADING:
        if len(lines) != 1:
            raise _reject(
                RejectionCode.SECTION_STRUCTURE_CHANGED, "description", None,
                f"A heading is one line; the edit adds a line break in {where}.",
            )  # fmt: skip
        return replace(section, lines=(lines[0],))
    before = len(section.items) if section.kind is SectionKind.LIST else len(section.lines)
    if len(lines) < before:
        raise _reject(
            RejectionCode.SECTION_DROPPED, "description", None,
            f"The edit merges or drops lines/items of {where} ({before} -> {len(lines)}).",
        )  # fmt: skip
    if section.kind is SectionKind.LIST:
        items = tuple(
            ListItem(line, *(
                (section.items[i].depth, section.items[i].ordered)
                if i < len(section.items)
                else (section.items[-1].depth, section.items[-1].ordered)
            ))
            for i, line in enumerate(lines)
        )  # fmt: skip
        return replace(section, items=items)
    return replace(section, lines=tuple(lines))


def _paragraphs(body: str) -> list[Section]:
    lines = [(_collapse(line), False) for line in body.splitlines()]
    return _sections_from_lines(lines)


def _apply_description(
    skeleton: DescriptionSkeleton, ops: list[DescriptionOp], flagged_codes: Collection[str]
) -> DescriptionSkeleton:
    replacements: dict[int, list[tuple[int, int, str, int]]] = {}
    inserts: dict[int, list[Section]] = {}
    appended: list[Section] = []
    texts = [section_text(s) for s in skeleton]

    def check_index(index: int, op_index: int) -> None:
        if not 0 <= index < len(skeleton):
            raise _reject(
                RejectionCode.SECTION_INDEX_OUT_OF_RANGE, "description", op_index,
                f"section_index {index} is out of range; "
                f"the description has {len(skeleton)} sections (0-based).",
            )  # fmt: skip

    for i, op in enumerate(ops):
        if isinstance(op, AppendSection):
            if op.reason_code not in flagged_codes:
                raise _reject(
                    RejectionCode.APPEND_CODE_NOT_FLAGGED, "description", i,
                    "A section may be appended only to fix a flagged code; "
                    f"{op.reason_code!r} is not flagged on this product.",
                )  # fmt: skip
            heading, body = _collapse(op.heading), _paragraphs(op.body)
            if not heading or not body:
                raise _reject(
                    RejectionCode.INSERT_TEXT_INVALID, "description", i,
                    "append_section needs a non-empty heading and body.",
                )  # fmt: skip
            style = (
                next(
                    (s.heading_style for s in reversed(skeleton) if s.kind is SectionKind.HEADING),
                    None,
                )
                or _BOLD_HEADING
            )
            appended.append(Section(SectionKind.HEADING, (heading,), heading_style=style))
            appended.extend(body)
            continue
        if not is_description_code(op.reason_code):
            raise _reject(
                RejectionCode.REASON_CODE_WRONG_FIELD, "description", i,
                f"reason_code {op.reason_code!r} is not a description diagnosis code.",
            )  # fmt: skip
        check_index(op.section_index, i)
        if isinstance(op, InsertAfter):
            new_sections = _paragraphs(op.text)
            if len(new_sections) != 1 or new_sections[0].kind is not SectionKind.PARAGRAPH:
                raise _reject(
                    RejectionCode.INSERT_TEXT_INVALID, "description", i,
                    "insert_after text must be one non-empty paragraph with no blank line.",
                )  # fmt: skip
            inserts.setdefault(op.section_index, []).append(new_sections[0])
            continue
        section = skeleton[op.section_index]
        if section.kind is SectionKind.RAW:
            raise _reject(
                RejectionCode.SECTION_NOT_EDITABLE, "description", i,
                f"section {op.section_index} is an image/markup block and cannot be edited.",
            )  # fmt: skip
        text = texts[op.section_index]
        start = _locate(text, op.old, "description", i, f"section {op.section_index}")
        replacements.setdefault(op.section_index, []).append(
            (start, start + len(op.old), op.new, i)
        )

    out: list[Section] = []
    for index, section in enumerate(skeleton):
        spans = replacements.get(index)
        if spans:
            new_text = _splice(texts[index], spans, "description")
            section = _rebuild_section(section, new_text, index)
        out.append(section)
        out.extend(inserts.get(index, []))
    out.extend(appended)
    return tuple(out)


def apply_ops(
    original_title: str,
    original_description_html: str,
    ops: ListingEditOps,
    flagged_codes: Collection[str],
) -> EditResult | EditRejection:
    """Apply the model's edit ops to the original listing, or say exactly why not."""
    if (
        len(original_title) > TITLE_MAX_CHARS
        or len(original_description_html) > DESCRIPTION_MAX_CHARS
    ):
        return EditRejection(
            RejectionCode.LISTING_OVER_LIMITS,
            "title" if len(original_title) > TITLE_MAX_CHARS else "description",
            None,
            "The listing already exceeds TikTok's length limits "
            f"(title {TITLE_MAX_CHARS}, description {DESCRIPTION_MAX_CHARS}); it is not edited.",
        )
    try:
        title = _apply_title(original_title, ops.title_ops)
        skeleton = parse_description(original_description_html)
        if ops.description_ops:
            skeleton = _apply_description(skeleton, ops.description_ops, flagged_codes)
            description = render_description(skeleton)
        else:
            description = original_description_html
    except _Reject as exc:
        return exc.rejection
    if len(title) > TITLE_MAX_CHARS:
        return EditRejection(
            RejectionCode.RESULT_OVER_LIMITS, "title", None,
            f"The edited title has {len(title)} characters; the limit is {TITLE_MAX_CHARS}.",
        )  # fmt: skip
    if len(description) > DESCRIPTION_MAX_CHARS:
        return EditRejection(
            RejectionCode.RESULT_OVER_LIMITS, "description", None,
            f"The edited description has {len(description)} characters; "
            f"the limit is {DESCRIPTION_MAX_CHARS}.",
        )  # fmt: skip
    changed = title != original_title or description != original_description_html
    return EditResult(title, description, skeleton, changed)
