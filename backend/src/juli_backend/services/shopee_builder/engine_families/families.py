"""One function per family: a builder version (+ the facts it needs) -> ``OptionInput``
(ADR-122 d.6-d.10). Drivers and sources follow the ADR's tables exactly; only drivers change, and
each option's own costs go to ``offers`` / ``fixed_cost`` / ``profit_per_order_after``.

Every function is pure: ``facts`` carry the shop's numbers (see ``facts.py``); ``adapters.py``
builds them from the recommendation environment.
"""

from __future__ import annotations

import math
from decimal import Decimal

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import (
    ALL_SOURCES,
    CARD_SOURCES,
    AddedTraffic,
    Band,
    Basis,
    Driver,
    DriverEffect,
    OfferCost,
    OptionInput,
    Source,
)
from juli_backend.services.shopee_builder.engine_families import common, measure
from juli_backend.services.shopee_builder.engine_families.common import (
    FamilyRefused,
    band3,
    clamp01,
    point,
    scaled,
)
from juli_backend.services.shopee_builder.engine_families.facts import (
    AdsFacts,
    AdsNewCampaign,
    AffiliatePlan,
    AffiliateRateFacts,
    ComboFacts,
    KolFacts,
    ListingComboFacts,
    NewComboListing,
    PriceFacts,
    SimpleFacts,
    VoucherFacts,
)

ZERO = Decimal(0)
ONE = Decimal(1)
DEFAULT_HORIZON_DAYS = 30
NOT_ESTIMABLE_TEXT = "chưa ước tính được"


def _label(spec: sp.VersionSpec, fallback: str) -> str:
    return spec.label or getattr(spec, "name", None) or fallback


def _weakest_basis(bases: list[Basis]) -> Basis:
    order: tuple[Basis, ...] = ("measured", "product_history", "shop", "prior", "not_estimable")
    return max(bases, key=order.index)


def _rel(delta: Decimal, base: Decimal | None) -> Decimal:
    return ZERO if not base else delta / base


# -- voucher (d.6) -------------------------------------------------------------------------------

_VOUCHER_SOURCES: dict[str, tuple[Source, ...]] = {
    "shop": ALL_SOURCES,
    "product": ALL_SOURCES,
    "follower": ALL_SOURCES,
    "livestream": ("live",),
}


def voucher_option(spec: sp.VoucherSpec, facts: VoucherFacts) -> OptionInput:
    sources = _VOUCHER_SOURCES[spec.scope]
    reducing = facts.baseline_per_use is not None and facts.per_use < facts.baseline_per_use
    drivers: list[DriverEffect] = []
    notes: list[str] = []
    ppo_after: Decimal | None = None
    use_lo = use_mid = use_hi = facts.qualifying_share * facts.usage_rate
    if reducing:
        drivers.append(
            DriverEffect(
                "ctor", sources, "prior", lift=Band(Decimal("-0.03"), Decimal("-0.01"), ZERO)
            )
        )
        if facts.profit_per_order is not None and facts.baseline_per_use is not None:
            saving = facts.baseline_per_use - facts.per_use
            ppo_after = facts.profit_per_order + saving * use_mid
    elif spec.min_spend > 0:
        # E2: the orders that reach the minimum, measured from the order lines (those within 20 %
        # below it today) -- the 0 / 20 / 50 % prior only when there are too few orders
        if facts.reach is not None:
            moving: tuple[Decimal, ...] = (facts.reach.p10, facts.reach.p50, facts.reach.p90)
            gaps = tuple(m * facts.reach_gap for m in moving)
            reach_basis: Basis = "measured"
        else:
            # the prior moves a share of the same near orders (never baskets far below)
            moving = tuple(r * facts.near_share for r in common.REACH)
            gaps = tuple(m * facts.reach_gap for m in moving)
            reach_basis = "prior"
        if facts.aov_now:
            lift = Band(*(g / facts.aov_now for g in gaps))
            drivers.append(DriverEffect("aov", sources, reach_basis, lift=lift))
        else:
            notes.append("Chưa có đơn để tính giá trị đơn tăng lên.")
        if facts.qualifying_share + facts.near_share > 0:
            # the visible discount converts only buyers whose basket can reach the minimum
            drivers.append(
                DriverEffect("ctor", sources, "prior", lift=band3(common.CTOR_VISIBLE_OFFER))
            )
        elif not drivers:
            drivers.append(DriverEffect("aov", sources, "prior", lift=point(ZERO)))
        use_lo, use_mid, use_hi = (
            clamp01((facts.qualifying_share + m) * facts.usage_rate) for m in moving
        )
    else:  # tri ân / đánh giá: no minimum, the visible discount converts more clicks
        drivers.append(
            DriverEffect("ctor", sources, "prior", lift=band3(common.CTOR_VISIBLE_OFFER))
        )
    if spec.scope == "follower":
        notes.append(common.NOTE_FOLLOWER)
    if spec.scope == "livestream":
        notes.append("Voucher livestream chỉ tác động nguồn Live.")
    kind = "min_spend_voucher" if spec.min_spend > 0 else "review_voucher"
    return OptionInput(
        kind=kind,
        label=_label(spec, "Voucher"),
        drivers=tuple(drivers),
        duration_days=spec.days,
        offers=(
            OfferCost(
                facts.per_use,
                Band(use_lo, use_mid, use_hi),
                None if spec.usage_limit is None else Decimal(spec.usage_limit),
                "voucher",
            ),
        ),
        profit_per_order_after=ppo_after,
        note=" ".join(notes) or None,
    )


