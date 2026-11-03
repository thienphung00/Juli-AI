"""Candidate generators, one per card family (contract 12), driven by the Phân tích list.

``generate(env, critical)`` walks the critical items (``shopee_analytics.critical``); for each,
the kinds contract 8 allows for its metric are tried (``kinds.WIRING``), plus an opportunity
pass for the families no critical metric asks for (sale, gift, add-on, affiliate target, ads
add-product). A generator returns a :class:`Candidate` with initial inputs already fitted to
the floors (it shrinks a discount until no SKU is below its operating floor) or ``None``.
It reads the environment only; nothing is persisted.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from decimal import ROUND_CEILING, Decimal
from typing import Any

from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import (
    campaign_profile,
    current_commission_pct,
    evaluate,
)
from juli_backend.services.shopee_recommendations.kinds import KINDS, allowed_for_metric
from juli_backend.services.shopee_recommendations.model import Candidate

TOP_PRODUCTS_FOR_FLOW_ITEMS = 3
Gen = Callable[[RecoEnv, dict[str, Any] | None, str], list[Candidate]]


def _ceil_to(value: Decimal, step: int) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _gap(crit: dict[str, Any] | None) -> float | None:
    if not crit or crit.get("deviation_pct") is None:
        return None
    return max(-float(crit["deviation_pct"]), 0.0)


def _shop_aov(env: RecoEnv) -> Decimal:
    orders = len({ln.order_id for ln, _ in env.view.pairs})
    gmv = sum((ln.order_value for ln, _ in env.view.pairs), ZERO)
    return gmv / orders if orders else ZERO


def _mk(
    kind: str,
    item: str | None,
    inputs: dict[str, Any],
    crit: dict[str, Any] | None,
    reason: str,
    wiring: str | None,
    **kw: Any,
) -> Candidate:
    return Candidate(
        kind=kind,
        items=(item,) if item else (),
        inputs=inputs,
        critical=None
        if crit is None
        else {
            k: crit.get(k)
            for k in (
                "id",
                "kind",
                "kpi",
                "level",
                "flow",
                "at_stake_per_day",
                "at_stake_per_month",
                "deviation_pct",
                "money_basis",
            )
        },
        reason=reason,
        wiring_key=wiring,
        gap_pct=_gap(crit),
        **kw,
    )


def _clean(env: RecoEnv, cand: Candidate) -> bool:
    """True when the candidate evaluates and has no operating-floor breach (a generator never
    proposes a change that breaks a floor)."""
    ev = evaluate(env, cand)
    return ev.refusal is None and not ev.breaches


# -------------------------------------------------------------------------- promotion


def _max_discount_pct(env: RecoEnv, item: str) -> float | None:
    caps = [f.max_discount_pct for f in env.floors(item).values() if f.max_discount_pct is not None]
    return None if not caps else float(min(caps))


def _current_discount_pct(env: RecoEnv, item: str) -> int:
    """How far below list the item already sells (percent, whole, the shallowest SKU)."""
    out = []
    for sku in env.skus_of(item):
        cur, listed = env.current_price(sku), env.list_price(sku)
        if cur and listed and listed > 0:
            out.append(max(int((listed - cur) / listed * 100), 0))
    return min(out) if out else 0


def gen_product_discount(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    """CTOR low: a discount a few points deeper than today's, inside the floor."""
    cap = _max_discount_pct(env, item)
    now = _current_discount_pct(env, item)
    top = now + config.DISCOUNT_TRY_PCT[-1]
    start = min(top, int(cap)) if cap is not None else now + config.DISCOUNT_TRY_PCT[0]
    for d in range(start, now + 2, -1):
        cand = _mk(
            "product_discount",
            item,
            {"discount_pct": d},
            crit,
            f"CTOR của sản phẩm thấp: giảm {d}% so với giá niêm yết (hiện {now}%), trong giới hạn giá sàn.",  # noqa: E501
            "ctor",
        )
        ev = evaluate(env, cand)
        if ev.refusal:
            return []
        if not ev.breaches:
            return [cand]
    return []


