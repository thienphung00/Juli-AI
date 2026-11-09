"""Price the options by one rule; margin and profit through the existing fee / cost functions.

Rules (``PriceRule.kind``):

- ``ladder`` (default): buying separately = sum of member selling price x quantity; the combo takes
  the ladder discount of the largest tier <= the option's boxes (below the first tier: none).
- ``target_margin``: the lowest price whose margin (``variations.unit_margin``: the shop's fee
  schedule, giá vốn, đóng gói, VAT) reaches ``target_margin_pct``; rounded UP so the margin is not
  lost to rounding. No giá vốn on a member -> no price ("chưa tính"), the seller may type one.
- ``per_box``: ``box_price`` x boxes.

Rounding: to the nearest ``round_to`` (default 1.000đ, never below it). ``ending_9`` instead uses
the nearest price ending in 9.000 (k x 10.000 - 1.000, e.g. 129.000). Target margin rounds up.

A manual price overrides a row (``reprice``): everything but the price is recomputed. Costs: a
combo is one order: giá vốn is the sum of members' giá vốn x quantity; đóng gói is the largest
member's (one parcel); VAT flags come from the first member. A member with no giá vốn makes margin
and profit "chưa tính" -- the 1/3-of-price fallback is never used. A price below the margin floor
only flags; it never blocks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from juli_backend.services.shopee_builder.combo_options import config
from juli_backend.services.shopee_builder.combo_options.models import (
    ComboOption,
    Economics,
    PricedRow,
    PriceRule,
)
from juli_backend.services.shopee_builder.variations import unit_margin
from juli_backend.services.shopee_recommendations.unit_cost import UnitCost

ZERO = Decimal(0)
HUNDRED = Decimal(100)


class PriceRuleError(ValueError):
    """A rule missing its number."""


def round_price(
    x: Decimal, step: int = config.DEFAULT_ROUND_TO, *, ending_9: bool = False, up: bool = False
) -> Decimal:
    mode = ROUND_CEILING if up else ROUND_HALF_UP
    s = Decimal(step)
    if ending_9:
        period = s * 10
        k = max(((x + s) / period).to_integral_value(mode), Decimal(1))
        return k * period - s
    return max((x / s).to_integral_value(mode), Decimal(1)) * s


def separate_total(option: ComboOption) -> Decimal | None:
    if any(m.unit_price is None for m in option.members):
        return None
    return sum(((m.unit_price or ZERO) * m.quantity for m in option.members), ZERO)


def ladder_discount(ladder: Mapping[int, Decimal], units: int) -> Decimal:
    tiers = [t for t in ladder if t <= units]
    return Decimal(str(ladder[max(tiers)])) if tiers else ZERO


def _combined_cost(option: ComboOption) -> UnitCost | None:
    """One order's cost of the whole option; ``None`` when any member has no giá vốn."""
    parts: list[tuple[UnitCost, int]] = []
    for m in option.members:
        if m.cost is None or m.cost.cogs is None:
            return None
        parts.append((m.cost, m.quantity))
    first = parts[0][0]
    return UnitCost(
        cogs=sum(((c.cogs or ZERO) * q for c, q in parts), ZERO),
        packaging=max((c.packaging or ZERO for c, _ in parts), default=ZERO),
        pack_count=option.units,
        pack_source="set",
        bom=False,
        vat=first.vat,
    )


def _margin(
    option: ComboOption, price: Decimal, eco: Economics
) -> tuple[Decimal | None, Decimal | None]:
    """(margin as a fraction, profit per order) at ``price``; (None, None) = chưa tính."""
    cost = _combined_cost(option)
    if cost is None:
        return None, None
    rate, profit, _ = unit_margin(
        option.members[0].item_id, option.sku, cost, price, price, eco.schedule, eco.on
    )
    return rate, profit


def _solve_target(option: ComboOption, target_pct: Decimal, eco: Economics) -> Decimal | None:
    """Lowest price reaching the target margin (bisection: margin only grows with price)."""
    cost = _combined_cost(option)
    if cost is None or not ZERO < target_pct < HUNDRED:
        return None
    goal = target_pct / HUNDRED
    lo, hi = Decimal(1), (cost.cogs or ZERO) * 20 + Decimal(1_000_000)
    rate, _ = _margin(option, hi, eco)
    if rate is None or rate < goal:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        r, _ = _margin(option, mid, eco)
        if r is not None and r >= goal:
            hi = mid
        else:
            lo = mid
    return hi