# -- combo khuyến mãi and new combo listing (d.7) ------------------------------------------------


def combo_option(spec: sp.ComboSpec, facts: ComboFacts) -> OptionInput:
    """E2: orders within 20 % (at least one unit) under the tier reach it, measured from the
    order lines. P100-C (B.10): with too few orders to measure that reach the option is cost and
    break-even only ("chưa ước tính được") -- the buyers who already qualify get the discount
    (its cost); no prior reach ("ước tính chung") is ever passed off as an estimate. The cost
    per use is the discount net of the % fees it saves (J: fees are on the post-combo total)."""
    label = _label(spec, spec.name or "Combo khuyến mãi")
    per_use = facts.per_use * (ONE - facts.fee_rate)
    if facts.reach is None or not facts.aov_now:
        now = facts.use_share_now
        return OptionInput(
            kind="bundle_deal",
            label=label,
            drivers=(
                DriverEffect("aov", ALL_SOURCES, "not_estimable", note=common.NOTE_COMBO_REACH),
            ),
            duration_days=spec.days,
            offers=(OfferCost(per_use, point(now), None, "giảm giá combo"),),
        )
    moving = (facts.reach.p10, facts.reach.p50, facts.reach.p90)
    units = facts.reach_units
    aov = Band(*(m * units * facts.unit_price / facts.aov_now for m in moving))
    use = Band(*(clamp01(facts.use_share_now + m) for m in moving))
    return OptionInput(
        kind="bundle_deal",
        label=label,
        drivers=(
            DriverEffect("aov", ALL_SOURCES, "measured", lift=aov),
            DriverEffect("ctor", ALL_SOURCES, "prior", lift=band3(common.CTOR_VISIBLE_OFFER)),
        ),
        duration_days=spec.days,
        offers=(OfferCost(per_use, use, None, "giảm giá combo"),),
    )


def listing_combo_option(spec: sp.ListingComboSpec, facts: ListingComboFacts) -> OptionInput:
    return _listing_combo(_label(spec, spec.title), facts)


def new_listing_option(row: NewComboListing, facts: ListingComboFacts) -> OptionInput:
    """A combo builder row (multi-pack or bundle) as a new combo listing (ADR-122 d.7, E3)."""
    return _listing_combo(row.label, facts)


