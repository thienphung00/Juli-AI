"""Ảnh bìa banners (P100 brief D, Flow v4; design https://claude.ai/artifact/4SuySBPc5VbTQFU1SMK1wx).

The E.7 ``banner`` spec (``fasttrack/contracts/p100-s2-demo.md``, schema_version 1): a template, a
day mode and up to 3 (Ngày thường) or 4 (Mega Sale) banners, each a kind with a fixed shape and the
positions that shape allows. Values are typed raw (money = integer đ, % = number, text = text); the
display text is derived here and in ``apps/demo/src/lib/shopee-decisions/banner.ts`` from the same
rules (``tests/fixtures/banner_cases.json`` pins both). The rule checks are the design's step 4.

Pure: no I/O. Rendering (compositing over the real cover, PNG 1200 px) is the browser's; nothing is
generated, and the product photo is never altered.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SIZE_PX = 1200
#: Shape -> the positions it may take, in the order a new banner tries them. Bottom-left is never
#: offered (Shopee's voucher strip), so no wide strip at the bottom either.
SHAPES: dict[str, tuple[str, ...]] = {
    "ngang": ("top",),
    "goc": ("top_left", "top_right"),
    "the": ("middle_right", "bottom_right"),
}
TEMPLATES = ("toi_gian", "noi_bat", "khung_vien")
DAY_LIMITS = {"ngay_thuong": 3, "mega_sale": 4}
#: Colours offered when the shop has no style profile yet (the design's palette).
DEFAULT_PALETTE = ("#2F7D4F", "#EE4D2D", "#121214", "#C98A00")
HEAD_MAX = 22
BANNER_MAX = 40
TOTAL_MAX = 90

FieldType = Literal["money", "pct", "int", "text"]


@dataclass(frozen=True)
class Kind:
    kind: str
    shape: str
    mega_only: bool
    fields: tuple[tuple[str, FieldType], ...]


KINDS: dict[str, Kind] = {
    k.kind: k
    for k in (
        Kind("mega", "ngang", True, (("title", "text"), ("sub", "text"), ("dates", "text"))),
        Kind("pct", "goc", False, (("pct", "pct"),)),
        Kind("genuine", "goc", False, (("text", "text"),)),
        Kind("freeship", "goc", False, (("min", "money"),)),
        Kind("combo", "the", False, (("q1", "int"), ("p1", "pct"), ("q2", "int"), ("p2", "pct"))),
        Kind("voucher", "the", False, (("value", "money"), ("min", "money"))),
        Kind("gift", "the", False, (("min", "money"), ("gift", "text"))),
        Kind("addon", "the", False, (("item", "text"), ("pct", "pct"))),
        Kind("unit", "the", False, (("price", "money"), ("qty", "int"), ("unit", "text"))),
        Kind("quy_cach", "the", False, (("text", "text"),)),
    )
}

Value = int | float | str | None
_HEX = r"^#[0-9A-Fa-f]{6}$"


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str | None = None
    field: str = Field(min_length=1, max_length=120)


class Banner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: Literal["ngang", "goc", "the"]
    kind: str
    values: dict[str, Value] = Field(default_factory=dict)
    sources: dict[str, Source] = Field(default_factory=dict)
    position: Literal["top", "top_left", "top_right", "middle_right", "bottom_right"]
    colour: Annotated[str, Field(pattern=_HEX)]
    size: Literal["S", "M", "L"] = "M"

    @model_validator(mode="after")
    def _kind_shape_values(self) -> Banner:
        k = KINDS.get(self.kind)
        if k is None:
            raise ValueError(f"unknown banner kind {self.kind!r}")
        if self.shape != k.shape:
            raise ValueError(f"{self.kind} is a {k.shape} banner")
        if self.position not in SHAPES[k.shape]:
            raise ValueError(f"{self.position} is not a {k.shape} position")
        types = dict(k.fields)
        for key, v in self.values.items():
            t = types.get(key)
            if t is None:
                raise ValueError(f"{self.kind} has no field {key!r}")
            if v is None:
                continue
            if t == "text" and (not isinstance(v, str) or len(v) > 60):
                raise ValueError(f"{key} must be text of at most 60 characters")
            if t in ("money", "int") and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                raise ValueError(f"{key} must be a whole number")
            if t == "pct" and (
                isinstance(v, bool) or not isinstance(v, int | float) or not 0 <= v <= 100
            ):
                raise ValueError(f"{key} must be a percent from 0 to 100")
        for key in self.sources:
            if key not in types:
                raise ValueError(f"{self.kind} has no field {key!r}")
        return self


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    banner: int | None = None
    title: str = ""
    fix: str = ""


class BannerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Literal["toi_gian", "noi_bat", "khung_vien"]
    day_mode: Literal["ngay_thuong", "mega_sale"]
    size_px: Literal[1200] = 1200
    banners: list[Banner] = Field(default_factory=list, max_length=4)
    checks: list[Check] = Field(default_factory=list)
    check_call_id: str | None = None

    @model_validator(mode="after")
    def _limits(self) -> BannerSpec:
        if len(self.banners) > DAY_LIMITS[self.day_mode]:
            raise ValueError(f"{self.day_mode} takes at most {DAY_LIMITS[self.day_mode]} banners")
        kinds = [b.kind for b in self.banners]
        if len(set(kinds)) != len(kinds):
            raise ValueError("one banner per kind")
        if self.day_mode != "mega_sale" and any(KINDS[k].mega_only for k in kinds):
            raise ValueError("the Mega Sale strip needs the Mega Sale day mode")
        return self


# ------------------------------------------------------------------ display text


def vnd(n: float) -> str:
    """``12345`` -> ``12.345đ`` (vi-VN grouping; halves round up, as the editor's JS does)."""
    whole = int(Decimal(str(n)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return f"{whole:,}".replace(",", ".") + "đ"


def k(n: float) -> str:
    """``149000`` -> ``149K``; a value not in whole thousands stays in đ."""
    if n % 1000 == 0:
        return f"{int(n // 1000):,}".replace(",", ".") + "K"
    return vnd(n)


def _num(v: Value) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        return float(v) if v > 0 else None
    digits = re.sub(r"[^0-9]", "", str(v))
    return float(digits) if digits and int(digits) > 0 else None


def _pct(v: Value) -> str:
    n = _num(v)
    if n is None:
        return ""
    return f"{n:g}".replace(".", ",")


def _text(v: Value) -> str:
    return str(v).strip() if isinstance(v, str) else ""


def text(kind: str, values: Mapping[str, Value]) -> tuple[str, str]:
    """The banner's head and sub line from its raw values (the design's ``catalog().text``). A
    missing value shows as a bracketed placeholder, never an invented claim."""
    f = values
    if kind == "mega":
        title, sub = _text(f.get("title")) or "Sale", _text(f.get("sub"))
        return title + (" · " + sub if sub else ""), _text(f.get("dates"))
    if kind == "pct":
        p = _pct(f.get("pct"))
        return (f"−{p}%" if p else "−…%"), ""
    if kind == "genuine":
        return _text(f.get("text")) or "Chính hãng", ""
    if kind == "freeship":
        m = _num(f.get("min"))
        return "Freeship", (f"Đơn từ {k(m)}" if m else "")
    if kind == "combo":
        q1, p1, q2, p2 = (_pct(f.get(x)) for x in ("q1", "p1", "q2", "p2"))
        head = f"Mua {q1} giảm {p1}%" if q1 and p1 else "Combo"
        return head, (f"Mua {q2} giảm {p2}%" if q2 and p2 else "")
    if kind == "voucher":
        v, m = _num(f.get("value")), _num(f.get("min"))
        return (f"Voucher giảm {k(v)}" if v else "Voucher"), (f"Đơn từ {k(m)}" if m else "")
    if kind == "gift":
        m = _num(f.get("min"))
        return (f"Mua từ {k(m)}" if m else "Quà tặng"), "Tặng " + (
            _text(f.get("gift")) or "[tên quà]"
        )
    if kind == "addon":
        p = _pct(f.get("pct"))
        return "Mua kèm " + (_text(f.get("item")) or "[sản phẩm]"), (f"giảm {p}%" if p else "")
    if kind == "unit":
        price, qty = _num(f.get("price")), _num(f.get("qty"))
        unit = _text(f.get("unit")) or "đơn vị"
        if price and qty:
            return f"Chỉ {vnd(price / qty)}/{unit}", f"{vnd(price)} · {qty:g} {unit}"
        return f"Giá / {unit}", f"Nhập số {unit} trong gói"
    if kind == "quy_cach":
        return _text(f.get("text")) or "[quy cách]", ""
    raise ValueError(f"unknown banner kind {kind!r}")


# ------------------------------------------------------------------ rule checks (step 4)

_POSITION_LABEL = {
    "top": "Dải trên",
    "top_left": "Trên trái",
    "top_right": "Trên phải",
    "middle_right": "Giữa phải",
    "bottom_right": "Dưới phải",
}
KIND_TITLE = {
    "mega": "Mega Sale",
    "pct": "Giảm %",
    "genuine": "Chính hãng",
    "freeship": "Freeship",
    "combo": "Combo",
    "voucher": "Voucher",
    "gift": "Quà tặng",
    "addon": "Mua kèm",
    "unit": "Giá / đơn vị",
    "quy_cach": "Quy cách",
}
_PLACEHOLDER = re.compile(r"\[|…|Nhập số")


def rule_checks(spec: BannerSpec) -> list[Check]:
    """The design's step-4 checks, in its order: overlap, then per banner (long head, empty value,
    too much text), then the whole cover (total text, Mega Sale without its strip)."""
    out: list[Check] = []
    by_pos: dict[str, list[int]] = {}
    for i, b in enumerate(spec.banners):
        by_pos.setdefault(b.position, []).append(i)
    used = {b.position for b in spec.banners}
    for pos, idx in by_pos.items():
        if len(idx) < 2:
            continue
        mover = spec.banners[idx[1]]
        free = next((p for p in SHAPES[mover.shape] if p not in used), None)
        names = " + ".join(KIND_TITLE[spec.banners[i].kind] for i in idx)
        out.append(
            Check(
                code="overlap",
                banner=idx[1],
                title=f"Hai banner chồng nhau: {names}",
                fix=(
                    f"Chuyển {KIND_TITLE[mover.kind]} sang {_POSITION_LABEL[free]}."
                    if free
                    else "Bỏ bớt một banner cùng dạng."
                ),
            )
        )
    total = 0
    for i, b in enumerate(spec.banners):
        head, sub = text(b.kind, b.values)
        total += len(head) + len(sub)
        name = KIND_TITLE[b.kind]
        if len(head) > HEAD_MAX:
            out.append(
                Check(
                    code="text_long",
                    banner=i,
                    title=f"{name}: dòng chính dài {len(head)} ký tự",
                    fix=f"Giữ dưới {HEAD_MAX} ký tự để đọc được trên điện thoại.",
                )
            )
        if _PLACEHOLDER.search(head + sub):
            out.append(
                Check(
                    code="empty_value",
                    banner=i,
                    title=f"{name}: còn ô chưa có giá trị",
                    fix="Điền giá trị ở bước 3 hoặc bỏ banner này.",
                )
            )
        if len(head) + 1 + len(sub) > BANNER_MAX:
            out.append(
                Check(
                    code="overload",
                    banner=i,
                    title=f"{name}: quá nhiều chữ",
                    fix="Bỏ dòng phụ để ảnh thoáng hơn.",
                )
            )
    if total > TOTAL_MAX:
        out.append(
            Check(
                code="overload",
                title=f"Tổng chữ trên ảnh: {total} ký tự",
                fix=f"Ảnh bìa nhỏ trên điện thoại; nên giữ dưới {TOTAL_MAX} ký tự.",
            )
        )
    if spec.day_mode == "mega_sale" and not any(b.shape == "ngang" for b in spec.banners):
        out.append(
            Check(
                code="missing_strip",
                title="Mega Sale chưa có dải tên sale",
                fix="Thêm banner Mega Sale ở dải trên.",
            )
        )
    return out


def with_checks(spec: BannerSpec) -> BannerSpec:
    """The spec with its rule checks filled in (what is stored)."""
    return spec.model_copy(update={"checks": rule_checks(spec)})


def palette_of(profile: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The colours a banner may take: the shop style profile's palette, else the default."""
    pal = (profile or {}).get("palette")
    if isinstance(pal, Sequence) and not isinstance(pal, str):
        found = tuple(str(c).upper() for c in pal if isinstance(c, str) and re.match(_HEX, c))
        if found:
            return found
    return DEFAULT_PALETTE


def off_palette(spec: BannerSpec, palette: Sequence[str]) -> list[int]:
    """Indexes of the banners whose colour is not in the palette."""
    allowed = {c.upper() for c in palette}
    return [i for i, b in enumerate(spec.banners) if b.colour.upper() not in allowed]


def summary(spec: BannerSpec) -> str:
    """One line for a card: what the cover will say."""
    parts = []
    for b in spec.banners:
        head, sub = text(b.kind, b.values)
        parts.append(head + (f" ({sub})" if sub else ""))
    return "; ".join(parts) or "chưa có banner"
