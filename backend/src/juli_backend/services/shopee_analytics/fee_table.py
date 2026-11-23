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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.fees import (
    INFRASTRUCTURE_FEE,
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


SERVICE_FEE_CODE = "phi_dich_vu"
#: Fewest income rows a shop's phí dịch vụ rate is learned from, and the share of them that
#: must carry the fee for the shop to count as enrolled (Voucher / Freeship Xtra).
SERVICE_MIN_ROWS = 5
SERVICE_ENROLLED_SHARE = Decimal("0.5")


def learn_service_rate(
    rows: Iterable[tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]],
) -> Decimal | None:
    """F4: the shop's phí dịch vụ rate (Voucher / Freeship Xtra) learned from income-file rows
    ``(product price, Phí Dịch Vụ, phí hạ tầng, Voucher Xtra)``. A row's service part is its
    Voucher Xtra when the file states it, else Phí Dịch Vụ minus the infrastructure fee (the
    stated one, else the 3.000đ the formula has as its own component), never below 0. The rate is
    the parts' total / the prices' total over the rows that carry one. None = the shop is not
    enrolled (too few rows, or under half of them carry the fee)."""
    parts: list[tuple[Decimal, Decimal]] = []
    for price, service, infra, xtra in rows:
        if price is None or price <= 0:
            continue
        if xtra is not None:
            part = xtra
        elif service is not None:
            part = max(service - (infra if infra is not None else INFRASTRUCTURE_FEE), Decimal(0))
        else:
            continue
        parts.append((price, part))
    if len(parts) < SERVICE_MIN_ROWS:
        return None
    charged = [(p, f) for p, f in parts if f > 0]
    if Decimal(len(charged)) / Decimal(len(parts)) < SERVICE_ENROLLED_SHARE:
        return None
    rate = sum((f for _, f in charged), Decimal(0)) / sum((p for p, _ in charged), Decimal(0))
    rate = rate.quantize(Decimal("0.0001"))
    return rate if Decimal(0) < rate < 1 else None


SERVICE_LEARN_DAYS = 90


def _service_part(
    service: Decimal | None, infra: Decimal | None, xtra: Decimal | None
) -> Decimal | None:
    if xtra is not None:
        return xtra
    if service is None:
        return None
    return max(service - (infra if infra is not None else INFRASTRUCTURE_FEE), Decimal(0))


def learn_service_rate_recent(
    rows: Iterable[
        tuple[date | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None]
    ],
) -> Decimal | None:
    """F4: :func:`learn_service_rate` over the income rows ``(paid day, price, Phí Dịch Vụ, infra,
    Xtra)`` since the shop's first row that carries the fee, or the newest 90 days, whichever is
    shorter, so rows from before it joined the programme never dilute the rate."""
    dated = [r for r in rows if r[0] is not None]
    if not dated:
        return None
    newest = max(r[0] for r in dated if r[0] is not None)
    carrying = [
        r[0]
        for r in dated
        if r[0] is not None and (_service_part(r[2], r[3], r[4]) or Decimal(0)) > 0
    ]
    if not carrying:
        return None
    start = max(min(carrying), newest - timedelta(days=SERVICE_LEARN_DAYS))
    return learn_service_rate(
        (price, service, infra, xtra)
        for day, price, service, infra, xtra in dated
        if day is not None and day >= start
    )


def with_service_fee(schedule: FeeSchedule, rate: Decimal | None) -> FeeSchedule:
    """``schedule`` with the phí dịch vụ component added to every version (on the order value
    after discounts); unchanged when the shop is not enrolled or a version already has it."""
    if rate is None:
        return schedule
    service = FeeComponent(
        SERVICE_FEE_CODE, FeeKind.PCT, FeeBase.ITEM_AFTER_SELLER_PROMO, rate=rate
    )
    return FeeSchedule(
        tuple(
            v
            if any(c.code == SERVICE_FEE_CODE for c in v.components)
            else FeeFormula(v.effective_from, (*v.components, service))
            for v in schedule.versions
        )
    )


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
