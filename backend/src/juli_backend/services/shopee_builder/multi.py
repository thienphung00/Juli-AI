"""P97 D85.13: the target list of a version (one card, many targets).

Kinds Shopee applies as ONE setting to many things take a target list: giảm giá % and hoa hồng
affiliate over products, ngân sách / ROAS over campaigns (``sum`` mode: every target is its own
change and the card is their sum) and a voucher over a product list (``joint`` mode: one voucher,
so the total is the joint evaluation and the rows are what the voucher would do on each product
alone). ``expand`` turns such a version into one ordinary single-target version per target; the
estimate machinery (``translate``, ``manual.build_variant``, ``outcome``) never learns the
difference except through ``recommendations.targets``.
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext

SUM = "sum"
JOINT = "joint"


def mode(spec: sp.VersionSpec) -> str | None:
    """``sum`` / ``joint`` when the version names several targets, else ``None``."""
    if isinstance(spec, sp.ProductDiscountSpec | sp.AffiliateSpec) and spec.targets:
        return SUM
    if isinstance(spec, sp.AdsSpec) and spec.campaign_keys:
        return SUM
    if isinstance(spec, sp.VoucherSpec) and spec.scope == "product" and len(spec.item_ids) > 1:
        return JOINT
    return None


def target_kind(spec: sp.VersionSpec) -> str:
    return "campaign" if isinstance(spec, sp.AdsSpec) else "item"


def target_ids(spec: sp.VersionSpec) -> list[str]:
    if isinstance(spec, sp.ProductDiscountSpec | sp.AffiliateSpec):
        return list(spec.targets)
    if isinstance(spec, sp.AdsSpec):
        return list(spec.campaign_keys)
    if isinstance(spec, sp.VoucherSpec):
        return list(spec.item_ids)
    return []


def target_name(ctx: BuilderContext, spec: sp.VersionSpec, target: str) -> str:
    if isinstance(spec, sp.AdsSpec):
        for alloc in ctx.env.view.ads.campaigns:
            if alloc.key == target:
                return alloc.name
        setting = ctx.env.setting_for(target)
        return setting.name if setting is not None else target
    return ctx.env.name(target)


def _uniform_rows(ctx: BuilderContext, item: str, pct: float) -> list[sp.VariationPrice]:
    """The variations a uniform % reaches: those that sold in the window (the evaluators price a
    variation from its newest order line), else every variation of the listing."""
    rows = ctx.rows(item)
    sold = set(ctx.env.skus_of(item))
    chosen = [r for r in rows if r.get("sku_key") in sold] or rows
    return [
        sp.VariationPrice(variation_id=r["variation_id"], discount_pct=pct) for r in chosen
    ] or [sp.VariationPrice(variation_id="", discount_pct=pct)]


def expand(spec: sp.VersionSpec, ctx: BuilderContext) -> list[tuple[str, sp.VersionSpec]]:
    """One single-target version per target, in the order the person ticked them."""
    out: list[tuple[str, sp.VersionSpec]] = []
    for target in target_ids(spec):
        single: sp.VersionSpec
        if isinstance(spec, sp.ProductDiscountSpec):
            assert spec.discount_pct is not None
            single = spec.model_copy(
                update={
                    "targets": [],
                    "item_id": target,
                    "discount_pct": None,
                    "variations": _uniform_rows(ctx, target, spec.discount_pct),
                }
            )
        elif isinstance(spec, sp.AffiliateSpec):
            single = spec.model_copy(update={"targets": [], "item_id": target})
        elif isinstance(spec, sp.AdsSpec):
            single = spec.model_copy(update={"campaign_keys": [], "campaign_key": target})
        elif isinstance(spec, sp.VoucherSpec):
            single = spec.model_copy(update={"item_ids": [target]})
        else:  # pragma: no cover - mode() is None for every other kind
            continue
        out.append((target, single))
    return out


def totals_row(card_row: dict[str, Any], breaches: list[dict[str, Any]]) -> dict[str, Any]:
    """A target's line as the card shows it: figures P50 + range, its floor breaches."""
    return {**card_row, "breaches": breaches, "breach": bool(breaches)}


__all__ = ["JOINT", "SUM", "expand", "mode", "target_ids", "target_kind", "target_name"]
