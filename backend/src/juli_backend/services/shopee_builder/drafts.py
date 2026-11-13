"""P92 B-4 / B-6: LLM drafts -- titles, cover-image overlay concepts, description first lines.

The model only writes words. Every number that reaches a cover comes from the product's own
facts (a variation's price, its list price, the discount between them, a running voucher, the
unit price), every title / line is checked after the model answers, and a draft that breaks a check
is dropped, never repaired by guessing:

- a title is at most ``MAX_TITLE_CHARS`` (100) characters and holds EVERY ticked keyword;
- no seller banned term, no generic claim pattern (``listing.is_clean``);
- no certification, ingredient or health claim the product's facts do not state: a claim word is
  allowed only when it already stands in the current title, a ticked keyword or a fact given;
- no price or percent that is not one of the product's own;
- an overlay concept's numbers are filled in by this module from the facts, the model picks the
  layout, which variation, whether to show the voucher / the unit price and the hook words.

The model is behind ``llm.LLMClient``; nothing here knows OpenAI.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.shopee_analytics.fee_table import fold
from juli_backend.services.shopee_builder.llm import (
    REASON_BAD_OUTPUT,
    LLMClient,
    LLMUnavailable,
)
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations import listing as lst

MIN_DRAFTS, MAX_DRAFTS = 2, 4
MAX_HOOK_CHARS = 40
MAX_KEYWORDS = 12
LAYOUTS = ("banner_top", "banner_bottom", "corner_tag")

#: Words that claim a certification, an ingredient or a health effect. A draft may use one only
#: when it already stands in the product's own title, a ticked keyword or a given fact.
CLAIM_TERMS: tuple[str, ...] = (
    "chứng nhận",
    "chứng chỉ",
    "đạt chuẩn",
    "tiêu chuẩn",
    "iso",
    "fda",
    "gmp",
    "haccp",
    "vietgap",
    "globalgap",
    "organic",
    "hữu cơ",
    "bộ y tế",
    "vsattp",
    "ecocert",
    "fsc",
    "halal",
    "usda",
    "không chứa",
    "chiết xuất",
    "tinh chất",
    "thành phần",
    "100% tự nhiên",
    "thiên nhiên",
    "không hóa chất",
    "không paraben",
    "không độc hại",
    "an toàn tuyệt đối",
    "vegan",
    "phân hủy",
    "kháng khuẩn",
    "diệt khuẩn",
    "chống",
    "trị",
    "chữa",
    "giảm cân",
    "hiệu quả",
)

_MONEY = re.compile(r"(\d[\d.,]*)\s*(k|nghìn|ngàn|đ|vnd|vnđ)\b", re.IGNORECASE)
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


@dataclass(frozen=True)
class ProductFacts:
    """Everything a draft may state about a product, and nothing else."""

    item_id: str
    title: str
    variations: Sequence[Mapping[str, Any]] = ()
    unit_price_line: str | None = None
    voucher_text: str | None = None
    voucher_amount_vnd: int | None = None
    tone: str | None = None
    banned_terms: tuple[str, ...] = ()
    #: extra sentences the seller or Juli stated about the product (never invented here)
    notes: tuple[str, ...] = ()

    def prices(self) -> set[int]:
        out: set[int] = set()
        for v in self.variations:
            for key in ("selling_price", "list_price", "price_per_unit"):
                if v.get(key):
                    out.add(int(round(v[key])))
        if self.voucher_amount_vnd:
            out.add(self.voucher_amount_vnd)
        return out

    def discount_pcts(self) -> set[int]:
        out: set[int] = set()
        for v in self.variations:
            sell, listed = v.get("selling_price"), v.get("list_price")
            if sell and listed and listed > sell:
                out.add(int(round((1 - sell / listed) * 100)))
        return out

    def allowed_text(self, extra: Iterable[str] = ()) -> str:
        parts = [self.title, *self.notes, *extra]
        parts += [str(v.get("name") or "") for v in self.variations]
        if self.voucher_text:
            parts.append(self.voucher_text)
        return fold(" ".join(parts))


class NoValidDraft(ValueError):
    """The model answered but nothing it wrote passed the checks."""

    def __init__(self, dropped: list[dict[str, str]]) -> None:
        super().__init__("no draft passed the checks")
        self.dropped = dropped


# ----------------------------------------------------------------------------- checks


def _has_word(text_folded: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(fold(term))}(?![a-z0-9])", text_folded) is not None


def claims_in(text: str) -> list[str]:
    folded = fold(text)
    return [t for t in CLAIM_TERMS if _has_word(folded, t)]


def unsupported_claims(text: str, allowed_folded: str) -> list[str]:
    """Claim words in ``text`` that the product's own words do not already contain."""
    return [t for t in claims_in(text) if not _has_word(allowed_folded, t)]


