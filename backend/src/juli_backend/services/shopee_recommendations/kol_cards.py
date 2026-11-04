"""KOL cards (P91 D-9, D-11): "Gửi mẫu cho KOL" (``affiliate_sample``) and "Mời KOL"
(``affiliate_invite``).

A card is about ONE creator and ONE product pitched to them. Version 1 is the product with the
best expected profit per sample; the other versions pitch the next best products and, for a
sample card, another sample count. The what-if knobs are the product (``item_id``), the sample
count (``qty``) and the commission rate (``commission_pct``).

EXPECTED ORDERS of a KOL x product pair in a month (empirical-Bayes style, every shrinkage weight
is ``n / (n + K)`` with ``K`` = ``ORDERS_THRESHOLD`` = 10, the same number that makes a pair
"Ít dữ liệu")::

    conv_used = w_kol * conv_kol + (1 - w_kol) * conv_shop      w_kol = n_kol / (n_kol + K)
    product_f = 1 + w_prod * (clip(conv_prod / conv_shop) - 1)  product's affiliate conversion
    channel_f = 1 + w_item * (clip(share_item / share_ch) - 1)  fit of the KOL's channel
    rate_f    = sqrt(new rate / current rate)                   higher rate, more effort
    model     = clicks_30d * conv_used * product_f * channel_f * rate_f * (0.7 if invited)
    mid       = w_pair * pair_orders_30d * rate_f + (1 - w_pair) * model
                                                                w_pair = n_pair / (n_pair + K)

``conv_kol`` / ``n_kol`` / ``clicks_30d`` are the creator's Shopee export (orders,
clicks); a creator with few orders is pulled toward the shop's average conversion. The range is
wide while the pair has fewer than 10 orders: P10 / P90 = ``mid`` x (0.3, 2.2) below 4 orders,
x (0.4, 1.9) below 10, x (0.6, 1.4) from 10 on. The 0.7 invite factor, the clips and the
spreads are priors of this module, labelled "dự kiến"; learning replaces them once cards have
been measured.

Per order the economics are the product's own (``KolPool.products``): net before commission =
contribution + commission of its delivered orders (affiliate orders when it has 3 or more),
commission = rate x the order's ``buyer_paid``. SAMPLE COST = qty x (giá vốn + đóng gói) + phí ship
(the creator's last shipping fee, else the median of the shop's, else 0, labelled).
ROI incl. samples = (net - sample) / (commission + sample); payback orders = sample / net per order.

MEASUREMENT: the KOL x product pair, orders before vs after the send date (``card["kol"]
["measurement"]``; the daily series is ``shopee_analytics.kol.pair_daily``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from juli_backend.services.shopee_analytics.kol import (
    LOW_DATA_LABEL,
    ORDERS_THRESHOLD,
    KolPool,
    KolStat,
    ProductStat,
)
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.kinds import FAMILY_LABELS, spec
from juli_backend.services.shopee_recommendations.model import Candidate, Evaluation, ProfitModel

if TYPE_CHECKING:
    from juli_backend.services.shopee_recommendations.env import RecoEnv

KOL_KINDS: tuple[str, ...] = ("affiliate_sample", "affiliate_invite")
#: A creator invited without a sample converts at this share of the model (prior, not measured).
INVITE_FACTOR = 0.7
#: At most this many KOL cards per generation run (the best by expected profit).
KOL_CARDS_MAX = 8
#: Other products pitched as extra versions of a KOL card.
PRODUCT_ALTERNATIVES = 2
DEFAULT_QTY = 2
DEFAULT_RATE_PCT = 8.0
PRODUCT_FACTOR_CLIP = (0.5, 2.0)
CHANNEL_FACTOR_CLIP = (0.5, 1.5)
#: (below this pair orders, (P10 multiplier, P90 multiplier)); the last row is the "enough" one.
SPREADS: tuple[tuple[int, tuple[float, float]], ...] = (
    (4, (0.3, 2.2)),
    (ORDERS_THRESHOLD, (0.4, 1.9)),
    (10**9, (0.6, 1.4)),
)
Z_P90, Z_P75 = config.Z_P90, config.Z_P75
RATE_STEP = Decimal("0.5")


def weight(n: float, k: int = ORDERS_THRESHOLD) -> float:
    return n / (n + k) if n > 0 else 0.0


def _clip(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])


def spread_for(pair_orders: int) -> tuple[float, float]:
    for limit, spread in SPREADS:
        if pair_orders < limit:
            return spread
    return SPREADS[-1][1]


# ------------------------------------------------------------------------------ forecast


@dataclass(frozen=True)
class SampleCost:
    cost: Decimal
    qty: int
    unit_cogs: Decimal
    unit_packaging: Decimal
    ship_fee: Decimal
    ship_source: str  # "kol" | "shop_median" | "none"
    cogs_source: str  # "real" | "assumed"
    label: str


@dataclass(frozen=True)
class Forecast:
    kol: KolStat
    item_id: str
    product: ProductStat
    invite: bool
    qty: int
    rate_pct: float
    cur_rate_pct: float | None
    shrink: dict[str, float]
    pair_orders: int
    orders_lo: float
    orders_mid: float
    orders_hi: float
    sample: SampleCost | None
    gmv_per_order: float
    commission_per_order: float
    net_per_order: float

    @property
    def low_data(self) -> bool:
        return self.pair_orders < ORDERS_THRESHOLD

    @property
    def sample_cost(self) -> float:
        return 0.0 if self.sample is None else float(self.sample.cost)

    def orders_at(self, q: str) -> float:
        mid = self.orders_mid
        sigma = (self.orders_hi - self.orders_lo) / (2 * Z_P90)
        if q == "p10":
            return self.orders_lo
        if q == "p90":
            return self.orders_hi
        z = {"p25": -Z_P75, "p50": 0.0, "p75": Z_P75}[q]
        return min(max(mid + z * sigma, self.orders_lo), self.orders_hi)

    def at(self, orders: float) -> dict[str, float | None]:
        net = orders * self.net_per_order
        commission = orders * self.commission_per_order
        sample = self.sample_cost
        denominator = commission + sample
        return {
            "orders": orders,
            "gmv": orders * self.gmv_per_order,
            "commission": commission,
            "net_profit": net,
            "profit_after_sample": net - sample,
            "roi_incl_samples": None if denominator <= 0 else (net - sample) / denominator,
        }

    @property
    def payback_orders(self) -> int | None:
        if self.sample_cost <= 0 or self.net_per_order <= 0:
            return None
        return math.ceil(self.sample_cost / self.net_per_order)


def sample_cost_of(pool: KolPool, kol: KolStat, prod: ProductStat, qty: int) -> SampleCost | None:
    unit = prod.unit_cost
    if unit is None:
        return None
    if kol.last_ship_fee is not None:
        ship, src = kol.last_ship_fee, "kol"
    elif pool.default_ship_fee is not None:
        ship, src = pool.default_ship_fee, "shop_median"
    else:
        ship, src = ZERO, "none"
    return SampleCost(
        cost=qty * (unit.cogs + unit.packaging) + ship,
        qty=qty,
        unit_cogs=unit.cogs,
        unit_packaging=unit.packaging,
        ship_fee=ship,
        ship_source=src,
        cogs_source=unit.cogs_source,
        label=unit.label,
    )


def forecast(
    pool: KolPool,
    kol_key: str,
    item_id: str,
    *,
    qty: int,
    rate_pct: float,
    invite: bool,
) -> Forecast | None:
    """The expected month of one KOL x product pair, or ``None`` when a needed fact is missing
    (no export row for the creator, no economics for the product, no cost to price a sample)."""
    kol = pool.kols.get(kol_key)
    prod = pool.products.get(item_id)
    if kol is None or prod is None or kol.clicks_per_30d is None or kol.conv_raw is None:
        return None
    conv_kol = float(kol.conv_raw)
    conv_shop = float(pool.shop_conv) if pool.shop_conv else conv_kol
    n_kol = kol.orders_seen
    w_kol = weight(n_kol)
    conv_used = w_kol * conv_kol + (1 - w_kol) * conv_shop

    w_prod = weight(prod.aff_orders)
    ratio_prod = float(prod.aff_conv) / conv_shop if prod.aff_conv and conv_shop > 0 else 1.0
    product_f = 1 + w_prod * (_clip(ratio_prod, PRODUCT_FACTOR_CLIP) - 1)

    n_item = pool.item_aff_orders.get(item_id, 0)
    w_item = weight(n_item)
    channel_f = 1.0
    if n_item > 0 and pool.aff_orders_total > 0 and pool.channel_orders.get(kol.channel):
        share_item = pool.item_channel_orders.get((item_id, kol.channel), 0) / n_item
        share_all = pool.channel_orders[kol.channel] / pool.aff_orders_total
        channel_f = 1 + w_item * (_clip(share_item / share_all, CHANNEL_FACTOR_CLIP) - 1)

    cur = float(prod.rate) if prod.rate else None
    new = rate_pct / 100
    rate_f = math.sqrt(new / cur) if cur and cur > 0 else 1.0
    invite_f = INVITE_FACTOR if invite else 1.0

    model = float(kol.clicks_per_30d) * conv_used * product_f * channel_f * rate_f * invite_f
    pair = pool.pairs.get((kol_key, item_id))
    n_pair = pair.orders if pair else 0
    w_pair = weight(n_pair)
    pair_30d = n_pair * 30 / max(pool.window_days, 1)
    mid = w_pair * pair_30d * rate_f + (1 - w_pair) * model
    lo_mult, hi_mult = spread_for(n_pair)

    sample = None if invite else sample_cost_of(pool, kol, prod, qty)
    if not invite and sample is None:
        return None
    base = float(prod.base_per_order)
    commission_po = new * base
    net_po = float(prod.precommission_per_order) - commission_po
    return Forecast(
        kol=kol,
        item_id=item_id,
        product=prod,
        invite=invite,
        qty=0 if invite else qty,
        rate_pct=rate_pct,
        cur_rate_pct=None if cur is None else cur * 100,
        shrink={
            "kol_orders": float(n_kol),
            "kol_weight": round(w_kol, 4),
            "conv_kol": conv_kol,
            "conv_shop": conv_shop,
            "conv_used": conv_used,
            "clicks_30d": float(kol.clicks_per_30d),
            "product_weight": round(w_prod, 4),
            "product_factor": round(product_f, 4),
            "channel_fit": round(channel_f, 4),
            "rate_factor": round(rate_f, 4),
            "invite_factor": invite_f,
            "pair_orders": float(n_pair),
            "pair_weight": round(w_pair, 4),
            "model_orders": model,
        },
        pair_orders=n_pair,
        orders_lo=mid * lo_mult,
        orders_mid=mid,
        orders_hi=mid * hi_mult,
        sample=sample,
        gmv_per_order=float(prod.aov),
        commission_per_order=commission_po,
        net_per_order=net_po,
    )


# ------------------------------------------------------------------------------ the card


def _pct_snap(rate: Decimal | None) -> float:
    if rate is None:
        return DEFAULT_RATE_PCT
    snapped = (rate * 100 / RATE_STEP).to_integral_value() * RATE_STEP
    return float(min(max(snapped, Decimal(0)), Decimal(50)))


def _inputs_of(cand: Candidate, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    inputs = dict(cand.inputs if overrides is None else overrides)
    inputs.setdefault("item_id", cand.item)
    return inputs


def forecast_of(env: RecoEnv, cand: Candidate, inputs: dict[str, Any]) -> Forecast | None:
    pool: KolPool | None = getattr(env, "kol", None)
    kol = (cand.extra or {}).get("kol") or {}
    item = inputs.get("item_id") or cand.item
    if pool is None or not kol.get("key") or not item:
        return None
    invite = cand.kind == "affiliate_invite"
    rate = float(inputs.get("commission_pct", DEFAULT_RATE_PCT))
    qty = int(inputs["qty"]) if inputs.get("qty") is not None else DEFAULT_QTY
    if not 0 <= rate <= 50 or (not invite and not 1 <= qty <= 50):
        return None
    return forecast(pool, kol["key"], str(item), qty=qty, rate_pct=rate, invite=invite)


def _money(f: Forecast) -> dict[str, Any]:
    """``predicted.money_per_month`` in the shape ``prediction.convert`` gives every card: the
    certain layer is the sample cost, the predicted layer the orders' revenue and profit."""
    out: dict[str, Any] = {
        "days": config.DAYS_PER_MONTH,
        "certain": {"dgmv": 0.0, "dprofit": -f.sample_cost, "dchi": f.sample_cost},
        "predicted": {},
        "total": {},
    }
    for q in ("p10", "p25", "p50", "p75", "p90"):
        at = f.at(f.orders_at(q))
        out["predicted"][q] = {
            "dgmv": at["gmv"],
            "dorders": at["orders"],
            "dprofit": at["net_profit"],
        }
        out["total"][q] = {
            "dgmv": at["gmv"],
            "dorders": at["orders"],
            "dprofit": at["profit_after_sample"],
        }
    return out


