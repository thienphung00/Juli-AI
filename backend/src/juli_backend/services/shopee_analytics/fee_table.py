"""The fee formula a Shopee line is charged when its order export carries no actual fee.

Order of authority (contract 4 / 13): the order export's actual fees win; else a
``platform_fee_formulas`` row for the item's category; else the code-level seed below
(``shopee_vn_non_mall`` with the fixed-fee rate of the item's category, contract 10a); else the
shop default rate, flagged ``default_assumed``. Every choice reports where the rate came from.

The seed is ORY's categories from the 23/05/2026 non-Mall table (VAT incl.). It is a stop-gap
until ``platform_fee_formulas`` rows exist; a database row for the same category wins.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.fees import (
    FeeBase,
    FeeComponent,
    FeeFormula,
    FeeKind,
    FeeSchedule,
    shopee_vn_non_mall,
)

SEED_EFFECTIVE_FROM = date(2026, 5, 23)
SEED_VERSION = "shopee-non-mall-2026-05-23"
#: Fixed-fee rate when neither a category nor a name hint is known (median of the seed).
DEFAULT_FIXED_FEE_RATE = Decimal("0.105")

SOURCE_DB = "platform_fee_formulas"
SOURCE_SEED_CATEGORY = "seed_category"
SOURCE_SEED_NAME_HINT = "seed_name_hint"
SOURCE_DEFAULT = "default_assumed"


@dataclass(frozen=True)
class CategoryRate:
    path: tuple[str, ...]
    rate: Decimal


# Contract 10a. Paths are L1 > L2 > L3 as Seller Centre prints them.
_HOME = "Nhà cửa & Đời sống"
_KITCHEN = (_HOME, "Dụng cụ nhà bếp")
_CARE = (_HOME, "Dụng cụ chăm sóc nhà cửa")
SEED_CATEGORIES: tuple[CategoryRate, ...] = (
    CategoryRate((*_KITCHEN, "Tạp dề & găng tay nấu nướng"), Decimal("0.15")),
    CategoryRate((*_CARE, "Túi nilon & túi rác"), Decimal("0.10")),
    CategoryRate((*_CARE, "Phụ kiện giặt là"), Decimal("0.105")),
    CategoryRate((*_CARE, "Chất tẩy rửa"), Decimal("0.105")),
    CategoryRate((*_CARE, "Miếng bọt biển, miếng chà vệ sinh"), Decimal("0.10")),
    CategoryRate((*_KITCHEN, "Giấy bạc / Màng bọc thực phẩm"), Decimal("0.16")),
)

#: Product-name hints for items whose category is not stored yet (contract 10a "likely" rows).
#: Matched on the accent-stripped lower-case name; first hit wins.
NAME_HINTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("gang tay",), SEED_CATEGORIES[0].path),
    (("tui rac", "tui bio", "tu huy sinh hoc"), SEED_CATEGORIES[1].path),
    (("vien giat", "hae"), SEED_CATEGORIES[2].path),
    (("nuoc rua chen", "nuoc tay", "tay dau mo", "nuoc lau"), SEED_CATEGORIES[3].path),
    (("xo muop", "mieng cha", "bot bien"), SEED_CATEGORIES[4].path),
    (("mang nhom", "giay bac", "mang boc"), SEED_CATEGORIES[5].path),
)


def fold(text: str) -> str:
    """Lower-case, accent-stripped, for matching Vietnamese names and categories."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


@dataclass(frozen=True)
class RateChoice:
    rate: Decimal
    source: str
    category: tuple[str, ...] | None = None


def _path_key(path: Sequence[str]) -> tuple[str, ...]:
    return tuple(fold(p) for p in path)


_SEED_BY_PATH: dict[tuple[str, ...], Decimal] = {_path_key(c.path): c.rate for c in SEED_CATEGORIES}


def choose_fixed_fee_rate(
    category_path: Sequence[str] | None,
    name: str | None,
    *,
    default: Decimal = DEFAULT_FIXED_FEE_RATE,
) -> RateChoice:
    """The phí cố định rate for an item: category path first (longest match), then a name hint,
    then the shop default (flagged)."""
    if category_path:
        key = _path_key(category_path)
        for end in range(len(key), 0, -1):
            hit = _SEED_BY_PATH.get(key[:end])
            if hit is not None:
                return RateChoice(hit, SOURCE_SEED_CATEGORY, tuple(category_path[:end]))
    if name:
        folded = fold(name)
        for words, path in NAME_HINTS:
            if any(re.search(rf"\b{re.escape(w)}", folded) for w in words):
                return RateChoice(_SEED_BY_PATH[_path_key(path)], SOURCE_SEED_NAME_HINT, path)
    return RateChoice(default, SOURCE_DEFAULT, None)


def seed_schedule(rate: Decimal) -> FeeSchedule:
    return FeeSchedule((shopee_vn_non_mall(rate, SEED_EFFECTIVE_FROM),))


def formula_from_components(
    effective_from: date, components: Sequence[Mapping[str, Any]]
) -> FeeFormula:
    """A ``platform_fee_formulas.components`` list -> :class:`FeeFormula`."""
    built: list[FeeComponent] = []
    for c in components:
        kind = FeeKind(c["kind"])
        built.append(
            FeeComponent(
                code=str(c["code"]),
                kind=kind,
                base=FeeBase(c.get("base", FeeBase.BUYER_PAID.value)),
                rate=Decimal(str(c["rate"])) if c.get("rate") is not None else None,
                amount=Decimal(str(c["amount"])) if c.get("amount") is not None else None,
                cap=Decimal(str(c["cap"])) if c.get("cap") is not None else None,
            )
        )
    return FeeFormula(effective_from, tuple(built))


@dataclass(frozen=True)
class FormulaRow:
    """One ``platform_fee_formulas`` row, detached from the ORM."""

    category_path: tuple[str, ...]
    effective_from: date
    components: tuple[Mapping[str, Any], ...]


def schedule_from_rows(
    rows: Sequence[FormulaRow], category_path: Sequence[str] | None
) -> FeeSchedule | None:
    """The versions of the longest-matching category (``[]`` = platform default); None if no
    row applies."""
    key = _path_key(category_path or ())
    best: tuple[int, list[FormulaRow]] | None = None
    for end in range(len(key), -1, -1):
        match = [r for r in rows if _path_key(r.category_path) == key[:end]]
        if match:
            best = (end, match)
            break
    if best is None:
        return None
    versions = {
        r.effective_from: formula_from_components(r.effective_from, r.components) for r in best[1]
    }
    return FeeSchedule(tuple(versions.values()))