def _listing_combo(label: str, facts: ListingComboFacts) -> OptionInput:
    """Orders already holding those quantities switch (AOV / lợi nhuận mỗi đơn change, Δ Đơn 0);
    extra orders only for a pack size the shop does not sell today, from the matching
    variation's measured rates (E3); no pack evidence -> Δ Đơn "+0 · chưa có dữ liệu cho quy cách
    này" beside the switching effect, and with no switching basket either the option is "chưa ước
    tính được" (P99: never an all-+0 estimate)."""
    drivers: list[DriverEffect] = []
    note: str | None = None
    if facts.aov_now:
        # a combo not cheaper than what those buyers pay today gives them no reason to switch
        gap = min(ZERO, facts.new_price - facts.value_now)
        delta = facts.switch_share * gap
        drivers.append(
            DriverEffect("aov", ALL_SOURCES, "measured", lift=point(_rel(delta, facts.aov_now)))
        )
    pack = facts.pack
    if facts.pack_sold_today:
        # E3: a pack size the shop already sells: its buyers switch, no extra orders
        note = common.NOTE_PACK_SOLD
    elif pack is not None and pack.window_days > 0:
        views = pack.views * Decimal(DEFAULT_HORIZON_DAYS) / Decimal(pack.window_days)
        drivers.append(
            DriverEffect(
                "views",
                CARD_SOURCES,
                "measured",
                added=AddedTraffic(
                    point(views), pack.ctr, pack.ctor, pack.aov, point(ONE), pack.profit_per_order
                ),
            )
        )
    else:
        note = common.NOTE_NO_PACK_EVIDENCE
        if not facts.switch_share or not facts.aov_now:
            # P99: no pack evidence and no basket that would switch: nothing is measured, so the
            # option is "chưa ước tính được" (never a +0 passed off as an estimate)
            drivers = [
                DriverEffect(
                    "views",
                    CARD_SOURCES,
                    "not_estimable",
                    note=f"{NOT_ESTIMABLE_TEXT} — {common.NOTE_NO_PACK_EVIDENCE}",
                )
            ]
            note = None  # the driver's note says it once
    if not drivers:
        drivers.append(DriverEffect("aov", ALL_SOURCES, "not_estimable", note=note))
    return OptionInput(
        kind="listing_combo",
        label=label,
        drivers=tuple(drivers),
        duration_days=None,
        profit_per_order_after=facts.profit_per_order_after,
        note=note,
    )


# -- price family, listing, basket, gift (d.10) --------------------------------------------------


def _price_days(spec: sp.VersionSpec) -> int | None:
    if isinstance(spec, sp.FlashSaleSpec):
        return max(1, math.ceil(spec.slot_hours / common.HOURS_PER_DAY))
    if isinstance(spec, sp.ProductDiscountSpec):
        return spec.days
    return None


def price_option(
    spec: sp.PriceSpec | sp.ProductDiscountSpec | sp.FlashSaleSpec, facts: PriceFacts
) -> OptionInput:
    """CTOR (the orders response, product history > shop > prior) + AOV (the price factor is
    certain arithmetic). ``profit_per_order_after`` carries the price effect on profit; the engine
    then moves GMV only through the AOV driver, so the price effect counts once."""
    aov_lift = facts.price_factor - ONE
    ppo_after = facts.profit_per_order_after
    offers: tuple[OfferCost, ...] = ()
    cost = facts.discount_per_order
    if spec.kind == "product_discount" and cost is not None and cost > 0:
        # P100 wave 2 (B.14): the discount is a cost inside the OptionResult, like the combo's --
        # given on every order after the change (today's buyers included, they get it too). It
        # leaves the per-order profit so it counts once; ROI and break-even read it.
        offers = (OfferCost(cost, point(ONE), None, "giảm giá chương trình"),)
        if ppo_after is not None:
            ppo_after = ppo_after + cost
    kind = {"price": "price", "product_discount": "product_discount", "flash_sale": "flash_sale"}[
        spec.kind
    ]
    return OptionInput(
        kind=kind,
        label=_label(
            spec,
            {"price": "Đổi giá", "product_discount": "Chương Trình Của Shop"}.get(
                spec.kind, "Flash Sale"
            ),
        ),
        drivers=(
            DriverEffect("ctor", ALL_SOURCES, facts.ctor.basis, lift=facts.ctor.band),
            DriverEffect("aov", ALL_SOURCES, "measured", lift=point(aov_lift)),
        ),
        duration_days=_price_days(spec),
        offers=offers,
        profit_per_order_after=ppo_after,
    )