def evaluation_of(env: RecoEnv, cand: Candidate, inputs: dict[str, Any]) -> Evaluation:
    """The generic :class:`Evaluation` of a KOL candidate (``evaluate.eval_kol`` returns it)."""
    from juli_backend.services.shopee_analytics.fmt import num
    from juli_backend.services.shopee_recommendations.evaluate import (
        _floor_with_commission,
        _refuse,
        _spend_check,
    )

    f = forecast_of(env, cand, inputs)
    if f is None:
        return _refuse("no_kol_data")
    spend_per_day = Decimal(str((f.sample_cost + (f.at(f.orders_mid)["commission"] or 0.0)) / 30))
    breaches: list[dict[str, Any]] = []
    new_rate = Decimal(str(f.rate_pct)) / 100
    for sku in env.floors(f.item_id):
        mine = [
            (ln, pb)
            for ln, pb in env.view.pairs
            if ln.sku == sku and ln.product_id == f.item_id and pb.excluded_reason is None
        ]
        units = sum(ln.qty for ln, _ in mine)
        if not units:
            continue
        unit_paid = sum((pb.revenue for _, pb in mine), ZERO) / units
        floor_px = _floor_with_commission(env, f.item_id, sku, new_rate)
        if floor_px is not None and unit_paid < floor_px:
            breaches.append(
                {
                    "sku": sku,
                    "kind": "operating",
                    "floor": num(floor_px),
                    "min_unit_price": num(unit_paid),
                    "lines": len(mine),
                }
            )
    mid = f.at(f.orders_mid)
    pm = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=Decimal(str(mid["gmv"])) / 30,
        base_orders_per_day=Decimal(str(f.orders_mid)) / 30,
        aov=Decimal(str(f.gmv_per_order)) if f.gmv_per_order else None,
        profit_per_gmv=None
        if not f.gmv_per_order
        else Decimal(str(f.net_per_order / f.gmv_per_order)),
        extra_cost_per_day=Decimal(str(f.sample_cost)) / 30,
        dchi_per_day=spend_per_day,
        base_label="kol_orders",
    )
    certain = {
        "kind": "kol",
        "sample_cost": None if f.sample is None else num(f.sample.cost),
        "sample_qty": f.qty,
        "sample_unit_cost": None
        if f.sample is None
        else num(f.sample.unit_cogs + f.sample.unit_packaging),
        "sample_cost_label": None if f.sample is None else f.sample.label,
        "ship_fee": None if f.sample is None else num(f.sample.ship_fee),
        "note": "Phần chắc chắn chỉ có chi phí mẫu; đơn và lợi nhuận từ KOL là phần dự kiến.",
    }
    notes = []
    if f.low_data:
        notes.append(
            f"{LOW_DATA_LABEL}: cặp KOL × sản phẩm này có {f.pair_orders} đơn "
            f"(dưới {ORDERS_THRESHOLD}); Juli kéo ước tính về mức trung bình của shop "
            "và để khoảng rộng."
        )
    if f.sample is not None and f.sample.ship_source != "kol":
        notes.append(
            "Phí ship dùng mức trung vị của shop."
            if f.sample.ship_source == "shop_median"
            else "Chưa có phí ship nào trong Mẫu KOL: đang tính 0đ."
        )
    if f.product.rate is None:
        notes.append("Chưa biết hoa hồng hiện tại của sản phẩm này.")
    return Evaluation(
        certain=certain,
        five=None,
        breaches=breaches,
        profit=pm,
        before={
            "commission_pct": None if f.cur_rate_pct is None else round(f.cur_rate_pct, 2),
            "samples_sent": f.kol.shipments,
        },
        after={"commission_pct": f.rate_pct, "qty": f.qty},
        target={
            "item_id": f.item_id,
            "kol_key": f.kol.key,
            "handle": f.kol.handle,
            "channel": f.kol.channel,
        },
        spend_check=_spend_check(env, spend_per_day),
        notes=notes,
    )