def _row(
    option: ComboOption,
    price: Decimal | None,
    eco: Economics,
    floor: Decimal | None,
    *,
    overridden: bool,
    basis: str,
    notes: Sequence[str] = (),
) -> PricedRow:
    sep = separate_total(option)
    margin = profit = None
    if price is not None:
        margin, profit = _margin(option, price, eco)
    saving = sep - price if sep is not None and price is not None else None
    margin_pct = (
        (margin * HUNDRED).quantize(Decimal("0.1"), ROUND_HALF_UP) if margin is not None else None
    )
    below = None if margin_pct is None or floor is None else margin_pct < floor
    return PricedRow(
        option=option,
        price=price,
        price_per_box=(price / option.units).quantize(Decimal(1), ROUND_HALF_UP)
        if price is not None
        else None,
        separate_total=sep,
        saving=saving,
        saving_pct=(saving / sep * HUNDRED).quantize(Decimal("0.1"), ROUND_HALF_UP)
        if saving is not None and sep
        else None,
        margin_pct=margin_pct,
        profit_per_order=profit.quantize(Decimal(1), ROUND_HALF_UP) if profit is not None else None,
        margin_label=None if margin_pct is not None else config.NOT_COUNTED,
        below_floor=below,
        overridden=overridden,
        basis=basis,
        notes=tuple(notes),
    )


def _rule_price(option: ComboOption, rule: PriceRule, eco: Economics) -> tuple[Decimal | None, str]:
    step, nine = rule.round_to, rule.ending_9
    if rule.kind == "ladder":
        sep = separate_total(option)
        disc = ladder_discount(rule.ladder, option.units)
        basis = f"giảm {(disc * HUNDRED).normalize():f} % so với mua lẻ"
        if sep is None:
            return None, basis
        return round_price(sep * (1 - disc), step, ending_9=nine), basis
    if rule.kind == "per_box":
        if rule.box_price is None:
            raise PriceRuleError("per_box needs box_price")
        return round_price(
            rule.box_price * option.units, step, ending_9=nine
        ), "giá cố định mỗi hộp"
    if rule.target_margin_pct is None:
        raise PriceRuleError("target_margin needs target_margin_pct")
    basis = f"biên mục tiêu {rule.target_margin_pct.normalize():f} %"
    raw = _solve_target(option, rule.target_margin_pct, eco)
    return (None if raw is None else round_price(raw, step, ending_9=nine, up=True)), basis


def price(
    options: Sequence[ComboOption],
    rule: PriceRule,
    economics: Economics,
    floor: Decimal | None = None,
    overrides: Mapping[str, Decimal | int] | None = None,
) -> list[PricedRow]:
    """One row per option. ``floor`` = margin floor in percent points (warns, never blocks);
    ``overrides`` = option key -> manual price (that row is recomputed around it)."""
    rows: list[PricedRow] = []
    for opt in options:
        if overrides and opt.key in overrides:
            rows.append(reprice_option(opt, Decimal(overrides[opt.key]), economics, floor))
            continue
        px, basis = _rule_price(opt, rule, economics)
        notes = (
            ()
            if px is not None
            else ("không tính được giá theo quy tắc: thiếu giá vốn hoặc giá bán",)
        )
        rows.append(_row(opt, px, economics, floor, overridden=False, basis=basis, notes=notes))
    return rows


def reprice_option(
    option: ComboOption, new_price: Decimal, economics: Economics, floor: Decimal | None = None
) -> PricedRow:
    return _row(option, new_price, economics, floor, overridden=True, basis="giá nhập tay")


def reprice(
    row: PricedRow, new_price: Decimal | int, economics: Economics, floor: Decimal | None = None
) -> PricedRow:
    """A manual price on one row: saving, margin, profit and the floor flag are recalculated."""
    return reprice_option(row.option, Decimal(new_price), economics, floor)