#: kind -> (change_kind, label, lead driver + sources, co-driver + sources, aov kind?)
_Lever = tuple[Driver, tuple[Source, ...]]
_SIMPLE: dict[str, tuple[str, str, _Lever, _Lever | None]] = {
    "title": ("title", "Tiêu đề", ("views", CARD_SOURCES), ("ctr", CARD_SOURCES)),
    "cover_image": ("cover_image", "Ảnh bìa", ("ctr", CARD_SOURCES), None),
    "price_display": ("price_display", "Hiển thị giá", ("ctr", CARD_SOURCES), None),
    "description_first_line": (
        "description_first_line",
        "Dòng đầu mô tả",
        ("ctor", ALL_SOURCES),
        None,
    ),
    "listing_hide": ("listing_hide", "Ẩn sản phẩm", ("views", ALL_SOURCES), None),
    "listing_relist": ("listing_relist", "Đăng lại sản phẩm", ("views", ALL_SOURCES), None),
    "add_on": ("add_on", "Deal Sốc · Mua Kèm Deal Sốc", ("aov", ALL_SOURCES), None),
    "variation_set": (
        "variation_set",
        "Bộ / quy cách nhiều món",
        ("aov", ALL_SOURCES),
        ("ctor", ALL_SOURCES),
    ),
    "gift": ("gift", "Deal Sốc · Mua Để Nhận Quà", ("ctor", ALL_SOURCES), None),
}


def simple_option(spec: sp.VersionSpec, facts: SimpleFacts) -> OptionInput:
    """Title / keywords (views + CTR on Thẻ sản phẩm), cover / price display (CTR), description
    first line (CTOR), hide / relist (views), basket (AOV, + CTOR for a variation set), gift
    (CTOR). Evidence for the lead driver comes in ``facts``; a second driver takes
    ``CO_DRIVER_SHARE`` of it, tagged "prior"."""
    try:
        change_kind, label, lead, co = _SIMPLE[spec.kind]
    except KeyError:
        raise FamilyRefused("kind_not_supported") from None
    drivers: list[DriverEffect] = []
    lead_metric = lead[0]
    if spec.kind == "listing_hide":
        # hiding a listing takes away all of its views: the loss is its own last 30 days
        drivers.append(DriverEffect("views", lead[1], "product_history", lift=point(-ONE)))
    elif lead_metric == "aov" and facts.aov is not None:
        drivers.append(DriverEffect("aov", lead[1], "measured", lift=facts.aov))
    else:
        drivers.append(DriverEffect(lead_metric, lead[1], facts.lead.basis, lift=facts.lead.band))
    if co is not None:
        drivers.append(
            DriverEffect(
                co[0],
                co[1],
                "prior",
                lift=scaled(facts.lead.band, common.CO_DRIVER_SHARE),
            )
        )
    return OptionInput(
        kind=change_kind,
        label=_label(spec, label),
        drivers=tuple(drivers),
        duration_days=getattr(spec, "days", None) if spec.kind in ("add_on", "gift") else None,
        offers=facts.offers,
        profit_per_order_after=facts.profit_per_order_after,
    )


# -- ads, new campaign (d.8) ---------------------------------------------------------------------