def _label(cand: Candidate, f: Forecast) -> str:
    return f"{spec(cand.kind).label} — {f.kol.handle} · {f.product.name}"


def _choices(env: RecoEnv, cand: Candidate, chosen: str) -> list[dict[str, Any]]:
    pool = env.kol
    assert pool is not None
    key = cand.extra["kol"]["key"]
    invite = cand.kind == "affiliate_invite"
    out: list[dict[str, Any]] = []
    for item in pool.products:
        f = forecast(
            pool,
            key,
            item,
            qty=default_qty(pool.kols.get(key)),
            rate_pct=_pct_snap(pool.products[item].rate),
            invite=invite,
        )
        if f is None:
            continue
        at = f.at(f.orders_mid)
        out.append(
            {
                "value": item,
                "label": f.product.name,
                "orders_p50": round(f.orders_mid, 2),
                "profit_p50": round(float(at["profit_after_sample"] or 0)),
                "selected": item == chosen,
            }
        )
    out.sort(key=lambda c: -c["profit_p50"])
    return out[:8]


def default_qty(kol: KolStat | None) -> int:
    q = kol.typical_qty if kol and kol.typical_qty else DEFAULT_QTY
    return min(max(int(q), 1), 50)


def build_kol_card(env: RecoEnv, cand: Candidate, *, now: datetime) -> dict[str, Any] | None:
    """The whole card payload (same keys as ``cards.build_card``) for a KOL candidate."""
    from juli_backend.services.shopee_recommendations.cards import _in_stock, shop_deltas
    from juli_backend.services.shopee_recommendations.plan import MetricStats, measurement_plan
    from juli_backend.services.shopee_recommendations.sheet import _step, build_sheet

    inputs = _inputs_of(cand)
    ev = evaluation_of(env, cand, inputs)
    if ev.refusal:
        return None
    f = forecast_of(env, cand, inputs)
    assert f is not None
    cand = replace(cand, items=(f.item_id,), inputs=inputs)
    s = spec(cand.kind)
    money = _money(f)
    mid = f.at(f.orders_mid)
    plan = measurement_plan(
        "orders",
        MetricStats(None, 0.0, f.orders_mid / 30, f.orders_mid / 30, None, 1.0),
    )
    sheet = build_sheet(cand.kind, ev.target, ev.before, ev.after, dict(inputs))
    steps = []
    n = 0
    if not f.invite:
        n += 1
        steps.append(_step(n, f"Gửi mẫu — {f.product.name} cho {f.kol.handle}", None, f.qty, "mẫu"))
        n += 1
        steps.append(
            _step(
                n,
                "Ghi vào Cài đặt › Thông số shop › Mẫu KOL (số lượng, ngày gửi, phí ship)",
                None,
                None,
            )
        )
    else:
        n += 1
        steps.append(_step(n, f"Mời {f.kol.handle} quảng bá {f.product.name}", None, None))
    n += 1
    steps.append(
        _step(
            n,
            f"Hoa hồng cho {f.product.name} (%)",
            ev.before.get("commission_pct"),
            f.rate_pct,
            "%",
        )
    )
    sheet["steps"] = steps
    sheet["revert_steps"] = [
        {**st, "before": st["after"], "after": st["before"], "copy": None} for st in steps
    ]
    spend = ev.spend_check or {}
    p50 = money["total"]["p50"]["dprofit"]
    kol_block = {
        "kol_key": f.kol.key,
        "handle": f.kol.handle,
        "channel": f.kol.channel,
        "invite": f.invite,
        "roi_shopee": None if f.kol.roi_shopee is None else float(f.kol.roi_shopee),
        "product": {"item_id": f.item_id, "name": f.product.name},
        "qty": f.qty,
        "commission_pct": f.rate_pct,
        "commission_pct_current": None if f.cur_rate_pct is None else round(f.cur_rate_pct, 2),
        "commission_source": f.product.rate_source,
        "sample": None
        if f.sample is None
        else {
            "cost": float(f.sample.cost),
            "unit_cogs": float(f.sample.unit_cogs),
            "unit_packaging": float(f.sample.unit_packaging),
            "ship_fee": float(f.sample.ship_fee),
            "ship_source": f.sample.ship_source,
            "cogs_source": f.sample.cogs_source,
            "label": f.sample.label,
        },
        "expected": {
            "orders": {q: round(f.orders_at(q), 2) for q in ("p10", "p50", "p90")},
            "gmv": round(mid["gmv"] or 0),
            "commission": round(mid["commission"] or 0),
            "net_profit": round(mid["net_profit"] or 0),
            "profit_after_sample": round(mid["profit_after_sample"] or 0),
            "profit_after_sample_range": [
                round(f.at(f.orders_lo)["profit_after_sample"] or 0),
                round(f.at(f.orders_hi)["profit_after_sample"] or 0),
            ],
            "roi_incl_samples": None
            if mid["roi_incl_samples"] is None
            else round(mid["roi_incl_samples"], 4),
            "payback_orders": f.payback_orders,
            "net_per_order": round(f.net_per_order),
        },
        "low_data": f.low_data,
        "low_data_label": LOW_DATA_LABEL if f.low_data else None,
        "pair_orders": f.pair_orders,
        "orders_threshold": ORDERS_THRESHOLD,
        "shrinkage": f.shrink,
        "choices": _choices(env, cand, f.item_id),
        "measurement": {
            "kind": "kol_pair",
            "metric": "orders",
            "kol_key": f.kol.key,
            "item_id": f.item_id,
            "send_date": None,
            "baseline_days": config.PLAN_PRE_DAYS,
            "note": "Đo đơn của cặp KOL × sản phẩm, trước và sau ngày gửi.",
        },
    }
    return {
        "schema": config.SCHEMA,
        "family": s.family,
        "family_label": FAMILY_LABELS[s.family],
        "change_kind": cand.kind,
        "title": _label(cand, f),
        "reason": cand.reason,
        "platform": "shopee",
        "model_version": config.MODEL_VERSION,
        "generated_at": now.isoformat(),
        "as_of": env.as_of.isoformat(),
        "window": env.view.window.json(),
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
        "metric": {
            "key": s.target_metric,
            "critical_id": None,
            "critical_kpi": None,
            "flow": "lien_ket",
            "at_stake_per_day": None,
            "at_stake_per_month": None,
        },
        "wiring": {"critical_metric": None, "allowed_kinds": []},
        "scope": {
            "level": "item",
            "product_ids": [f.item_id],
            "sku_ids": sorted(env.skus_of(f.item_id)),
            "campaign_key": cand.campaign_key,
        },
        "change": {
            "change_kind": cand.kind,
            "target": ev.target,
            "before": ev.before,
            "after": ev.after,
        },
        "inputs": dict(inputs),
        "candidate_extra": dict(cand.extra),
        "wiring_key": None,
        "gap_pct": None,
        "whatif": {
            "sliders": _slider_rows(cand, inputs),
            "text_fields": [],
            "choices": [{"key": "item_id", "label": "Sản phẩm", "options": kol_block["choices"]}],
        },
        "certain": {**ev.certain, "label": "Chắc chắn"},
        "five_numbers": None,
        "floor": {"breaches": ev.breaches, "unknown_skus": [], "ok": not ev.breaches},
        "spend": ev.spend_check,
        "predicted": {
            "label": "Dự kiến",
            "model_version": config.MODEL_VERSION,
            "lift": {
                "metric": "orders",
                "source": "kol_shrinkage",
                "factor": 1.0,
                "range_scale": 1.0,
                "gap_bucket": "unknown",
                "sim": {},
            },
            "money_per_month": money,
            "base": "kol_orders",
            "sim": {},
        },
        "measurement_plan": plan,
        "execution_sheet": sheet,
        "notes": ev.notes,
        "rank_inputs": {
            "kpi_p25": shop_deltas(env, money),
            "dgmv_p25": money["total"]["p25"]["dgmv"],
            "dprofit_p50": p50,
            "floor_breach": bool(ev.breaches),
            "spend_after": spend.get("shop_chi_per_day_after"),
            "spend_cap": spend.get("cap"),
            "in_stock": _in_stock(env, cand),
            "kg_value": None,
            "items": [f.item_id],
        },
        "bundle": False,
        "kol": kol_block,
    }


