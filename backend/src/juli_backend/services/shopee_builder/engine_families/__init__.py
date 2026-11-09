"""P98 W2-F: the per-family translation from a builder version to the funnel engine's
``OptionInput`` (ADR-122 d.6-d.10). ``option_for(spec, ctx, extras)`` is the dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from juli_backend.services.shopee_builder import multi, translate
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext
from juli_backend.services.shopee_builder.engine.contract import OptionInput
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.engine_families.common import FamilyRefused, scaled
from juli_backend.services.shopee_builder.engine_families.facts import (
    AdsFacts,
    AdsNewCampaign,
    AffiliatePlan,
    KolFacts,
    NewComboListing,
    PackEvidence,
    SimpleFacts,
)
from juli_backend.services.shopee_builder.engine_families.families import (
    ads_option,
    affiliate_option,
    combo_option,
    listing_combo_option,
    new_listing_option,
    price_option,
    simple_option,
    voucher_option,
)
from juli_backend.services.shopee_recommendations.model import Candidate

#: The builder hides Ads edits (budget, ROAS, pause, keywords, add / remove product): ADR-122 d.10.
HIDDEN_SPEC_KINDS = ("ads",)
_SIMPLE_KINDS = (
    "title",
    "cover_image",
    "price_display",
    "description_first_line",
    "listing_hide",
    "listing_relist",
    "add_on",
    "variation_set",
    "gift",
)


@dataclass(frozen=True)
class FamilyExtras:
    """Data the BuilderContext does not carry yet; wave 3 loads them once per request."""

    pack: PackEvidence | None = None  # listing_combo: the matching pack variation, measured
    ads: AdsFacts | None = None  # ads new campaign: past campaigns + the product's on / off days
    kol: KolFacts | None = None  # affiliate: KOL rows, before / after, sample unit cost
    contribution_rate: Decimal | None = None  # FunnelBase.contribution_rate (price AOV term)
    profit_per_order: Decimal | None = None  # the FunnelBase's profit ÷ orders (switching)


def _magnitude(spec: sp.VersionSpec) -> float | None:
    """Percent size of a price change (positive = cheaper), for the lift model."""
    if isinstance(spec, sp.ProductDiscountSpec):
        if spec.discount_pct is not None:
            return float(spec.discount_pct)
        pcts = [v.discount_pct for v in spec.variations if v.discount_pct is not None]
        return float(sum(pcts) / len(pcts)) if pcts else None
    if isinstance(spec, sp.PriceSpec):
        pcts = [v.change_pct for v in spec.variations if v.change_pct is not None]
        return -float(sum(pcts) / len(pcts)) if pcts else None
    if isinstance(spec, sp.FlashSaleSpec):
        pcts = [v.discount_pct for v in spec.variations if v.discount_pct is not None]
        return float(sum(pcts) / len(pcts)) if pcts else None
    return None


def _rebased(
    option: OptionInput, line_ppo: Decimal | None, base_ppo: Decimal | None
) -> OptionInput:
    """An option's profit per order after, stated on the order lines, moved onto the funnel's
    profit per order (the engine compares it with the base's): the same per-order change."""
    after = option.profit_per_order_after
    if after is None or line_ppo is None or base_ppo is None:
        return option
    return replace(option, profit_per_order_after=base_ppo + after - line_ppo)


def option_for(
    spec: sp.VersionSpec | AdsNewCampaign | AffiliatePlan | NewComboListing,
    ctx: BuilderContext,
    extras: FamilyExtras | None = None,
) -> OptionInput:
    """The one entry. Raises :class:`FamilyRefused` (``hidden`` for the Ads edit kinds)."""
    ex = extras or FamilyExtras()
    env = ctx.env
    if isinstance(spec, AdsNewCampaign):
        return ads_option(spec, ex.ads or AdsFacts())
    if isinstance(spec, AffiliatePlan):
        return affiliate_option(spec, ex.kol or KolFacts())
    if isinstance(spec, NewComboListing):
        return new_listing_option(
            spec, adapters.new_listing_facts(spec, env, ex.pack, ex.profit_per_order)
        )
    if spec.kind in HIDDEN_SPEC_KINDS:
        raise FamilyRefused("hidden", "Chỉnh sửa chiến dịch quảng cáo đang chạy đã được ẩn.")
    if isinstance(spec, sp.AffiliateSpec):
        raise FamilyRefused("affiliate_needs_kol", "Chọn KOL từ bảng KOL để ước tính.")
    # one voucher over a product list is ONE offer on their orders (joint); a sum-mode list is
    # evaluated per target by the caller (``multi.expand``)
    if multi.mode(spec) == multi.SUM:
        raise FamilyRefused("multi_target", "Đánh giá từng sản phẩm riêng.")
    if isinstance(spec, sp.VoucherSpec):
        vf = adapters.voucher_facts(spec, env)
        return _rebased(voucher_option(spec, vf), vf.profit_per_order, ex.profit_per_order)
    if isinstance(spec, sp.ComboSpec):
        return combo_option(spec, adapters.combo_facts(spec, env))
    if isinstance(spec, sp.ListingComboSpec):
        return listing_combo_option(spec, adapters.listing_combo_facts(spec, env, ex.pack))
    items = sp.items_of(spec)
    if isinstance(spec, sp.PriceSpec | sp.ProductDiscountSpec | sp.FlashSaleSpec):
        tr = translate.to_variant(spec, ctx)
        v = tr.variant
        cand = Candidate(
            kind=v["change_kind"],
            items=tuple(v["items"]),
            inputs=dict(v["inputs"]),
            extra=dict(v.get("extra") or {}),
        )
        from juli_backend.services.shopee_recommendations.evaluate import evaluate

        ev = evaluate(env, cand)
        if ev.refusal:
            raise FamilyRefused(ev.refusal)
        lines = env.lines_for(items)
        values = adapters.order_values(lines)
        aov = sum(values.values(), adapters.ZERO) / len(values) if values else None
        ctor = adapters.lift_evidence(spec.kind, items, env, _magnitude(spec))
        facts = adapters.price_facts_from_evaluation(
            ev,
            aov_now=aov,
            contribution_rate=ex.contribution_rate,
            ctor=ctor,
        )
        if (
            ex.profit_per_order is not None
            and facts.profit_per_order is not None
            and facts.profit_per_order_after is not None
        ):
            # the evaluator's per-order change on the funnel's own profit per order: the engine
            # applies ``profit_per_order_after`` against the base's (ShopMetrics) profit per order
            facts = replace(
                facts,
                profit_per_order_after=ex.profit_per_order
                + facts.profit_per_order_after
                - facts.profit_per_order,
            )
        return price_option(spec, facts)
    if spec.kind in _SIMPLE_KINDS:
        lead = adapters.lift_evidence(spec.kind, items, env)
        if isinstance(spec, sp.GiftSpec) and spec.trigger.type == "min_spend":
            # a gift on a minimum spend converts only the buyers whose basket qualifies
            q = adapters.qualifying_share(env, Decimal(spec.trigger.amount or 0))
            lead = replace(lead, band=scaled(lead.band, q))
        return simple_option(spec, SimpleFacts(lead))
    raise FamilyRefused("kind_not_supported")


__all__ = [
    "HIDDEN_SPEC_KINDS",
    "FamilyExtras",
    "FamilyRefused",
    "NewComboListing",
    "option_for",
]