def ads_option(setup: AdsNewCampaign, facts: AdsFacts) -> OptionInput:
    """Driver ``views`` on the ad share of Thẻ sản phẩm: spend ÷ the measured CPM; CTR / CTOR /
    AOV of the ad traffic; the extra share measured on the product's organic orders on days with
    vs without ads. Anything unmeasured -> ``not_estimable`` with the exact cost (never a prior)."""
    days = setup.days
    budget = setup.daily_budget * days
    notes: list[str] = []
    spend = budget
    if setup.roas_target is not None:
        util = measure.spend_utilisation(facts.campaigns, setup.roas_target)
        if util is None:
            notes.append(
                "Chưa có lịch sử ở ROAS mục tiêu tương tự: chi phí tính theo ngân sách tối đa."
            )
        else:
            spend = budget * util
    rates = measure.ad_rates(facts.campaigns, setup.item_ids, setup.ad_type)
    share = measure.on_off_extra_share(facts.days)
    label = setup.label or "Quảng cáo Hiển thị Sản phẩm"
    complete = (
        rates is not None
        and rates.ctr is not None
        and rates.ctor is not None
        and rates.aov is not None
        and share is not None
    )
    if not complete or rates is None or share is None:
        # cost and break-even only; the ad's own rates (when known) still give the break-even
        # profit per order
        added = None
        if rates is not None and rates.ctr and rates.ctor and rates.aov:
            added = AddedTraffic(
                point(ZERO), rates.ctr, rates.ctor, rates.aov, point(ZERO), facts.profit_per_order
            )
        return OptionInput(
            kind="ads_new_campaign",
            label=label,
            drivers=(
                DriverEffect(
                    "views",
                    CARD_SOURCES,
                    "not_estimable",
                    added=added,
                    note=common.NOTE_ADS_NOT_ESTIMABLE,
                ),
            ),
            duration_days=days,
            fixed_cost=spend,
            note=" ".join(notes) or None,
        )
    assert rates.ctr is not None and rates.ctor is not None and rates.aov is not None
    views = Band(
        spend / rates.cpm_high * 1000, spend / rates.cpm_mid * 1000, spend / rates.cpm_low * 1000
    )
    basis: Basis = "measured"
    if rates.scope != "product":
        notes.append("Tỉ lệ quảng cáo lấy từ các chiến dịch cùng loại của shop.")
    return OptionInput(
        kind="ads_new_campaign",
        label=label,
        drivers=(
            DriverEffect(
                "views",
                CARD_SOURCES,
                basis,
                added=AddedTraffic(
                    views, rates.ctr, rates.ctor, rates.aov, share, facts.profit_per_order
                ),
            ),
        ),
        duration_days=days,
        fixed_cost=spend,
        note=" ".join(notes) or None,
    )


# -- affiliate / KOL (d.9) -----------------------------------------------------------------------


def affiliate_option(plan: AffiliatePlan, facts: KolFacts) -> OptionInput:
    """Per chosen KOL × product the KOL's own views / CTR / CTOR / AOV on ``lien_ket`` (summed
    into one added traffic, rates weighted by clicks / orders). Extra share measured only; any
    chosen non-cashback KOL without it makes the option ``not_estimable``. Cost is exact:
    commission % × the KOL's GMV (or the fixed fee) + samples (qty × (giá vốn + đóng gói) +
    shipping). Cashback / coupon affiliates carry extra share 0 and never get samples."""
    days = plan.duration_days or DEFAULT_HORIZON_DAYS
    cost = ZERO
    notes: list[str] = []
    views = clicks = orders = gmv = ZERO
    views_known = True
    extra_orders = ZERO
    unmeasured: list[str] = []
    for kol in plan.kols:
        rates = facts.rates.get(kol.kol_key)
        cashback = measure.is_cashback(kol.handle, facts.extra_cashback_names)
        if cashback:
            notes.append(f"{kol.handle}: {common.CASHBACK_LABEL}.")
        if rates is not None and rates.days > 0:
            k = Decimal(days) / Decimal(rates.days)
            if kol.commission_pct is not None:
                cost += kol.commission_pct / 100 * rates.gmv * k
            if rates.views is None:
                views_known = False
            else:
                views += rates.views * k
            clicks += rates.clicks * k
            orders += rates.orders * k
            gmv += rates.gmv * k
            share = (
                Band(ZERO, ZERO, ZERO)
                if cashback
                else measure.kol_extra_share(facts.before_after.get(kol.kol_key))
            )
            if share is None:
                unmeasured.append(kol.handle)
            else:
                extra_orders += rates.orders * k * share.p50
        else:
            unmeasured.append(kol.handle)
            views_known = False
        cost += kol.fixed_fee
        if kol.sample_qty > 0 and cashback:
            notes.append(f"{kol.handle}: không gửi mẫu cho {common.CASHBACK_LABEL}.")
        elif kol.sample_qty > 0 and kol.sample_item_id is not None:
            unit = facts.sample_unit_cost.get(kol.sample_item_id, ZERO)
            cost += Decimal(kol.sample_qty) * unit + kol.sample_ship_fee
        elif kol.sample_qty > 0:
            unit = sum((facts.sample_unit_cost.get(i, ZERO) for i in kol.item_ids), ZERO) / max(
                1, len(kol.item_ids)
            )
            cost += Decimal(kol.sample_qty) * unit + kol.sample_ship_fee
    label = plan.label or "Gửi mẫu / hoa hồng KOL"
    ctr = None if not views_known or views <= 0 else clicks / views
    ctor = None if clicks <= 0 else orders / clicks
    aov = None if orders <= 0 else gmv / orders
    if unmeasured or ctr is None or ctor is None or aov is None:
        added = None
        if ctr and ctor and aov:
            added = AddedTraffic(point(ZERO), ctr, ctor, aov, point(ZERO), facts.profit_per_order)
        return OptionInput(
            kind="affiliate_sample",
            label=label,
            drivers=(
                DriverEffect(
                    "views",
                    ("lien_ket",),
                    "not_estimable",
                    added=added,
                    note=common.NOTE_KOL_NOT_ESTIMABLE,
                ),
            ),
            duration_days=plan.duration_days,
            fixed_cost=cost,
            note=" ".join(notes) or None,
        )
    own_orders = views * ctr * ctor
    share_mid = clamp01(extra_orders / own_orders) if own_orders > 0 else ZERO
    # spread: the engine draws the share from a band; use the weakest measured KOL spread
    lo_hi = [
        measure.kol_extra_share(facts.before_after.get(k.kol_key))
        for k in plan.kols
        if not measure.is_cashback(k.handle, facts.extra_cashback_names)
    ]
    spread_lo = min((b.p10 / b.p50 if b and b.p50 > 0 else ONE for b in lo_hi), default=ONE)
    spread_hi = max((b.p90 / b.p50 if b and b.p50 > 0 else ONE for b in lo_hi), default=ONE)
    return OptionInput(
        kind="affiliate_sample",
        label=label,
        drivers=(
            DriverEffect(
                "views",
                ("lien_ket",),
                "measured",
                added=AddedTraffic(
                    point(views),
                    ctr,
                    ctor,
                    aov,
                    Band(
                        clamp01(share_mid * spread_lo),
                        share_mid,
                        clamp01(share_mid * spread_hi),
                    ),
                    facts.profit_per_order,
                ),
            ),
        ),
        duration_days=plan.duration_days,
        fixed_cost=cost,
        note=" ".join(notes) or None,
    )