def _slider_rows(cand: Candidate, inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for sl in spec(cand.kind).sliders:
        if inputs.get(sl.key) is None:
            continue
        rows.append(
            {
                "key": sl.key,
                "label": sl.label,
                "unit": sl.unit,
                "min": sl.minimum,
                "max": sl.maximum,
                "step": sl.step,
                "default": inputs[sl.key],
                "default_source": (cand.extra or {})
                .get("default_source", {})
                .get(sl.key, "generator"),
            }
        )
    return rows


# --------------------------------------------------------------------------- generation


def _reason(f: Forecast, invite: bool) -> str:
    lead = (
        f"{f.kol.handle} ({f.kol.channel}) chưa nhận mẫu nào: mời bán {f.product.name}, "
        "không tốn chi phí mẫu."
        if invite
        else f"{f.kol.handle} ({f.kol.channel}) đã nhận mẫu trước đây: gửi mẫu {f.product.name}."
    )
    tail = f" Dự kiến khoảng {f.orders_mid:.1f} đơn/tháng"
    if f.low_data:
        tail += f" ({LOW_DATA_LABEL}, khoảng rộng)"
    return lead + tail + "."


def candidate_for(
    pool: KolPool, kol: KolStat, item: str, *, invite: bool
) -> tuple[Candidate, Forecast] | None:
    prod = pool.products.get(item)
    if prod is None:
        return None
    qty = default_qty(kol)
    rate = _pct_snap(prod.rate)
    f = forecast(pool, kol.key, item, qty=qty, rate_pct=rate, invite=invite)
    if f is None:
        return None
    inputs: dict[str, Any] = {"item_id": item, "commission_pct": rate}
    if not invite:
        inputs["qty"] = qty
    cand = Candidate(
        kind="affiliate_invite" if invite else "affiliate_sample",
        items=(item,),
        inputs=inputs,
        campaign_key=f"kol:{kol.key}",
        critical=None,
        reason=_reason(f, invite),
        wiring_key=None,
        extra={"kol": {"key": kol.key, "handle": kol.handle, "channel": kol.channel}},
    )
    return cand, f


def _score(f: Forecast) -> float:
    """Expected profit per sample (per sample sent; a no-sample invite is its whole profit)."""
    profit = f.at(f.orders_mid)["profit_after_sample"] or 0.0
    return profit / f.qty if f.qty else profit


def generate(env: RecoEnv) -> list[Candidate]:
    """One card per creator: the product with the best expected profit per sample, with the
    runners-up recorded for the versions. Creators with a sample on record get "Gửi mẫu", the
    others "Mời KOL". A pair that already got a sample, or a product out of stock, is skipped."""
    pool: KolPool | None = getattr(env, "kol", None)
    if pool is None:
        return []
    ranked: list[tuple[float, Candidate]] = []
    for kol in pool.kols.values():
        invite = kol.shipments == 0
        scored: list[tuple[float, Candidate]] = []
        for item, prod in pool.products.items():
            if prod.in_stock is False or prod.orders < config.MIN_PRODUCT_ORDERS:
                continue
            if (kol.key, item) in pool.sent_pairs:
                continue
            made = candidate_for(pool, kol, item, invite=invite)
            if made is None:
                continue
            cand, f = made
            scored.append((_score(f), cand))
        scored.sort(key=lambda t: (-t[0], t[1].item or ""))
        if not scored or scored[0][0] <= 0:
            continue
        best_score, best = scored[0]
        best.extra["alternatives"] = [
            c.item for s, c in scored[1 : 1 + PRODUCT_ALTERNATIVES] if c.item
        ]
        ranked.append((best_score, best))
    ranked.sort(key=lambda t: (-t[0], t[1].campaign_key or ""))
    return [c for _, c in ranked[:KOL_CARDS_MAX]]


def product_alternatives(env: RecoEnv, cand: Candidate) -> list[tuple[str, Candidate]]:
    """Versions that pitch another product to the same creator (labelled with the product)."""
    pool: KolPool | None = getattr(env, "kol", None)
    kol = pool.kols.get(cand.extra["kol"]["key"]) if pool and cand.extra.get("kol") else None
    if pool is None or kol is None:
        return []
    out: list[tuple[str, Candidate]] = []
    for item in (cand.extra.get("alternatives") or [])[:PRODUCT_ALTERNATIVES]:
        made = candidate_for(pool, kol, item, invite=cand.kind == "affiliate_invite")
        if made is None:
            continue
        alt, _ = made
        out.append(
            (
                f"Sản phẩm: {pool.products[item].name}",
                replace(alt, reason=cand.reason, extra={**cand.extra}),
            )
        )
    return out


async def attach_kol_cards(
    session: Any, shop_id: Any, payload: dict[str, Any], *, audience: str
) -> dict[str, Any]:
    """``row["card"]`` on the KOL table rows that have an open KOL card for the creator (seller:
    published only; Ops: drafts too). The card nearest the top of its product queue wins."""
    from juli_backend.services.shopee_recommendations import store
    from juli_backend.services.shopee_recommendations.refs import OPS_STATUSES, SELLER_STATUSES

    statuses = OPS_STATUSES if audience == "ops" else SELLER_STATUSES
    by_kol: dict[str, list[tuple[int, int, dict[str, Any]]]] = {}
    for p, card in await store.list_cards(session, shop_id, statuses=statuses):
        if card.get("change_kind") not in KOL_KINDS:
            continue
        key = ((card.get("candidate_extra") or {}).get("kol") or {}).get("key")
        if not key:
            continue
        ref = {
            "id": str(p.id),
            "code": p.code,
            "change_kind": card["change_kind"],
            "kind_label": spec(card["change_kind"]).label,
            "title": card["title"],
            "product_queue": p.product_queue,
            "item_id": (card["scope"]["product_ids"] or [None])[0],
        }
        by_kol.setdefault(key, []).append(
            (p.product_queue or 99, int((card.get("rank") or {}).get("position") or 10**6), ref)
        )
    for row in payload.get("rows", []):
        found = by_kol.get(row["kol_key"])
        if found:
            row["card"] = min(found, key=lambda t: (t[0], t[1], t[2]["id"]))[2]
    return payload


__all__ = [
    "KOL_KINDS",
    "attach_kol_cards",
    "Forecast",
    "build_kol_card",
    "candidate_for",
    "evaluation_of",
    "forecast",
    "generate",
    "product_alternatives",
    "spread_for",
    "weight",
]
