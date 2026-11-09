"""Generate the combo options (multi-pack of one product, bundles of several), count them first.

Rules against exploding combinations: one variation inside a multi-pack (default), only
variations sold in the last 30 days (default), at most ``Rules.max_options``.
Mixed-variation packs (rule off) are multisets: C(v + n - 1, n) per size, which is why the rule
is on by default. Pure; ordering is deterministic (products, then sizes, then variations as given).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from itertools import combinations_with_replacement, islice, product
from math import comb, prod

from juli_backend.services.shopee_builder.combo_options import config, naming
from juli_backend.services.shopee_builder.combo_options.models import (
    BundleSpec,
    ComboOption,
    Member,
    OptionCount,
    Packs,
    ProductIn,
    Rules,
    VariationIn,
)


class ComboInputError(ValueError):
    """A pack size or bundle the builder cannot take."""


def _check_packs(packs: Packs) -> None:
    for n in packs.sizes:
        if not config.MIN_PACK <= n <= config.MAX_PACK:
            raise ComboInputError(f"pack size {n} outside {config.MIN_PACK}..{config.MAX_PACK}")
    for spec in packs.bundles:
        if len(spec.quantities) < 2:
            raise ComboInputError("a bundle needs at least two products")
        if any(q < 1 or q > config.MAX_PACK for _, q in spec.quantities):
            raise ComboInputError(f"bundle quantity outside 1..{config.MAX_PACK}")


def _allowed(
    products: Sequence[ProductIn], picks: Mapping[str, Sequence[str]], rules: Rules
) -> dict[str, list[VariationIn]]:
    out: dict[str, list[VariationIn]] = {}
    for p in products:
        chosen = set(picks.get(p.item_id) or ())
        if not chosen:
            continue
        out[p.item_id] = [
            v
            for v in p.variations
            if v.variation_id in chosen and (v.sold_30d or not rules.sold_only)
        ]
    return out


def count(
    products: Sequence[ProductIn],
    picks: Mapping[str, Sequence[str]],
    packs: Packs,
    rules: Rules,
) -> OptionCount:
    """How many options ``generate`` would build, BEFORE building any."""
    _check_packs(packs)
    allowed = _allowed(products, picks, rules)
    multi = 0
    for vs in allowed.values():
        for n in dict.fromkeys(packs.sizes):
            multi += len(vs) if rules.same_variation else (comb(len(vs) + n - 1, n) if vs else 0)
    bundles = sum(
        prod(len(allowed.get(item, ())) for item, _ in spec.quantities) for spec in packs.bundles
    )
    total = multi + bundles
    kept = min(total, max(rules.max_options, 0))
    return OptionCount(
        total=total,
        kept=kept,
        over_cap=total - kept,
        by_form={"multi_pack": multi, "bundle": bundles},
    )


def _member(p: ProductIn, v: VariationIn, qty: int) -> Member:
    return Member(
        item_id=p.item_id,
        product_name=p.name,
        variation_id=v.variation_id,
        variation_name=v.name,
        quantity=qty,
        unit_price=v.selling_price,
        cost=v.cost,
        stock=v.stock,
        item_code=naming.slug(p.code or p.item_id) or "ITEM",
        var_code=naming.slug(v.sku or v.variation_id) or "DEF",
    )


def _multi_pack(
    p: ProductIn, vs: Sequence[VariationIn], packs: Packs, rules: Rules
) -> Iterator[tuple[str, tuple[Member, ...]]]:
    for n in dict.fromkeys(packs.sizes):
        if rules.same_variation:
            for v in vs:
                yield "multi_pack", (_member(p, v, n),)
        elif vs:
            for combo in combinations_with_replacement(vs, n):
                counted = Counter(v.variation_id for v in combo)
                first = {v.variation_id: v for v in combo}
                yield (
                    "multi_pack",
                    tuple(_member(p, first[vid], q) for vid, q in counted.items()),
                )


def _bundle(
    spec: BundleSpec, by_item: Mapping[str, ProductIn], allowed: Mapping[str, Sequence[VariationIn]]
) -> Iterator[tuple[str, tuple[Member, ...]]]:
    if any(item not in by_item for item, _ in spec.quantities):
        return
    pools = [allowed.get(item, ()) for item, _ in spec.quantities]
    for combo in product(*pools):
        yield (
            "bundle",
            tuple(
                _member(by_item[item], v, q)
                for (item, q), v in zip(spec.quantities, combo, strict=True)
            ),
        )


def _iter(
    products: Sequence[ProductIn],
    allowed: Mapping[str, Sequence[VariationIn]],
    packs: Packs,
    rules: Rules,
) -> Iterator[tuple[str, tuple[Member, ...]]]:
    by_item = {p.item_id: p for p in products}
    for p in products:
        if p.item_id in allowed:
            yield from _multi_pack(p, allowed[p.item_id], packs, rules)
    for spec in packs.bundles:
        yield from _bundle(spec, by_item, allowed)


def generate(
    products: Sequence[ProductIn],
    picks: Mapping[str, Sequence[str]],
    packs: Packs,
    rules: Rules,
) -> list[ComboOption]:
    """The options, at most ``rules.max_options`` (see :func:`count` for the full number)."""
    _check_packs(packs)
    allowed = _allowed(products, picks, rules)
    out: list[ComboOption] = []
    taken: set[str] = set()
    for form, members in islice(_iter(products, allowed, packs, rules), max(rules.max_options, 0)):
        label = (
            naming.bundle_name(members)
            if form == "bundle"
            else naming.multi_pack_name(members, rules.unit)
        )
        short = naming.option_name(label)
        i = 1
        while short in taken:  # two long names cut to the same text
            i += 1
            tail = f" {i}"
            short = naming.fit(label, config.SHOPEE_MAX_OPTION_NAME_CHARS - len(tail)) + tail
        taken.add(short)
        out.append(
            ComboOption(
                key=f"{form}:"
                + "|".join(f"{m.item_id}/{m.variation_id}x{m.quantity}" for m in members),
                form="bundle" if form == "bundle" else "multi_pack",
                members=members,
                units=sum(m.quantity for m in members),
                name=naming.full_name(label),
                option_name=short,
                sku=naming.make_sku(rules.shop_code, members, form == "bundle"),
                suggested_stock=naming.suggested_stock(members),
            )
        )
    return out


def limit_warnings(options: Sequence[ComboOption]) -> list[str]:
    """Warnings against the per-listing limits (UNCONFIRMED, see ``config``); never blocks."""
    warns: list[str] = []
    if len(options) > config.SHOPEE_MAX_TOTAL_VARIATIONS:
        warns.append(
            f"{len(options)} phân loại, vượt giới hạn {config.SHOPEE_MAX_TOTAL_VARIATIONS} "
            "mỗi sản phẩm (chưa xác nhận)"
        )
    groups = {o.members[0].variation_name for o in options if o.form == "multi_pack"}
    if len(groups) > config.SHOPEE_MAX_OPTIONS_PER_GROUP:
        warns.append(
            f"{len(groups)} lựa chọn trong một nhóm, vượt {config.SHOPEE_MAX_OPTIONS_PER_GROUP} "
            "(chưa xác nhận)"
        )
    return warns