# -- affiliate commission of a product, no KOL chosen (P99, d.9) -------------------------------

NOTE_NO_AFFILIATE_ORDERS = (
    "Chưa có đơn Liên kết trong {days} ngày: hoa hồng chỉ phát sinh khi có đơn."
)


def affiliate_rate_option(spec: sp.AffiliateSpec, facts: AffiliateRateFacts) -> OptionInput:
    """A commission rate on one product (the builder's Liên kết tab). Extra orders are measured
    only (d.9), so the result is cost and break-even only ("chưa ước tính được — đo sau lần gửi
    mẫu đầu"). Cost is exact: commission % × the product's expected Liên kết GMV (its window GMV
    scaled to the 30-day horizon) + the samples (qty × (giá vốn + đóng gói) + shipping)."""
    days = DEFAULT_HORIZON_DAYS
    rate = Decimal(str(spec.commission_pct)) / 100
    gmv = (
        facts.affiliate_gmv * Decimal(days) / Decimal(facts.window_days)
        if facts.window_days > 0
        else ZERO
    )
    cost = rate * gmv + (facts.sample_cost or ZERO)
    notes: list[str] = []
    if facts.affiliate_gmv <= 0:
        notes.append(NOTE_NO_AFFILIATE_ORDERS.format(days=facts.window_days))
    if facts.sample_qty > 0 and facts.sample_cost is None:
        notes.append("Chi phí mẫu chưa tính: thiếu giá vốn.")
    return OptionInput(
        kind="affiliate_target_campaign" if spec.target_campaign else "affiliate_commission",
        label=_label(spec, "Liên kết"),
        drivers=(
            DriverEffect(
                "views", ("lien_ket",), "not_estimable", note=common.NOTE_KOL_NOT_ESTIMABLE
            ),
        ),
        duration_days=None,
        fixed_cost=cost,
        note=" ".join(notes) or None,
    )