def gen_price(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    """Margin under target / a SKU under its floor: raise the price to the floor (+ 2 %)."""
    need = Decimal(0)
    for sku in env.skus_of(item):
        cur, fl = env.current_price(sku), env.floor_price(item, sku)
        if cur and fl and cur < fl:
            need = max(need, fl * Decimal("1.02") / cur * 100)
    if need == 0:
        need = Decimal(105)
    pct = int(min(need.to_integral_value(rounding=ROUND_CEILING), Decimal(130)))
    cand = _mk(
        "price",
        item,
        {"new_price_pct": pct},
        crit,
        f"Biên dưới mục tiêu / giá khách trả dưới giá sàn: nâng giá lên {pct}% giá hiện tại.",
        "bien",
    )
    ev = evaluate(env, cand)
    return [] if ev.refusal else [cand]


# ---------------------------------------------------------------------------- voucher


def _qty(env: RecoEnv, item: str | None, days: int, per_day_orders: Decimal) -> int:
    q = max(int(math.ceil(float(per_day_orders) * days * 1.5)), 10)
    stock = env.stock(item) if item else None
    if stock is not None and stock > 0:
        q = min(q, max(int(stock * config.STOCK_SHARE_CAP), 1))
    return q


def gen_min_spend_voucher(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    aov = _shop_aov(env)
    if aov <= 0:
        return []
    min_spend = _ceil_to(aov * Decimal("1.25"), config.VOUCHER_MIN_SPEND_STEP)
    per_day = Decimal(env.orders_of(item)) / env.window_days
    for share in (Decimal("0.05"), Decimal("0.04"), Decimal("0.03"), Decimal("0.02")):
        value = int(_ceil_to(min_spend * share, 1000))
        cand = _mk(
            "min_spend_voucher",
            item,
            {
                "value": value,
                "min_spend": int(min_spend),
                "quantity": _qty(env, item, config.VOUCHER_DAYS, per_day),
                "days": config.VOUCHER_DAYS,
            },
            crit,
            f"AOV thấp: voucher {value:,}đ cho đơn từ {int(min_spend):,}đ.".replace(",", "."),
            "aov",
        )
        if _clean(env, cand):
            return [cand]
    return []


def gen_review_voucher(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    aov = _shop_aov(env)
    if aov <= 0:
        return []
    value = int(max(_ceil_to(aov * Decimal("0.02"), 1000), Decimal(1000)))
    per_day = Decimal(env.orders_of(item)) / env.window_days
    cand = _mk(
        "review_voucher",
        item,
        {
            "value": value,
            "min_spend": 0,
            "quantity": _qty(env, item, config.VOUCHER_DAYS, per_day),
            "days": config.VOUCHER_DAYS,
        },
        crit,
        f"CTOR thấp: voucher tri ân nhỏ {value:,}đ.".replace(",", "."),
        "ctor",
    )
    return [cand] if _clean(env, cand) else []


def gen_voucher_cap(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    """Margin under target: lower the value of the shop's live fixed-value voucher by 20 %."""
    live = [v for v in env.vouchers if v.value and v.value > 0]
    if not live:
        return []
    v = max(live, key=lambda x: x.value or ZERO)
    new_value = int(
        max(((v.value or ZERO) * Decimal("0.8") / 1000).to_integral_value() * 1000, Decimal(1000))
    )
    base = {
        "value": int(v.value or 0),
        "min_spend": int(v.min_spend or 0),
        "max_value": None if v.max_value is None else int(v.max_value),
        "quantity": v.usage_limit,
        "voucher_id": v.voucher_id,
    }
    if new_value >= int(v.value or 0):
        return []
    cand = _mk(
        "voucher_cap",
        None,
        {
            "value": new_value,
            "min_spend": base["min_spend"],
            "quantity": v.usage_limit or 100,
            "days": config.VOUCHER_DAYS,
            "baseline": base,
        },
        crit,
        f"Biên dưới mục tiêu: giảm voucher từ {base['value']:,}đ xuống {new_value:,}đ.".replace(
            ",", "."
        ),
        "bien",
    )
    return [cand] if evaluate(env, cand).refusal is None else []


# ------------------------------------------------------------------------------ combo


def gen_bundle_deal(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    for t2, t3 in ((5, 8), (4, 6), (3, 5), (2, 3)):
        cand = _mk(
            "bundle_deal",
            item,
            {"tier2_pct": t2, "tier3_pct": t3},
            crit,
            f"AOV thấp: combo mua 2 giảm {t2}%, mua 3 giảm {t3}%.",
            "aov",
        )
        if _clean(env, cand):
            return [cand]
    return []


def gen_variation_set(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    for pct in (5, 4, 3):
        cand = _mk(
            "variation_set",
            item,
            {"set_size": 2, "set_discount_pct": pct},
            crit,
            f"AOV thấp: bán thêm bộ 2 món giảm {pct}%.",
            "aov",
        )
        if _clean(env, cand):
            return [cand]
    return []


def gen_add_on(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    """The add-on is the cheapest in-stock product of the shop with the best margin."""
    main_price = max((env.current_price(s) or ZERO for s in env.skus_of(item)), default=ZERO)
    best: tuple[Decimal, str] | None = None
    for other, pp in env.view.profit.products.items():
        if other == item or pp.margin_rate is None or env.stock(other) == 0:
            continue
        price = max((env.current_price(s) or ZERO for s in env.skus_of(other)), default=ZERO)
        if price <= 0 or (main_price and price > main_price * Decimal("0.6")):
            continue
        if best is None or pp.margin_rate > best[0]:
            best = (pp.margin_rate, other)
    if best is None:
        return []
    for off in (10, 8, 5):
        cand = _mk(
            "add_on",
            item,
            {"addon_discount_pct": off},
            crit,
            f"AOV thấp: mua kèm deal sốc, giảm {off}% cho món mua kèm.",
            "aov",
            extra={"addon_item": best[1]},
        )
        if _clean(env, cand):
            return [cand]
    return []


def gen_gift(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    cheapest: tuple[Decimal, str] | None = None
    for other in env.item_ids():
        if other == item:
            continue
        for sku in env.skus_of(other):
            c = env.costs.get(sku)
            if c and c.cogs is not None and (cheapest is None or c.cogs < cheapest[0]):
                cheapest = (c.cogs, other)
    if cheapest is None:
        return []
    aov = _shop_aov(env)
    if aov <= 0:
        return []
    cand = _mk(
        "gift",
        item,
        {"min_spend": int(_ceil_to(aov * Decimal("1.3"), 10_000))},
        crit,
        "CTOR thấp: tặng quà nhỏ cho đơn từ mức tối thiểu.",
        "ctor",
        extra={"gift_item": cheapest[1]},
    )
    return [cand] if evaluate(env, cand).refusal is None else []


# ------------------------------------------------------------------------------- sale


def _sale(kind: str, env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    cap = _max_discount_pct(env, item)
    if cap is None or cap < 5:
        return []
    stock = env.stock(item)
    units = 20 if stock is None else max(min(int(stock * config.STOCK_SHARE_CAP), 200), 0)
    if units <= 0:
        return []
    for d in range(min(int(cap), 25 if kind == "flash_sale" else 20), 4, -1):
        cand = _mk(
            kind,
            item,
            {"discount_pct": d, "units": units, "slot_days": 1},
            crit,
            f"Sản phẩm bán ổn, còn dư giá sàn: {d}% trong "
            + ("khung Flash Sale của shop." if kind == "flash_sale" else "chương trình Shopee."),
            "sale",
        )
        if _clean(env, cand):
            return [cand]
    return []


def gen_flash_sale(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    return _sale("flash_sale", env, crit, item)


def gen_program_registration(
    env: RecoEnv, crit: dict[str, Any] | None, item: str
) -> list[Candidate]:
    return _sale("program_registration", env, crit, item)


# ---------------------------------------------------------------------------- affiliate


def gen_affiliate_commission(
    env: RecoEnv, crit: dict[str, Any] | None, item: str
) -> list[Candidate]:
    cur = current_commission_pct(env, item)
    new = Decimal(8) if cur is None else min(cur + 2, Decimal(30))
    new = new.quantize(Decimal("0.5"))
    for pct in (new, new - 1, new - 2):
        if pct <= 0:
            continue
        cand = _mk(
            "affiliate_commission",
            item,
            {"commission_pct": float(pct)},
            crit,
            f"Lượt xem từ liên kết thấp: hoa hồng chiến dịch mở {pct}%.",
            "lien_ket" if crit and crit.get("cause", {}).get("stage") == "lien_ket" else "views",
        )
        ev = evaluate(env, cand)
        if ev.refusal is None and not ev.breaches:
            return [cand]
    return []


def gen_affiliate_target(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    partners = sorted(env.view.data.affiliate.partners, key=lambda p: -p.gmv)[:3]
    if not partners:
        return []
    cur = current_commission_pct(env, item)
    pct = float((cur or Decimal(8)) + 3)
    cand = _mk(
        "affiliate_target_campaign",
        item,
        {"commission_pct": pct},
        crit,
        "Chiến dịch liên kết chỉ định cho các nhà sáng tạo đang bán tốt.",
        "lien_ket",
        extra={"partners": [p.key for p in partners]},
    )
    ev = evaluate(env, cand)
    return [] if ev.refusal or ev.breaches else [cand]


# -------------------------------------------------------------------------------- ads


def _campaign_of(env: RecoEnv, item: str) -> str | None:
    for c in env.view.ads.campaigns:
        if item in c.products:
            return c.key
    return None


def _round1(x: Decimal) -> float:
    return float((x * 10).to_integral_value(rounding=ROUND_CEILING) / 10)


def gen_ads_for_roas(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    """ROAS under break-even (the item's campaign): raise the target, remove the product, or
    pause a campaign that loses badly."""
    key = _campaign_of(env, item)
    prof = campaign_profile(env, key) if key else None
    if prof is None:
        return []
    out: list[Candidate] = []
    alloc = prof["alloc"]
    be = prof["break_even_roas"]
    roas = prof["roas_direct"]
    setting = env.setting_for(key)
    if be is not None and roas is not None and roas < be:
        new_target = _round1(be * Decimal(str(config.ROAS_TARGET_MARGIN)))
        before = setting.roas_target if setting else None
        if before is None or Decimal(str(new_target)) > before:
            out.append(
                _mk(
                    "ads_roas_target",
                    None,
                    {"roas_target": new_target},
                    crit,
                    f"ROAS trực tiếp {roas:.2f} dưới điểm hoà vốn {be:.2f}: nâng ROAS mục tiêu lên {new_target}.",  # noqa: E501
                    "roas",
                    campaign_key=key,
                    extra={"magnitude_pct": 10.0} if before is None else {},
                )
            )
        if len(alloc.products) > 1:
            out.append(
                _mk(
                    "ads_remove_product",
                    item,
                    {},
                    crit,
                    "Sản phẩm này kéo ROAS của chiến dịch nhóm xuống dưới hoà vốn: gỡ khỏi nhóm.",
                    "roas",
                    campaign_key=key,
                )
            )
        if roas < be * Decimal("0.5"):
            out.append(
                _mk(
                    "ads_pause",
                    None,
                    {},
                    crit,
                    "ROAS trực tiếp chưa bằng một nửa điểm hoà vốn: tạm dừng chiến dịch.",
                    "bien",
                    campaign_key=key,
                )
            )
    if key and (setting is None or setting.purpose is None):
        out.append(
            _mk(
                "ads_purpose",
                None,
                {"purpose": "chuyen_doi"},
                crit,
                "Chiến dịch chưa có mục đích: đặt 'Chuyển đổi' để đánh giá theo ROAS.",
                "roas",
                campaign_key=key,
            )
        )
    return out


def gen_ads_budget(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    """Views low and the item's campaign earns above break-even: raise the daily budget 20 %."""
    key = _campaign_of(env, item)
    prof = campaign_profile(env, key) if key else None
    if prof is None or prof["break_even_roas"] is None or prof["roas_direct"] is None:
        return []
    if prof["roas_direct"] < prof["break_even_roas"] * Decimal("1.2"):
        return []
    setting = env.setting_for(key)
    base = setting.daily_budget if setting and setting.daily_budget else prof["spend_per_day"]
    new = int(_ceil_to(base * (1 + Decimal(config.ADS_BUDGET_STEP_PCT) / 100), 1000))
    return [
        _mk(
            "ads_budget",
            None,
            {"daily_budget": new},
            crit,
            f"Lượt xem thấp và ROAS trực tiếp trên hoà vốn: tăng ngân sách ngày lên {new:,}đ.".replace(  # noqa: E501
                ",", "."
            ),
            "views",
            campaign_key=key,
        )
    ]


def gen_ads_add_product(env: RecoEnv, crit: dict[str, Any] | None, item: str) -> list[Candidate]:
    pp = env.product(item)
    if pp is None or pp.margin_rate is None or _campaign_of(env, item) is not None:
        return []
    target = env.margin_target_rate
    if target is not None and pp.margin_rate < target:
        return []
    best = None
    for c in env.view.ads.campaigns:
        prof = campaign_profile(env, c.key)
        if (
            prof
            and prof["break_even_roas"]
            and prof["roas_direct"]
            and prof["roas_direct"] >= prof["break_even_roas"] * Decimal("1.2")
            and len(c.products) >= 1
        ):
            best = c.key
            break
    if best is None:
        return []
    return [
        _mk(
            "ads_add_product",
            item,
            {},
            crit,
            "Sản phẩm có biên tốt chưa chạy quảng cáo: thêm vào chiến dịch nhóm đang có lãi.",
            "views",
            campaign_key=best,
        )
    ]


# ------------------------------------------------------------------------- dispatcher

#: kind -> (generator, needs a product)
GENERATORS: dict[str, tuple[Gen | Callable[..., list[Candidate]], bool]] = {
    "product_discount": (gen_product_discount, True),
    "price": (gen_price, True),
    "min_spend_voucher": (gen_min_spend_voucher, True),
    "review_voucher": (gen_review_voucher, True),
    "voucher_cap": (gen_voucher_cap, False),
    "bundle_deal": (gen_bundle_deal, True),
    "variation_set": (gen_variation_set, True),
    "add_on": (gen_add_on, True),
    "gift": (gen_gift, True),
    "flash_sale": (gen_flash_sale, True),
    "program_registration": (gen_program_registration, True),
    "affiliate_commission": (gen_affiliate_commission, True),
    "affiliate_target_campaign": (gen_affiliate_target, True),
    "ads_budget": (gen_ads_budget, True),
    "ads_roas_target": (gen_ads_for_roas, True),
    "ads_pause": (gen_ads_for_roas, True),
    "ads_remove_product": (gen_ads_for_roas, True),
    "ads_purpose": (gen_ads_for_roas, True),
    "ads_add_product": (gen_ads_add_product, True),
}


def _key(c: Candidate) -> tuple[Any, ...]:
    return (c.kind, c.items, c.campaign_key)


def generate(env: RecoEnv, critical: dict[str, Any]) -> list[Candidate]:
    """All candidates for the shop, deduplicated by (kind, product, campaign)."""
    out: dict[tuple[Any, ...], Candidate] = {}
    ranked_items = [i for i in env.item_ids() if env.orders_of(i) >= config.MIN_PRODUCT_ORDERS]
    top = ranked_items[:TOP_PRODUCTS_FOR_FLOW_ITEMS]

    def add(cands: list[Candidate], only: set[str] | None = None) -> None:
        ads_ok = only is not None and any(k.startswith("ads_") for k in only)
        for c in cands:
            if (
                only is not None
                and c.kind not in only
                and not (ads_ok and c.kind.startswith("ads_"))
            ):
                continue
            if c.item and (env.locked.get(c.item) or env.stock(c.item) == 0):
                continue
            out.setdefault(_key(c), c)

    for crit in critical.get("items", []):
        stage = (crit.get("cause") or {}).get("stage") or crit.get("kpi")
        wanted = {k for k in crit.get("change_kinds", []) if k in KINDS}
        wanted |= {k for k in allowed_for_metric(stage) if k in KINDS} if not wanted else set()
        if not wanted:
            continue
        pid = crit.get("product_id")
        products = [pid] if pid else top
        for item in products:
            if item is None or env.orders_of(item) < config.MIN_PRODUCT_ORDERS:
                continue
            ran: set[Callable[..., Any]] = set()
            for kind in sorted(wanted):
                gen, needs_item = GENERATORS[kind]
                if gen in ran:
                    continue  # one ads generator emits several kinds
                ran.add(gen)
                if needs_item or item:
                    add(gen(env, crit, item) if needs_item else gen(env, crit, item), wanted)
    # opportunity pass: families no critical metric asks for
    for n, item in enumerate(ranked_items[:5]):
        add(
            gen_flash_sale(env, None, item)
            if n == 0
            else gen_program_registration(env, None, item)
            if n == 1
            else []
        )
        add(gen_ads_add_product(env, None, item))
        add(gen_affiliate_target(env, None, item))
    return list(out.values())