def _money_values(text: str) -> list[int]:
    out = []
    for m in _MONEY.finditer(text):
        raw, unit = m.group(1), m.group(2).lower()
        digits = raw.replace(".", "").replace(",", "")
        if not digits.isdigit():
            continue
        n = int(digits)
        out.append(n * 1000 if unit in ("k", "nghìn", "ngàn") else n)
    return out


def numbers_problem(text: str, facts: ProductFacts) -> str | None:
    """A price or a percent in ``text`` that is not one of the product's own."""
    prices = facts.prices()
    for value in _money_values(text):
        if value not in prices:
            return f"giá {value} không phải giá của sản phẩm"
    pcts = facts.discount_pcts()
    for m in _PERCENT.finditer(text):
        n = float(m.group(1).replace(",", "."))
        if not any(abs(n - p) <= 1 for p in pcts):
            return f"{m.group(1)}% không phải mức giảm của sản phẩm"
    return None


def _drop(dropped: list[dict[str, str]], text: str, why: str) -> None:
    dropped.append({"text": text[:120], "reason": why})


# ------------------------------------------------------------------------------ titles

TITLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["drafts"],
    "properties": {
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "note"],
                "properties": {
                    "title": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        }
    },
}


def title_system(facts: ProductFacts) -> str:
    lines = [
        "Bạn viết tiêu đề sản phẩm Shopee bằng tiếng Việt cho một shop.",
        f"Mỗi tiêu đề tối đa {config.MAX_TITLE_CHARS} ký tự, đúng chính tả, có dấu.",
        "Phải chứa MỌI từ khoá được chọn, viết đúng như đã cho (giữ dấu).",
        "Chỉ dùng từ có trong tiêu đề hiện tại, từ khoá được chọn hoặc thông tin đã cho.",
        "Tuyệt đối không thêm chứng nhận, thành phần, công dụng, xuất xứ hay thương hiệu không có "
        "trong thông tin đã cho. Không hứa hẹn, không so sánh hơn nhất.",
        "Đặt từ khoá quan trọng nhất ở đầu tiêu đề.",
    ]
    if facts.tone:
        lines.append(f"Giọng văn của shop: {facts.tone}")
    if facts.banned_terms:
        lines.append("Không dùng các từ: " + ", ".join(facts.banned_terms))
    return "\n".join(lines)


def title_user(facts: ProductFacts, keywords: Sequence[str], n: int) -> str:
    variations = "; ".join(
        f"{v.get('name') or 'Mặc định'} ({v.get('selling_price')}đ)" for v in facts.variations
    )
    return (
        f"Tiêu đề hiện tại: {facts.title}\n"
        f"Từ khoá phải có: {', '.join(keywords) or '(không có)'}\n"
        f"Phân loại: {variations or '(không có)'}\n"
        f"Viết {n} tiêu đề khác nhau."
    )


def screen_titles(
    items: Sequence[object], facts: ProductFacts, kws: Sequence[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The titles of ``items`` that pass every check, and the dropped ones with the reason.

    One screen for every title Juli shows: the model's drafts and the sample shop's pre-written
    ones (P100 S2-D) -- a stored title is held to the same rules as a fresh one.
    """
    kws = list(kws)
    allowed = facts.allowed_text(kws)
    dropped: list[dict[str, str]] = []
    out: list[dict[str, Any]] = []
    seen: set[str] = {fold(facts.title)}
    for entry in items:
        title = " ".join(str(entry.get("title") if isinstance(entry, dict) else "").split())
        if not title:
            continue
        if len(title) > config.MAX_TITLE_CHARS:
            _drop(dropped, title, f"dài {len(title)} ký tự (tối đa {config.MAX_TITLE_CHARS})")
            continue
        missing = [k for k in kws if fold(k) not in fold(title)]
        if missing:
            _drop(dropped, title, "thiếu từ khoá: " + ", ".join(missing))
            continue
        if not lst.is_clean(title, facts.banned_terms):
            _drop(dropped, title, "có từ không được dùng")
            continue
        bad = unsupported_claims(title, allowed)
        if bad:
            _drop(dropped, title, "tuyên bố chưa có trong thông tin sản phẩm: " + ", ".join(bad))
            continue
        problem = numbers_problem(title, facts)
        if problem:
            _drop(dropped, title, problem)
            continue
        if fold(title) in seen:
            continue
        seen.add(fold(title))
        audit = lst.audit_title(title, kws)
        out.append(
            {
                "title": title,
                "chars": len(title),
                "keywords": {"covered": list(kws), "missing": []},
                "late_keywords": list(audit.late),
                "note": str(entry.get("note") or "")[:200] if isinstance(entry, dict) else "",
            }
        )
        if len(out) == MAX_DRAFTS:
            break
    return out, dropped


async def draft_titles(
    client: LLMClient,
    facts: ProductFacts,
    keywords: Sequence[str],
    *,
    count: int = 3,
) -> dict[str, Any]:
    """2-4 titles (≤100 characters) that hold every ticked keyword."""
    count = max(MIN_DRAFTS, min(count, MAX_DRAFTS))
    kws = [k.strip() for k in keywords if k.strip()][:MAX_KEYWORDS]
    raw = await client.complete_json(
        system=title_system(facts),
        user=title_user(facts, kws, count),
        schema_name="shopee_titles",
        schema=TITLE_SCHEMA,
    )
    items = raw.get("drafts")
    if not isinstance(items, list):
        raise LLMUnavailable(REASON_BAD_OUTPUT, "drafts missing")
    return title_result(*screen_titles(items, facts, kws))


def title_result(out: list[dict[str, Any]], dropped: list[dict[str, str]]) -> dict[str, Any]:
    """The title drafts answer (``NoValidDraft`` when nothing passed the screen)."""
    if not out:
        raise NoValidDraft(dropped)
    return {
        "drafts": out,
        "dropped": dropped,
        "max_chars": config.MAX_TITLE_CHARS,
        "warnings": [] if len(out) >= MIN_DRAFTS else ["Chỉ có một tiêu đề qua được kiểm tra."],
    }


# ------------------------------------------------------------------------------- covers

COVER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["concepts"],
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layout",
                    "variation_id",
                    "use_voucher",
                    "use_unit_price",
                    "hook_text",
                    "pack_text",
                    "rationale",
                ],
                "properties": {
                    "layout": {"type": "string", "enum": list(LAYOUTS)},
                    "variation_id": {"type": "string"},
                    "use_voucher": {"type": "boolean"},
                    "use_unit_price": {"type": "boolean"},
                    "hook_text": {"type": "string"},
                    "pack_text": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}


def cover_system(facts: ProductFacts) -> str:
    lines = [
        "Bạn đề xuất chữ ghi lên ảnh bìa sản phẩm Shopee (ảnh thật của shop, không đổi ảnh).",
        "Chỉ chọn: bố cục, phân loại nào, có hiện voucher / đơn giá hay không, và vài chữ nổi bật.",
        "Giá, giá gốc và % giảm do hệ thống điền từ dữ liệu thật, bạn không viết số.",
        f"hook_text tối đa {MAX_HOOK_CHARS} ký tự, chỉ nêu lợi ích có trong thông tin sản phẩm; "
        "để trống nếu không chắc.",
        "pack_text là quy cách có trong tên phân loại (vd. Combo 3 hộp); để trống nếu không có.",
        "Không thêm chứng nhận, thành phần, công dụng hay lời hứa nào không có trong thông tin.",
    ]
    if facts.tone:
        lines.append(f"Giọng văn của shop: {facts.tone}")
    if facts.banned_terms:
        lines.append("Không dùng các từ: " + ", ".join(facts.banned_terms))
    return "\n".join(lines)


def cover_user(facts: ProductFacts, n: int) -> str:
    rows = [
        f"- variation_id={v['variation_id']!r}: {v.get('name')}, giá {v.get('selling_price')}đ, "
        f"giá gốc {v.get('list_price')}đ, đơn giá {v.get('price_per_unit')}đ"
        for v in facts.variations
    ]
    return (
        f"Tên sản phẩm: {facts.title}\nPhân loại:\n"
        + "\n".join(rows)
        + f"\nVoucher đang chạy: {facts.voucher_text or 'không có'}\n"
        + f"Đơn giá: {facts.unit_price_line or 'không có'}\nĐề xuất {n} phương án khác nhau."
    )


def _build_overlay(
    facts: ProductFacts, variation: Mapping[str, Any], concept: Mapping[str, Any], allowed: str
) -> tuple[dict[str, Any] | None, str | None]:
    sell, listed = variation.get("selling_price"), variation.get("list_price")
    overlay: dict[str, Any] = {"layout": concept["layout"]}
    if sell:
        overlay["price_vnd"] = int(round(sell))
    if sell and listed and listed > sell:
        overlay["original_price_vnd"] = int(round(listed))
        overlay["discount_pct"] = int(round((1 - sell / listed) * 100))
    if concept.get("use_voucher") and facts.voucher_text:
        overlay["voucher_text"] = facts.voucher_text
    pack = str(concept.get("pack_text") or "").strip()
    if pack and fold(pack) in fold(str(variation.get("name") or "")):
        overlay["pack_text"] = pack[:60]
    elif (
        concept.get("use_unit_price")
        and variation.get("price_per_unit")
        and (variation.get("pack_count") or 1) > 1
    ):
        overlay["pack_text"] = f"Chỉ {lst.vnd(variation['price_per_unit'])}/món"
    hook = " ".join(str(concept.get("hook_text") or "").split())
    if hook:
        if len(hook) > MAX_HOOK_CHARS:
            return None, f"hook dài {len(hook)} ký tự (tối đa {MAX_HOOK_CHARS})"
        if not lst.is_clean(hook, facts.banned_terms):
            return None, "hook có từ không được dùng"
        bad = unsupported_claims(hook, allowed)
        if bad:
            return None, "hook có tuyên bố chưa có trong thông tin: " + ", ".join(bad)
        if numbers_problem(hook, facts):
            return None, "hook có số không phải của sản phẩm"
        if concept["layout"] == "banner_bottom":  # the CoverVariant draws the hook only there
            overlay["hook_text"] = hook
    if len(overlay) <= 1:
        return None, "không có thông tin nào để ghi lên ảnh"
    return overlay, None


async def draft_overlays(
    client: LLMClient, facts: ProductFacts, *, count: int = 3
) -> dict[str, Any]:
    """2-4 overlay concepts (text fields of the CoverVariant overlay) from the product's numbers."""
    count = max(MIN_DRAFTS, min(count, MAX_DRAFTS))
    if not facts.variations:
        raise NoValidDraft([{"text": "", "reason": "sản phẩm chưa có giá để ghi lên ảnh"}])
    raw = await client.complete_json(
        system=cover_system(facts),
        user=cover_user(facts, count),
        schema_name="shopee_cover_overlays",
        schema=COVER_SCHEMA,
    )
    items = raw.get("concepts")
    if not isinstance(items, list):
        raise LLMUnavailable(REASON_BAD_OUTPUT, "concepts missing")
    by_id = {str(v["variation_id"]): v for v in facts.variations}
    allowed = facts.allowed_text()
    dropped: list[dict[str, str]] = []
    out: list[dict[str, Any]] = []
    seen: list[dict[str, Any]] = []
    for concept in items:
        if not isinstance(concept, dict) or concept.get("layout") not in LAYOUTS:
            continue
        variation = by_id.get(str(concept.get("variation_id")))
        if variation is None:
            variation = next(iter(by_id.values()))
        overlay, why = _build_overlay(facts, variation, concept, allowed)
        if overlay is None:
            _drop(
                dropped, str(concept.get("hook_text") or concept.get("rationale") or ""), why or ""
            )
            continue
        if overlay in seen:
            continue
        seen.append(overlay)
        out.append(
            {
                "overlay": overlay,
                "variation_id": variation["variation_id"],
                "hook_text": overlay.get("hook_text"),
                "rationale": str(concept.get("rationale") or "")[:200],
            }
        )
        if len(out) == MAX_DRAFTS:
            break
    if not out:
        raise NoValidDraft(dropped)
    return {
        "concepts": out,
        "dropped": dropped,
        "layouts": list(LAYOUTS),
        "note": "Ảnh thật của sản phẩm được giữ nguyên; chỉ thêm chữ.",
    }


# ------------------------------------------------------------------------- descriptions

DESCRIPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["drafts"],
    "properties": {
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["first_line", "note"],
                "properties": {
                    "first_line": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        }
    },
}


def description_system(facts: ProductFacts) -> str:
    lines = [
        "Bạn viết DÒNG ĐẦU mô tả sản phẩm Shopee bằng tiếng Việt: một câu, không xuống dòng.",
        f"Tối đa {lst.MAX_DESCRIPTION_LINE_CHARS} ký tự; nêu đơn giá (nếu có), một lợi ích chính.",
        "Lợi ích chỉ lấy từ tiêu đề và thông tin sản phẩm đã cho. Giá và % chỉ dùng số đã cho.",
        "Không thêm chứng nhận, thành phần, công dụng hay lời hứa không có trong thông tin.",
    ]
    if facts.tone:
        lines.append(f"Giọng văn của shop: {facts.tone}")
    if facts.banned_terms:
        lines.append("Không dùng các từ: " + ", ".join(facts.banned_terms))
    return "\n".join(lines)


def description_user(facts: ProductFacts, n: int) -> str:
    rows = [
        f"- {v.get('name') or 'Mặc định'}: giá {v.get('selling_price')}đ, "
        f"đơn giá {v.get('price_per_unit')}đ"
        for v in facts.variations
    ]
    return (
        f"Tên sản phẩm: {facts.title}\nPhân loại:\n"
        + "\n".join(rows)
        + f"\nĐơn giá: {facts.unit_price_line or 'không có'}\nViết {n} dòng khác nhau."
    )


async def draft_descriptions(
    client: LLMClient, facts: ProductFacts, *, count: int = 3
) -> dict[str, Any]:
    count = max(MIN_DRAFTS, min(count, MAX_DRAFTS))
    raw = await client.complete_json(
        system=description_system(facts),
        user=description_user(facts, count),
        schema_name="shopee_description_lines",
        schema=DESCRIPTION_SCHEMA,
    )
    items = raw.get("drafts")
    if not isinstance(items, list):
        raise LLMUnavailable(REASON_BAD_OUTPUT, "drafts missing")
    allowed = facts.allowed_text()
    dropped: list[dict[str, str]] = []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in items:
        written = str(entry.get("first_line") if isinstance(entry, dict) else "").strip()
        line = " ".join(written.split())
        if not line:
            continue
        reason = lst.check_planned(
            "description_first_line",
            {
                "first_line": written if "\n" in written else line
            },  # a line break is one line too many
            facts.banned_terms,
        )
        if reason:
            _drop(dropped, line, reason)
            continue
        bad = unsupported_claims(line, allowed)
        if bad:
            _drop(dropped, line, "tuyên bố chưa có trong thông tin sản phẩm: " + ", ".join(bad))
            continue
        problem = numbers_problem(line, facts)
        if problem:
            _drop(dropped, line, problem)
            continue
        if fold(line) in seen:
            continue
        seen.add(fold(line))
        out.append(
            {"first_line": line, "chars": len(line), "note": str(entry.get("note") or "")[:200]}
        )
        if len(out) == MAX_DRAFTS:
            break
    if not out:
        raise NoValidDraft(dropped)
    return {"drafts": out, "dropped": dropped, "max_chars": lst.MAX_DESCRIPTION_LINE_CHARS}


@dataclass
class DraftContext:
    facts: ProductFacts
    keywords: list[str] = field(default_factory=list)


__all__ = [
    "CLAIM_TERMS",
    "LAYOUTS",
    "DraftContext",
    "NoValidDraft",
    "ProductFacts",
    "claims_in",
    "draft_descriptions",
    "draft_overlays",
    "draft_titles",
    "numbers_problem",
    "screen_titles",
    "title_result",
    "unsupported_claims",
]
